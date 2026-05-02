from email.message import EmailMessage
import html
import smtplib
import socket
import ssl

from app.core.config import settings


DEFAULT_SMTP_TIMEOUT = 20


def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def smtp_is_configured() -> bool:
    return all(
        [
            _clean(settings.smtp_host),
            settings.smtp_port,
            _clean(settings.smtp_username),
            _clean(settings.smtp_password),
            _clean(settings.smtp_from_email),
        ]
    )


def _smtp_error_message(exc: Exception) -> str:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "SMTP连接超时，请检查SMTP_HOST、SMTP_PORT，以及当前部署平台是否允许连接该SMTP端口"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "SMTP认证失败，请检查SMTP_USERNAME和SMTP_PASSWORD。注意很多邮箱需要填写授权码，不是登录密码"
    if isinstance(exc, smtplib.SMTPConnectError):
        return "SMTP连接失败，请检查SMTP_HOST和SMTP_PORT"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "收件人邮箱被SMTP服务器拒绝，请检查客户邮箱是否正确"
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "发件人邮箱被SMTP服务器拒绝，请检查SMTP_FROM_EMAIL是否和SMTP账号匹配"
    return str(exc) or exc.__class__.__name__


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> dict:
    if not smtp_is_configured():
        raise ValueError("SMTP is not configured")

    host = _clean(settings.smtp_host)
    port = int(settings.smtp_port or 587)
    username = _clean(settings.smtp_username)
    password = _clean(settings.smtp_password)
    from_email = _clean(settings.smtp_from_email)
    from_name = _clean(settings.smtp_from_name) or "Membership Agent"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg.set_content(text_body)

    if html_body:
        msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()

    try:
        # 465 是 SSL 直连；587/25 通常是普通连接后 STARTTLS。
        # 之前所有端口都走 smtplib.SMTP + starttls，465 会非常容易 timed out。
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=DEFAULT_SMTP_TIMEOUT, context=context) as server:
                server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=DEFAULT_SMTP_TIMEOUT) as server:
                server.ehlo()
                if settings.smtp_use_tls:
                    server.starttls(context=context)
                    server.ehlo()
                server.login(username, password)
                server.send_message(msg)
    except Exception as exc:
        raise RuntimeError(_smtp_error_message(exc)) from exc

    return {
        "ok": True,
        "to": to_email,
        "subject": subject,
    }


def send_delivery_email(
    target_email: str,
    product_code: str,
    order_no: str,
    delivery_content: str,
) -> dict:
    subject = f"订单 {order_no} 已完成开通"
    safe_order_no = html.escape(str(order_no or ""))
    safe_product_code = html.escape(str(product_code or ""))
    safe_delivery_content = html.escape(str(delivery_content or "")).replace("\n", "<br>")

    text_body = (
        "您好，\n\n"
        "您的订单已完成处理。\n\n"
        f"订单号：{order_no}\n"
        f"产品套餐：{product_code}\n"
        f"开通结果：\n{delivery_content}\n\n"
        "如有问题，请联系网站客服。"
    )

    html_body = f"""
    <html>
      <body style="font-family:Arial,'Microsoft YaHei',sans-serif;line-height:1.7;color:#111827;">
        <h2>订单已完成开通</h2>
        <p>您好，您的订单已完成处理。</p>
        <p><strong>订单号：</strong>{safe_order_no}</p>
        <p><strong>产品套餐：</strong>{safe_product_code}</p>
        <p><strong>开通结果：</strong></p>
        <div style="padding:12px;border:1px solid #e5e7eb;border-radius:8px;background:#f9fafb;white-space:normal;">
          {safe_delivery_content}
        </div>
        <p style="margin-top:16px;color:#6b7280;font-size:13px;">如有问题，请联系网站客服。</p>
      </body>
    </html>
    """

    return send_email(
        to_email=target_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
