"""Small Worker-owned HTTP(S) egress proxy for the isolated sandbox."""

from __future__ import annotations

import argparse
import ipaddress
import os
import select
import signal
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit

MAX_HEADER_BYTES = 64 * 1024
MAX_CONNECTIONS = 16
MAX_RELAY_BYTES = 512 * 1024 * 1024
RELAY_BUFFER_BYTES = 64 * 1024
IDLE_TIMEOUT_SECONDS = 30.0
CONNECT_TIMEOUT_SECONDS = 5.0
PUBLIC_PORTS = frozenset({80, 443})
PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)


class ProxyRequestError(ValueError):
    """The client requested an invalid or disallowed destination."""


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global


def _resolve_public(host: str, port: int) -> tuple[str, ...]:
    host = host.strip().rstrip(".")
    if not host or len(host) > 253:
        raise ProxyRequestError("invalid destination host")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ProxyRequestError("destination DNS lookup failed") from exc
        addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
    else:
        addresses = (host.strip("[]"),)
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise ProxyRequestError("destination is not public")
    return addresses


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ProxyRequestError("invalid destination port") from exc
    if port not in PUBLIC_PORTS:
        raise ProxyRequestError("only public HTTP(S) ports are allowed")
    return port


def _host_port(value: str) -> tuple[str, int]:
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        if end < 0 or not value[end + 1 :].startswith(":"):
            raise ProxyRequestError("invalid CONNECT target")
        return value[1:end], _port(value[end + 2 :])
    if value.count(":") != 1:
        raise ProxyRequestError("invalid CONNECT target")
    host, raw_port = value.rsplit(":", 1)
    if not host:
        raise ProxyRequestError("invalid CONNECT target")
    return host, _port(raw_port)


def _read_request(client: socket.socket) -> tuple[bytes, bytes]:
    data = bytearray()
    client.settimeout(IDLE_TIMEOUT_SECONDS)
    while b"\r\n\r\n" not in data:
        chunk = client.recv(RELAY_BUFFER_BYTES)
        if not chunk:
            raise ProxyRequestError("empty proxy request")
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise ProxyRequestError("proxy headers are too large")
    header, remainder = bytes(data).split(b"\r\n\r\n", 1)
    return header, remainder


def _headers(header: bytes) -> tuple[str, str, list[tuple[str, str]]]:
    try:
        lines = header.decode("latin-1").split("\r\n")
    except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 accepts bytes
        raise ProxyRequestError("invalid proxy headers") from exc
    if not lines or len(lines[0].split()) != 3:
        raise ProxyRequestError("invalid proxy request line")
    method, target, version = lines[0].split()
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ProxyRequestError("unsupported HTTP version")
    parsed: list[tuple[str, str]] = []
    for line in lines[1:]:
        if ":" not in line:
            raise ProxyRequestError("invalid proxy header")
        name, value = line.split(":", 1)
        if not name or any(ord(char) < 33 or ord(char) > 126 for char in name):
            raise ProxyRequestError("invalid proxy header name")
        if any(ord(char) < 32 and char not in "\t" for char in value):
            raise ProxyRequestError("invalid proxy header value")
        parsed.append((name, value.strip()))
    return method, target, parsed


def _destination(
    method: str, target: str
) -> tuple[str, int, str | None, str | None]:
    if method.upper() == "CONNECT":
        host, port = _host_port(target)
        return host, port, None, None

    try:
        parsed = urlsplit(target)
    except ValueError as exc:
        raise ProxyRequestError("invalid proxy URL") from exc
    if parsed.scheme.lower() != "http" or not parsed.netloc:
        raise ProxyRequestError("HTTP proxy requires an absolute HTTP URL")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ProxyRequestError("invalid proxy URL")
    host = parsed.hostname
    if not host:
        raise ProxyRequestError("invalid proxy URL host")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise ProxyRequestError("invalid destination port") from exc
    if port not in PUBLIC_PORTS or port != 80:
        raise ProxyRequestError("only public HTTP(S) ports are allowed")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    host_header = f"[{host}]:{port}" if ":" in host else host
    return host, port, path, host_header


def _relay(left: socket.socket, right: socket.socket) -> None:
    peers = {left: right, right: left}
    transferred = {left: 0, right: 0}
    while peers:
        try:
            readable, _, _ = select.select(list(peers), (), (), IDLE_TIMEOUT_SECONDS)
        except (OSError, ValueError):
            return
        if not readable:
            return
        for source in readable:
            target = peers[source]
            try:
                data = source.recv(RELAY_BUFFER_BYTES)
            except OSError:
                return
            if not data:
                return
            transferred[source] += len(data)
            if transferred[source] > MAX_RELAY_BYTES:
                return
            try:
                target.sendall(data)
            except OSError:
                return


def _error(client: socket.socket, status: str, message: str) -> None:
    body = f"{status}: {message}\n".encode("utf-8")
    try:
        client.sendall(
            f"HTTP/1.1 {status}\r\nConnection: close\r\n"
            f"Content-Length: {len(body)}\r\nContent-Type: text/plain\r\n\r\n".encode()
            + body
        )
    except OSError:
        pass


def _connect(host: str, port: int) -> socket.socket:
    addresses = _resolve_public(host, port)
    last_error: OSError | None = None
    for address in addresses:
        try:
            upstream = socket.create_connection(
                (address, port), timeout=CONNECT_TIMEOUT_SECONDS
            )
            upstream.settimeout(IDLE_TIMEOUT_SECONDS)
            return upstream
        except OSError as exc:
            last_error = exc
    raise OSError("public destination is unreachable") from last_error


def _serve_client(client: socket.socket) -> None:
    upstream: socket.socket | None = None
    try:
        header, remainder = _read_request(client)
        method, target, request_headers = _headers(header)
        host, port, path, host_header = _destination(method, target)
        upstream = _connect(host, port)
        if path is None:
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if remainder:
                upstream.sendall(remainder)
        else:
            forwarded = [f"{method} {path} HTTP/1.1"]
            for name, value in request_headers:
                lowered = name.lower()
                if lowered in {
                    "connection",
                    "keep-alive",
                    "proxy-connection",
                    "proxy-authenticate",
                    "proxy-authorization",
                    "te",
                    "trailer",
                    "upgrade",
                    "host",
                }:
                    continue
                forwarded.append(f"{name}: {value}")
            forwarded.extend((f"Host: {host_header}", "Connection: close", ""))
            client_request = ("\r\n".join(forwarded) + "\r\n").encode("latin-1")
            upstream.sendall(client_request + remainder)
        _relay(client, upstream)
    except ProxyRequestError as exc:
        _error(client, "403 Forbidden", str(exc))
    except (OSError, TimeoutError):
        _error(client, "502 Bad Gateway", "public destination unavailable")
    finally:
        try:
            client.close()
        finally:
            if upstream is not None:
                upstream.close()


class LocalEgressProxy:
    """Loopback listener inside the sandbox, relaying to a Worker Unix socket."""

    def __init__(self, egress_socket: str | Path):
        self.egress_socket = Path(egress_socket)
        if not self.egress_socket.is_absolute():
            raise ValueError("sandbox egress socket must be absolute")
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(MAX_CONNECTIONS)
        self._listener.settimeout(0.2)
        self._closed = threading.Event()
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._thread: threading.Thread | None = None
        self._connections: set[socket.socket] = set()
        self._connections_lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._listener.getsockname()[1]}"

    def environment(self) -> dict[str, str]:
        return {
            name: "" if name.lower() == "no_proxy" else self.url
            for name in PROXY_ENV_NAMES
        }

    def start(self) -> str:
        if self._thread is not None:
            return self.url
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self.url

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                client, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not self._slots.acquire(blocking=False):
                client.close()
                continue
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        with self._connections_lock:
            self._connections.add(client)
        try:
            upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            upstream.settimeout(CONNECT_TIMEOUT_SECONDS)
            upstream.connect(str(self.egress_socket))
            upstream.settimeout(IDLE_TIMEOUT_SECONDS)
            with self._connections_lock:
                self._connections.add(upstream)
            _relay(client, upstream)
        except OSError:
            pass
        finally:
            with self._connections_lock:
                self._connections.discard(client)
                if upstream is not None:
                    self._connections.discard(upstream)
            client.close()
            if upstream is not None:
                upstream.close()
            self._slots.release()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._listener.close()
        with self._connections_lock:
            connections = tuple(self._connections)
        for connection in connections:
            connection.close()
        if self._thread is not None:
            self._thread.join(timeout=1)


def serve_fd(fd: int) -> None:  # pragma: no cover - separate Worker process
    if fd < 0:
        raise ValueError("proxy listener fd must be non-negative")
    listener = socket.socket(fileno=fd)
    listener.set_inheritable(False)
    listener.settimeout(0.5)
    slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()
        listener.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopped.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not slots.acquire(blocking=False):
                client.close()
                continue
            threading.Thread(
                target=_serve_with_slot, args=(client, slots), daemon=True
            ).start()
    finally:
        listener.close()


def _serve_with_slot(  # pragma: no cover - separate Worker process
    client: socket.socket, slots: threading.BoundedSemaphore
) -> None:
    try:
        _serve_client(client)
    finally:
        slots.release()


def main() -> None:  # pragma: no cover - separate Worker process
    parser = argparse.ArgumentParser()
    parser.add_argument("--fd", required=True, type=int)
    args = parser.parse_args()
    if os.name != "posix":
        raise SystemExit("the egress proxy requires a POSIX host")
    serve_fd(args.fd)


if __name__ == "__main__":
    main()
