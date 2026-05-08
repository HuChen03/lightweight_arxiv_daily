import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from pathlib import Path

# 获取项目根目录
BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"

# 加载 .env 文件中的环境变量（如果存在）
# 系统环境变量会优先于 .env 文件中的配置
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)

# 邮件配置（从环境变量读取）
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "XXX")
EMAIL_TO = os.getenv("EMAIL_TO", "")


def send_email_notification(papers, days=3, translate=False):
    """发送论文通知邮件"""
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        print("⚠️  邮件配置缺失，请设置环境变量：EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO")
        return False

    # 构建 HTML 邮件内容
    from datetime import datetime, timedelta, timezone

    # Determine if we had to extend beyond the requested days to get enough papers
    original_cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    papers_beyond_requested_days = []

    for p in papers:
        published = datetime.strptime(p['published'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if published < original_cutoff:
            papers_beyond_requested_days.append(p)

    has_extended_papers = len(papers_beyond_requested_days) > 0

    current_date = datetime.now().strftime("%y.%m.%d")

    msg = MIMEMultipart()
    if has_extended_papers:
        if translate:
            msg['Subject'] = f"Arxiv Hep-ex Daily Paper Digest {current_date} [{len(papers)} papers, extended from {days} day(s), 中英文对照]"
        else:
            msg['Subject'] = f"Arxiv Hep-ex Daily Paper Digest {current_date} [{len(papers)} papers, extended from {days} day(s)]"
    else:
        if translate:
            msg['Subject'] = f"Arxiv Hep-ex Daily Paper Digest {current_date} [{len(papers)} papers, 中英文对照]"
        else:
            msg['Subject'] = f"Arxiv Hep-ex Daily Paper Digest {current_date} [{len(papers)} papers]"

    if translate:
        html = """
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .header {{ background-color: #f4f4f4; padding: 20px; border-radius: 5px; }}
                .paper {{ margin: 20px 0; padding: 15px; border-left: 4px solid #007bff; background-color: #fafafa; }}
                .title {{ font-size: 16px; font-weight: bold; color: #333; }}
                .original-title {{ font-size: 14px; font-style: italic; color: #666; }}
                .meta {{ color: #666; font-size: 14px; margin: 5px 0; }}
                .abstract {{ color: #444; font-size: 14px; margin: 10px 0; }}
                .original-abstract {{ color: #666; font-size: 13px; margin: 8px 0; }}
                .link {{ color: #007bff; text-decoration: none; }}
                .extension-note {{ background-color: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>📚 最新 hep-ex 论文 [中英文对照]</h2>
                <p>{count} 篇论文 - Arxiv Hep-ex Daily Paper Digest {current_date}</p>
            </div>
            {extension_note}
            {papers_html}
        </body>
        </html>
        """
    else:
        html = """
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .header {{ background-color: #f4f4f4; padding: 20px; border-radius: 5px; }}
                .paper {{ margin: 20px 0; padding: 15px; border-left: 4px solid #007bff; background-color: #fafafa; }}
                .title {{ font-size: 16px; font-weight: bold; color: #333; }}
                .meta {{ color: #666; font-size: 14px; margin: 5px 0; }}
                .abstract {{ color: #444; font-size: 14px; margin: 10px 0; }}
                .link {{ color: #007bff; text-decoration: none; }}
                .extension-note {{ background-color: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>📚 Arxiv Hep-ex Daily Paper Digest {current_date}</h2>
                <p>{count} papers</p>
            </div>
            {extension_note}
            {papers_html}
        </body>
        </html>
        """

    # Generate extension note if needed
    if has_extended_papers:
        extension_note = f'<div class="extension-note"><strong>ℹ️ Note:</strong> The following papers are from over {days} day(s) ago (time window extended to include at least 10 papers).</div>'
    else:
        extension_note = ''

    papers_html = ""
    for i, p in enumerate(papers, 1):
        pub_date = p['published'].replace("T", " ").replace("Z", "")

        # Format authors - show only first few and indicate if there are more
        author_list = p['authors']
        if len(author_list) > 5:
            authors_display = ', '.join(author_list[:5]) + f', ... and {len(author_list)-5} more authors'
        else:
            authors_display = ', '.join(author_list)

        if translate and 'translated_summary' in p:
            # Include both translated and original content
            papers_html += f"""
            <div class="paper">
                <div class="title">[{i}] {p['translated_title']}</div>
                <div class="original-title">Original Title: {p['title']}</div>
                <div class="meta">📅 {pub_date}</div>
                <div class="meta">👤 {authors_display}</div>
                <div class="abstract">📝 Abstract (中文): {p['translated_summary']}</div>
                <div class="original-abstract">📝 Abstract (English): {p['summary']}</div>
                <a class="link" href="{p['link']}">🔗 View Paper</a>
            </div>
            """
        else:
            papers_html += f"""
            <div class="paper">
                <div class="title">[{i}] {p['title']}</div>
                <div class="meta">📅 {pub_date}</div>
                <div class="meta">👤 {authors_display}</div>
                <div class="abstract">📝 {p['summary']}</div>
                <a class="link" href="{p['link']}">🔗 View Paper</a>
            </div>
            """

    from datetime import datetime
    current_date = datetime.now().strftime("%y.%m.%d")
    html_content = html.format(count=len(papers), days=days, papers_html=papers_html, current_date=current_date, extension_note=extension_note)

    msg = MIMEMultipart()
    if translate:
        msg['Subject'] = f"Arxiv Hep-ex Daily Paper Digest {current_date} [{len(papers)} papers, 中英文对照]"
    else:
        msg['Subject'] = f"Arxiv Hep-ex Daily Paper Digest {current_date} [{len(papers)} papers]"

    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO

    msg.attach(MIMEText(html_content, 'html'))

    try:
        print(f"正在连接 {SMTP_SERVER}:{SMTP_PORT}...")

        # 根据端口选择 SSL 或 STARTTLS
        if SMTP_PORT == 465 or SMTP_USE_SSL:
            # SSL 连接（如 163 邮箱 465 端口）
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
            print(f"使用 SSL 连接...")
        else:
            # STARTTLS 连接（如 Gmail 587 端口）
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            print(f"使用 STARTTLS 连接...")

        server.set_debuglevel(0)  # 关闭调试模式
        print(f"正在登录 {EMAIL_FROM}...")
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        print(f"正在发送邮件到 {EMAIL_TO}...")
        server.send_message(msg)
        server.quit()
        print(f"✅ 邮件已发送至 {EMAIL_TO}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ SMTP 认证失败：{e}")
        print("   请检查 EMAIL_FROM 和 EMAIL_PASSWORD 是否正确")
        print("   Gmail/163 用户需要使用'授权码/应用专用密码'，不是登录密码")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"❌ SMTP 连接失败：{e}")
        print(f"   请检查 SMTP_SERVER ({SMTP_SERVER}) 和 SMTP_PORT ({SMTP_PORT}) 是否正确")
        return False
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")
        return False
