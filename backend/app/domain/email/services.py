"""Pure system-email templates."""

from dataclasses import dataclass
from html import escape


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


def _html(title: str, paragraphs: list[str], action: tuple[str, str] | None = None) -> str:
    content = "".join(f"<p>{escape(item)}</p>" for item in paragraphs)
    if action is not None:
        label, url = action
        content += (
            '<p><a href="'
            + escape(url, quote=True)
            + '" style="display:inline-block;padding:10px 16px;background:#111827;'
            'color:#fff;text-decoration:none;border-radius:6px">'
            + escape(label)
            + "</a></p>"
        )
    return (
        '<!doctype html><html><body style="font-family:Arial,sans-serif;'
        'line-height:1.6;color:#111827;max-width:640px;margin:0 auto;padding:24px">'
        f"<h2>{escape(title)}</h2>{content}"
        '<p style="color:#6b7280">NexaFlow</p></body></html>'
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
        url = _required(payload, "url")
        subject = f"NexaFlow 工作空间邀请 / Workspace invitation - {workspace}"
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
            _html(subject, paragraphs, ("接受邀请 / Accept invitation", url)),
        )

    if kind == "welcome":
        workspace = _required(payload, "workspace")
        username = _required(payload, "username")
        url = _required(payload, "url")
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
            _html(subject, paragraphs, ("登录 NexaFlow / Sign in", url)),
        )

    if kind == "password_reset":
        url = _required(payload, "url")
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
            _html(subject, paragraphs, ("重置密码 / Reset password", url)),
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
        _html(subject, paragraphs),
    )
