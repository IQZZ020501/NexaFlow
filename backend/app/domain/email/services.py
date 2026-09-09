"""Pure system-email templates."""

from dataclasses import dataclass
from html import escape
from urllib.parse import urlsplit


EMAIL_KINDS = {
    "workspace_invitation",
    "welcome",
    "password_changed",
    "password_reset",
}


class EmailPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedEmail:
    recipient: str
    subject: str
    text_body: str
    html_body: str


def _required(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise EmailPayloadError(f"Missing email payload field: {key}.")
    return value


def _header_fragment(value: str, key: str) -> str:
    if "\r" in value or "\n" in value:
        raise EmailPayloadError(f"Invalid email payload field: {key}.")
    return value


def _validate_url(value: str, key: str = "url") -> str:
    """Return an absolute web URL suitable for an email action link."""
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise EmailPayloadError(f"Invalid email payload URL: {key}.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
    except ValueError as exc:
        raise EmailPayloadError(f"Invalid email payload URL: {key}.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or username is not None
        or password is not None
    ):
        raise EmailPayloadError(f"Invalid email payload URL: {key}.")
    return value


def _safe_url(payload: dict[str, object], key: str = "url") -> str:
    return _validate_url(_required(payload, key), key)


def _html(
    title: str,
    paragraphs: list[str],
    action: tuple[str, str] | None = None,
    *,
    subject: str | None = None,
    eyebrow: str | None = None,
) -> str:
    content = "".join(
        '<p style="margin:0 0 16px;color:#182230;font-size:16px;'
        'line-height:1.6;word-break:break-word;overflow-wrap:anywhere">'
        f"{escape(item)}</p>"
        for item in paragraphs
    )
    if action is not None:
        label, url = action
        _validate_url(url, "action")
        escaped_url = escape(url, quote=True)
        content += (
            '<p style="margin:28px 0 18px;text-align:left">'
            '<a href="'
            + escaped_url
            + '" style="display:inline-block;max-width:100%;box-sizing:border-box;'
            'padding:14px 22px;background:#4f46e5;color:#ffffff;'
            'font-size:16px;font-weight:700;line-height:1.4;text-align:center;'
            'text-decoration:none;border-radius:9px;word-break:break-word;'
            'box-shadow:0 3px 8px rgba(79,70,229,0.22)">'
            + escape(label)
            + "</a></p>"
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'border="0" style="width:100%;border-collapse:separate;background-color:#f8f9ff;'
            'border:1px solid #e0e7ff;border-radius:10px">'
            '<tr><td style="padding:14px 16px">'
            '<p style="margin:0 0 6px;color:#667085;font-size:13px;line-height:1.5">'
            "如果按钮无法使用，请复制以下链接 / If the button does not work, copy this link:"
            '</p><a href="'
            + escaped_url
            + '" style="color:#3155d8;font-size:13px;line-height:1.5;'
            'text-decoration:underline;word-break:break-word;overflow-wrap:anywhere">'
            "打开链接 / Open link"
            "</a></td></tr></table>"
        )
    eyebrow_html = (
        '<p style="margin:0 0 10px;color:#4f46e5;font-size:12px;font-weight:700;'
        'letter-spacing:0.08em;line-height:1.4;text-transform:uppercase;'
        'word-break:break-word;overflow-wrap:anywhere">'
        f"{escape(eyebrow)}</p>"
        if eyebrow
        else ""
    )
    return (
        '<!doctype html>'
        '<html lang="zh-CN">'
        '<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{escape(subject or title)}</title>"
        "</head>"
        '<body style="margin:0;padding:0;background-color:#f3f5ff;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Arial,sans-serif;'
        'color:#182230;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="width:100%;border-collapse:collapse;background-color:#f3f5ff">'
        '<tr><td align="center" style="padding:32px 16px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="width:100%;max-width:600px;border-collapse:separate;'
        'background-color:#ffffff;border:1px solid #e5e7eb;border-radius:18px;'
        'overflow:hidden;box-shadow:0 12px 30px rgba(31,41,55,0.08)">'
        '<tr><td style="padding:24px 32px 20px;background-color:#ffffff;'
        'border-bottom:1px solid #eaecf0">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:collapse"><tr>'
        '<td style="width:34px;height:34px;background-color:#4f46e5;'
        'border-radius:10px;color:#ffffff;font-size:18px;font-weight:700;'
        'line-height:34px;text-align:center">N</td>'
        '<td style="padding-left:11px;color:#101828;font-size:20px;font-weight:700;'
        'letter-spacing:-0.01em">NexaFlow</td>'
        '<td align="right" style="color:#98a2b3;font-size:12px;line-height:1.4">'
        'Workspace platform</td>'
        '</tr></table>'
        '</td></tr>'
        '<tr><td style="padding:36px 32px 30px">'
        f"{eyebrow_html}"
        f'<h1 style="margin:0 0 22px;color:#101828;font-size:27px;line-height:1.25;'
        f'font-weight:700;letter-spacing:-0.02em;word-break:break-word;'
        f'overflow-wrap:anywhere">{escape(title)}</h1>'
        f"{content}"
        '</td></tr>'
        '<tr><td style="padding:22px 32px 26px;background-color:#fbfcfe;'
        'border-top:1px solid #eaecf0">'
        '<p style="margin:0 0 6px;color:#667085;font-size:12px;line-height:1.6">'
        '此邮件由 NexaFlow 自动发送，请勿直接回复。<br>'
        'This message was sent automatically by NexaFlow; please do not reply.'
        '</p>'
        '<p style="margin:0;color:#98a2b3;font-size:12px;line-height:1.5">'
        'NexaFlow · Secure workspace operations'
        '</p>'
        '</td></tr>'
        '</table>'
        '</td></tr>'
        '</table>'
        '</body></html>'
    )


def render_email(kind: str, payload: dict[str, object]) -> RenderedEmail:
    if kind not in EMAIL_KINDS:
        raise EmailPayloadError("Unsupported email kind.")
    recipient = _required(payload, "recipient")
    name = _required(payload, "name")

    if kind == "workspace_invitation":
        workspace = _required(payload, "workspace")
        inviter = _required(payload, "inviter")
        role = _required(payload, "role")
        url = _safe_url(payload)
        subject = (
            "NexaFlow 工作空间邀请 / Workspace invitation - "
            f"{_header_fragment(workspace, 'workspace')}"
        )
        paragraphs = [
            f"{name}，你好！{inviter} 邀请你以 {role} 身份加入工作空间“{workspace}”。",
            "邀请链接 7 天内有效且仅可领取一次。",
            f"Hello {name}, {inviter} invited you to join “{workspace}” as {role}.",
            "This invitation link is valid for 7 days and can be accepted once.",
        ]
        text = "\n\n".join(paragraphs + [f"接受邀请 / Accept invitation: {url}"])
        return RenderedEmail(
            recipient,
            subject,
            text,
            _html(
                "你已受邀加入 / You are invited to join",
                paragraphs,
                ("接受邀请 / Accept invitation", url),
                subject=subject,
                eyebrow=workspace,
            ),
        )

    if kind == "welcome":
        workspace = _required(payload, "workspace")
        username = _required(payload, "username")
        url = _safe_url(payload)
        subject = "欢迎使用 NexaFlow / Welcome to NexaFlow"
        paragraphs = [
            f"{name}，你的账号 {username} 已注册成功，并已加入工作空间“{workspace}”。",
            f"Hello {name}, your account {username} is ready and has joined “{workspace}”.",
        ]
        text = "\n\n".join(paragraphs + [f"登录 / Sign in: {url}"])
        return RenderedEmail(
            recipient,
            subject,
            text,
            _html(
                "欢迎加入 NexaFlow / Welcome",
                paragraphs,
                ("登录 NexaFlow / Sign in", url),
                subject=subject,
                eyebrow=workspace,
            ),
        )

    if kind == "password_reset":
        url = _safe_url(payload)
        subject = "重置 NexaFlow 密码 / Reset your NexaFlow password"
        paragraphs = [
            f"{name}，我们收到了你的密码重置请求。此链接将在 30 分钟后失效。",
            "如果不是你本人发起的请求，请忽略此邮件。",
            f"Hello {name}, we received a request to reset your password. This link expires in 30 minutes.",
            "If you did not request this, you can ignore this email.",
        ]
        text = "\n\n".join(paragraphs + [f"重置密码 / Reset password: {url}"])
        return RenderedEmail(
            recipient,
            subject,
            text,
            _html(
                "重置密码 / Reset your password",
                paragraphs,
                ("重置密码 / Reset password", url),
                subject=subject,
                eyebrow="NexaFlow account",
            ),
        )

    changed_by = _required(payload, "changed_by")
    changed_at = _required(payload, "changed_at")
    subject = "NexaFlow 密码已修改 / NexaFlow password changed"
    paragraphs = [
        f"{name}，你的 NexaFlow 密码已于 {changed_at} 修改（方式：{changed_by}）。",
        "如果这不是你的操作，请立即联系系统管理员。",
        f"Hello {name}, your NexaFlow password was changed at {changed_at} (method: {changed_by}).",
        "If you did not expect this change, contact your system administrator immediately.",
    ]
    return RenderedEmail(
        recipient,
        subject,
        "\n\n".join(paragraphs),
        _html(
            "密码安全通知 / Password security notice",
            paragraphs,
            subject=subject,
            eyebrow="NexaFlow account",
        ),
    )
