import os
from email.message import EmailMessage

import requests
import smtplib

from app.core.config import settings


RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_RESEND_FROM = "AI会员 <support@aimembership.app>"


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


def _get_resend_from() -> str:
    return (
        _env("EMAIL_FROM")
        or _env("RESEND_FROM_EMAIL")
        or DEFAULT_RESEND_FROM
    )


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
        "from": _get_resend_from(),
        "to": [to_email],
        "subject": subject,
        "text": text_body,
    }

    if html_body:
        payload["html"] = html_body

    try:
        response = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except requests.Timeout as e:
        raise RuntimeError("Resend发送失败：请求超时，请稍后重试") from e
    except requests.RequestException as e:
        raise RuntimeError(f"Resend发送失败：网络请求异常：{e}") from e

    if response.status_code not in (200, 202):
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(
            f"Resend发送失败：HTTP {response.status_code} error: {detail}"
        )

    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    return {
        "ok": True,
        "provider": "resend",
        "to": to_email,
        "subject": subject,
        "from": payload["from"],
        "response": data,
    }


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

    port = int(settings.smtp_port or 587)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, port, timeout=30) as server:
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, port, timeout=30) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
    except TimeoutError as e:
        raise RuntimeError("SMTP连接超时，请检查SMTP_HOST、SMTP_PORT，或改用Resend API") from e
    except Exception as e:
        raise RuntimeError(f"SMTP发送失败：{e}") from e

    return {
        "ok": True,
        "provider": "smtp",
        "to": to_email,
        "subject": subject,
    }


def send_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> dict:
    if resend_is_configured():
        return _send_email_by_resend(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

    return _send_email_by_smtp(
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def _is_processing_delivery(delivery_content: str) -> bool:
    content = str(delivery_content or "")
    keywords = [
        "确认收款",
        "进入代开通流程",
        "请等待处理完成通知",
        "等待处理完成",
        "正在处理",
        "处理中",
    ]
    return any(k in content for k in keywords)


def send_delivery_email(
    target_email: str,
    product_code: str,
    order_no: str,
    delivery_content: str,
) -> dict:
    is_processing = _is_processing_delivery(delivery_content)

    if is_processing:
        subject = f"订单正在处理中：{order_no}"
        title = "订单正在处理中"
        intro = "您好，您的订单已确认收款，目前正在进入代开通流程。"
        footer = "处理完成后，我们会再次通过邮件通知您，请耐心等待。"
    else:
        subject = f"订单已完成：{order_no}"
        title = "订单已处理完成"
        intro = "您好，您的订单已处理完成，详情如下："
        footer = "感谢您的支持。"

    text_body = (
        f"您好，\n\n"
        f"{intro}\n\n"
        f"订单号：{order_no}\n"
        f"产品套餐：{product_code}\n"
        f"订单内容：\n{delivery_content}\n\n"
        f"{footer}"
    )

    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #111827; line-height: 1.7;">
        <div style="max-width: 640px; margin: 0 auto; padding: 24px; border: 1px solid #e5e7eb; border-radius: 12px;">
          <h2 style="margin-top: 0; color: #111827;">{title}</h2>
          <p>{intro}</p>
          <p><strong>订单号：</strong>{order_no}</p>
          <p><strong>产品套餐：</strong>{product_code}</p>
          <p><strong>订单内容：</strong></p>
          <div style="white-space: pre-wrap; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px;">{delivery_content}</div>
          <p style="color: #6b7280; font-size: 13px; margin-top: 20px;">{footer}</p>
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
