import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config  # Loads .env once for the process.
from email_renderer import render_email_content


SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")


def send_email_notification(
    papers,
    days=3,
    translate=False,
    time_window_extended=None,
    category_label="hep-ex",
    usage_summary=None,
):
    """发送论文通知邮件."""
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        print("邮件配置缺失，请设置环境变量：EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO")
        return False

    subject, html_content = render_email_content(
        papers,
        days=days,
        translate=translate,
        category_label=category_label,
        time_window_extended=time_window_extended,
        usage_summary=usage_summary,
    )

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html_content, "html"))

    try:
        print(f"正在连接 {SMTP_SERVER}:{SMTP_PORT}...")
        if SMTP_PORT == 465 or SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
            print("使用 SSL 连接...")
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            print("使用 STARTTLS 连接...")

        server.set_debuglevel(0)
        print(f"正在登录 {EMAIL_FROM}...")
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        print(f"正在发送邮件到 {EMAIL_TO}...")
        server.send_message(msg)
        server.quit()
        print(f"邮件已发送至 {EMAIL_TO}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP 认证失败：{e}")
        print("请检查 EMAIL_FROM 和 EMAIL_PASSWORD 是否正确")
        print("Gmail/163 用户需要使用授权码/应用专用密码，不是登录密码")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"SMTP 连接失败：{e}")
        print(f"请检查 SMTP_SERVER ({SMTP_SERVER}) 和 SMTP_PORT ({SMTP_PORT}) 是否正确")
        return False
    except Exception as e:
        print(f"邮件发送失败：{e}")
        return False
