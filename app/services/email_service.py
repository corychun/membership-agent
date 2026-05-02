import os
import requests

RESEND_API_KEY = os.getenv("RESEND_API_KEY")


def send_email(to_email: str, subject: str, html_content: str):
    if not RESEND_API_KEY:
        print("❌ RESEND_API_KEY 未配置")
        return False

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": "AI会员 <onboarding@resend.dev>",
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            },
            timeout=10,
        )

        if response.status_code == 200:
            print("✅ 邮件发送成功")
            return True
        else:
            print("❌ 邮件发送失败:", response.text)
            return False

    except Exception as e:
        print("❌ 邮件异常:", str(e))
        return False
