import html
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def format_authors(authors: list[str]) -> str:
    if not authors:
        return "Unknown authors"
    if len(authors) > 5:
        return ", ".join(authors[:5]) + f", ... and {len(authors) - 5} more authors"
    return ", ".join(authors)


def is_digest_item(item: dict[str, Any]) -> bool:
    return "source_paper" in item and "llm_analysis" in item


def has_extended_papers(items: list[dict[str, Any]], days: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    papers = []
    for item in items:
        papers.append(item["source_paper"] if is_digest_item(item) else item)
    for paper in papers:
        published = datetime.strptime(paper["published"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if published < cutoff:
            return True
    return False


def render_related_papers(related_papers: list[dict[str, Any]]) -> str:
    if not related_papers:
        return '<div class="empty-related">No related papers found.</div>'

    parts = []
    for paper in related_papers:
        matched = ", ".join(paper.get("matched_keywords", []))
        parts.append(
            f"""
            <li>
                <a href="{esc(paper.get('link'))}">{esc(paper.get('title'))}</a>
                <span class="related-date">{esc(str(paper.get('published', ''))[:10])}</span>
                <div class="related-meta">Matched: {esc(matched or 'query terms')}</div>
            </li>
            """
        )
    return '<ul class="related-list">' + "\n".join(parts) + "</ul>"


def render_digest_item(index: int, item: dict[str, Any]) -> str:
    paper = item["source_paper"]
    analysis = item.get("llm_analysis", {})
    related_papers = item.get("related_papers", [])
    pub_date = paper["published"].replace("T", " ").replace("Z", "")
    keywords = ", ".join(analysis.get("keywords", []))
    query_terms = ", ".join(analysis.get("query_terms", []))

    pdf_link = paper.get("pdf_link") or paper.get("link")
    translated_title = paper.get("translated_title")
    translated_summary = paper.get("translated_summary")

    translated_block = ""
    if translated_title or translated_summary:
        translated_block = f"""
        <div class="translated">
            <div><strong>中文标题:</strong> {esc(translated_title or '')}</div>
            <div><strong>中文摘要:</strong> {esc(translated_summary or '')}</div>
        </div>
        """

    return f"""
    <section class="paper">
        <h3>[{index}] {esc(paper.get('title'))}</h3>
        <div class="meta">
            {esc(pub_date)} · {esc(paper.get('primary_category'))} · {esc(format_authors(paper.get('authors', [])))}
        </div>
        {translated_block}
        <p class="summary"><strong>LLM Summary:</strong> {esc(analysis.get('topic_summary', ''))}</p>
        <p class="focus"><strong>Focus:</strong> {esc(analysis.get('technical_focus', ''))}</p>
        <p class="keywords"><strong>Keywords:</strong> {esc(keywords)}</p>
        <p class="keywords"><strong>arXiv query terms:</strong> {esc(query_terms)}</p>
        <div class="links">
            <a href="{esc(paper.get('link'))}">arXiv</a>
            <a href="{esc(pdf_link)}">PDF</a>
        </div>
        <div class="abstract"><strong>Abstract:</strong> {esc(paper.get('summary'))}</div>
        <h4>Related papers</h4>
        {render_related_papers(related_papers)}
    </section>
    """


def render_legacy_paper(index: int, paper: dict[str, Any], translate: bool = False) -> str:
    pub_date = paper["published"].replace("T", " ").replace("Z", "")
    title = paper.get("translated_title") if translate and paper.get("translated_title") else paper.get("title")
    summary = paper.get("translated_summary") if translate and paper.get("translated_summary") else paper.get("summary")
    original_block = ""
    if translate and paper.get("translated_summary"):
        original_block = f"""
        <div class="abstract original"><strong>Original Abstract:</strong> {esc(paper.get('summary'))}</div>
        """
    return f"""
    <section class="paper">
        <h3>[{index}] {esc(title)}</h3>
        <div class="meta">{esc(pub_date)} · {esc(format_authors(paper.get('authors', [])))}</div>
        <div class="abstract"><strong>Abstract:</strong> {esc(summary)}</div>
        {original_block}
        <div class="links"><a href="{esc(paper.get('link'))}">View Paper</a></div>
    </section>
    """


def render_usage_summary(usage_summary: dict[str, Any] | None) -> str:
    if not usage_summary:
        return ""
    total_tokens = int(usage_summary.get("total_tokens", 0) or 0)
    model = usage_summary.get("model") or "unknown"
    if usage_summary.get("cost_known"):
        cost_text = f"¥{float(usage_summary.get('cost_cny', 0.0)):.4f}"
    else:
        cost_text = "unknown model price"
    rate = usage_summary.get("usd_cny_rate", "")
    rate_text = f" (USD/CNY={esc(rate)})" if rate != "" else ""
    return f"""
    <section class="usage-summary">
        <h3>本次 LLM 消耗</h3>
        <div>Model: {esc(model)}</div>
        <div>Total tokens: {total_tokens:,}</div>
        <div>Estimated cost: {esc(cost_text)}{rate_text}</div>
    </section>
    """


def render_email_content(
    items: list[dict[str, Any]],
    days: int,
    translate: bool,
    category_label: str,
    time_window_extended: bool | None,
    usage_summary: dict[str, Any] | None = None,
) -> tuple[str, str]:
    current_date = datetime.now().strftime("%Y.%m.%d")
    extended = time_window_extended if time_window_extended is not None else has_extended_papers(items, days)
    digest_mode = bool(items and is_digest_item(items[0]))

    subject_bits = [f"Arxiv Daily Research Digest {current_date}", f"{len(items)} papers"]
    if category_label:
        subject_bits.append(category_label)
    if extended:
        subject_bits.append(f"extended from {days} day(s)")
    if translate:
        subject_bits.append("中英文对照")
    subject = " [" + ", ".join(subject_bits[1:]) + "]"
    subject = subject_bits[0] + subject

    if not items:
        content = '<section class="paper"><h3>No Papers Today</h3><p>No new arXiv papers were found.</p></section>'
    elif digest_mode:
        content = "\n".join(render_digest_item(i, item) for i, item in enumerate(items, 1))
    else:
        content = "\n".join(render_legacy_paper(i, item, translate=translate) for i, item in enumerate(items, 1))

    extension_note = ""
    if extended:
        extension_note = f"""
        <div class="extension-note">
            The time window was extended beyond {days} day(s) to include enough papers.
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #222; }}
            .header {{ background: #f4f4f4; padding: 20px; border-radius: 6px; }}
            .header h2 {{ margin: 0 0 8px 0; }}
            .paper {{ margin: 28px 0; padding: 16px; border-left: 4px solid #2563eb; background: #fafafa; }}
            .paper h3 {{ margin: 0 0 8px 0; font-size: 18px; }}
            .paper h4 {{ margin: 16px 0 6px 0; }}
            .meta, .related-meta, .related-date {{ color: #666; font-size: 13px; }}
            .summary, .focus, .keywords, .abstract {{ font-size: 14px; }}
            .abstract {{ margin-top: 12px; color: #444; }}
            .original {{ color: #666; }}
            .translated {{ background: #eef6ff; padding: 10px; margin: 10px 0; border-radius: 4px; }}
            .links a {{ display: inline-block; margin-right: 10px; color: #2563eb; }}
            .related-list {{ padding-left: 20px; }}
            .related-list li {{ margin-bottom: 10px; }}
            .empty-related {{ color: #777; font-size: 14px; }}
            .extension-note {{ background: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; margin: 12px 0; }}
            .usage-summary {{ margin: 32px 0 0 0; padding: 14px; background: #f6f7f9; border: 1px solid #ddd; border-radius: 6px; }}
            .usage-summary h3 {{ margin: 0 0 8px 0; font-size: 16px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>Arxiv Daily Research Digest {esc(current_date)}</h2>
            <div>{esc(category_label or 'arXiv')} · {len(items)} papers</div>
        </div>
        {extension_note}
        {content}
        {render_usage_summary(usage_summary)}
    </body>
    </html>
    """
    return subject, html_content


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
