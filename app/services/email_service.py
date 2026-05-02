from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from html import escape

from app.core.config import settings


RESEND_API_URL = "https://api.resend.com/emails"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def resend_is_configured() -> bool:
    return bool(_env("RESEND_API_KEY"))


def smtp_is_configured() -> bool:
    return all(
        [
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_username,
            settings.smtp_password,
            settings.smtp_from_email,
        ]
    )


def _from_address() -> str:
    """
    Resend 默认测试发件人是 onboarding@resend.dev。
    如果你已经在 Resend 绑定并验证了自己的域名，可以在 Render 环境变量里配置：
    RESEND_FROM_EMAIL=support@你的域名
    RESEND_FROM_NAME=你的平台名称
    """
    from_email = _env("RESEND_FROM_EMAIL") or settings.smtp_from_email or "onboarding@resend.dev"
    from_name = _env("RESEND_FROM_NAME") or settings.smtp_from_name or "Membership Agent"
    return f"{from_name} <{from_email}>"


def _send_email_by_resend(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> dict:
    api_key = _env("RESEND_API_KEY")
    if not api_key:
        raise ValueError("RESEND_API_KEY is not configured")

    payload = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body

    request = urllib.request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            return {
                "ok": True,
                "provider": "resend",
                "to": to_email,
                "subject": subject,
                "id": data.get("id"),
                "raw": data,
            }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend发送失败：HTTP {e.code} {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Resend连接失败：{e.reason}") from e


def _send_email_by_smtp(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> dict:
    if not smtp_is_configured():
        raise ValueError("SMTP is not configured")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg.set_content(text_body)

    if html_body:
        msg.add_alternative(html_body, subtype="html")

    port = int(settings.smtp_port)
    timeout = 20

    # 465 使用 SMTP_SSL；587/25 通常使用 STARTTLS。
    if port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, port, timeout=timeout, context=context) as server:
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, port, timeout=timeout) as server:
            if settings.smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)

    return {
        "ok": True,
        "provider": "smtp",
        "to": to_email,
        "subject": subject,
    }


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> dict:
    """
    优先使用 Resend API，避免 Render 上 SMTP 超时。
    如果没有配置 RESEND_API_KEY，则保留原来的 SMTP 发送逻辑，不影响旧功能。
    """
    if resend_is_configured():
        return _send_email_by_resend(to_email, subject, text_body, html_body)

    return _send_email_by_smtp(to_email, subject, text_body, html_body)


def send_delivery_email(
    target_email: str,
    product_code: str,
    order_no: str,
    delivery_content: str,
) -> dict:
    subject = f"订单已完成：{order_no}"

    safe_product = product_code or "-"
    safe_order_no = order_no or "-"
    safe_delivery = delivery_content or "-"

    text_body = (
        "您好，\n\n"
        "您的订单已处理完成。\n\n"
        f"订单号：{safe_order_no}\n"
        f"产品套餐：{safe_product}\n"
        f"开通结果：{safe_delivery}\n\n"
        "如有问题，请联系网站客服。\n"
        "感谢使用。"
    )

    html_body = f"""
    <html>
      <body style="font-family:Arial,'Microsoft YaHei',sans-serif;background:#f6f7fb;padding:24px;color:#111827;">
        <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:14px;padding:24px;border:1px solid #e5e7eb;">
          <h2 style="margin:0 0 16px;color:#111827;">订单已处理完成</h2>
          <p style="line-height:1.7;">您好，您的会员代开通订单已处理完成，请查看下面的结果。</p>
          <div style="background:#f9fafb;border-radius:10px;padding:16px;margin:16px 0;line-height:1.8;">
            <p><strong>订单号：</strong>{escape(safe_order_no)}</p>
            <p><strong>产品套餐：</strong>{escape(safe_product)}</p>
            <p><strong>开通结果：</strong><br>{escape(safe_delivery).replace(chr(10), '<br>')}</p>
          </div>
          <p style="line-height:1.7;color:#374151;">如有问题，请联系网站客服。</p>
          <p style="font-size:12px;color:#6b7280;margin-top:24px;">此邮件由系统自动发送，请勿直接回复。</p>
        </div>
      </body>
    </html>
    """

    return send_email(
        to_email=target_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
