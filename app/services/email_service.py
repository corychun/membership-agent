from email.message import EmailMessage
import smtplib

from app.core.config import settings


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


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> dict:
    if not smtp_is_configured():
        raise ValueError("SMTP is not configured")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg.set_content(text_body)

    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)

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
    subject = f"Your delivery for {product_code}"

    text_body = (
        f"Hello,\n\n"
        f"Your order has been delivered successfully.\n\n"
        f"Order No: {order_no}\n"
        f"Product: {product_code}\n"
        f"Delivery result: {delivery_content}\n\n"
        f"Thank you."
    )

    html_body = f"""
    <html>
      <body>
        <h2>Your order has been delivered successfully</h2>
        <p><strong>Order No:</strong> {order_no}</p>
        <p><strong>Product:</strong> {product_code}</p>
        <p><strong>Delivery result:</strong><br>{delivery_content}</p>
        <p>Thank you.</p>
      </body>
    </html>
    """

    return send_email(
        to_email=target_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )