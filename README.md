# Lightweight arXiv Daily

每天自动获取指定 arXiv 领域的新文章，调用 OpenAI 兼容 LLM 分析关键词，再用关键词检索最近一年高引用相关论文，并通过控制台或邮件输出研究 digest。

## 功能

- 获取一个或多个 arXiv category 下的新论文，例如 `hep-ex`、`cs.AI,cs.LG`
- 调用 LLM 为每篇新论文生成关键词、中文摘要和研究关注点
- 用 LLM 生成的关键词检索最近一年高引用相关论文；优先使用 OpenAlex citation 数据，Semantic Scholar 作为备用，最后降级为 arXiv 关键词检索
- 支持 HTML 邮件通知
- 邮件末尾展示本次 LLM total tokens 和人民币估算费用
- 支持 GitHub Actions 每日自动运行
- 无 LLM key 时会降级为本地关键词抽取，方便测试流程

## 本地运行

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 创建 `.env` 并配置环境变量：

```bash
cp .env.example .env
```

如果只想先测试流程，可以不配置 `OPENAI_API_KEY`，程序会使用本地关键词降级逻辑。要启用 LLM，需要配置 `OPENAI_API_KEY`、`OPENAI_API_BASE` 和 `LLM_MODEL`。要发送邮件，需要配置 SMTP 和邮箱变量。

3. 运行：

```bash
# 抓取 hep-ex 最近 24 小时论文，最多 10 篇，LLM 分析关键词，并检索相关论文
python main.py --category hep-ex --days 1 --max-results 10

# 多个领域
python main.py --category "cs.AI,cs.LG,cs.CL" --days 1

# 发送邮件
python main.py --category hep-ex --days 1 --email

# 跳过 LLM，用本地关键词抽取测试完整流程
python main.py --category hep-ex --days 1 --max-results 3 --related-per-paper 2 --skip-llm
```

## 主要参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--category` | arXiv category，多个用逗号分隔 | `hep-ex` |
| `--days` | 搜索过去几天的新论文 | `3` |
| `--max-results` | 最多处理多少篇源论文 | `10` |
| `--related-per-paper` | 每篇源论文保留多少篇相关论文 | `5` |
| `--email` | 发送邮件通知 | false |
| `--skip-llm` | 跳过 LLM，使用本地关键词降级逻辑 | false |

## 环境变量

项目启动时会自动读取根目录的 `.env`。建议从模板开始：

```bash
cp .env.example .env
```

### arXiv 抓取

```env
ARXIV_CATEGORY=hep-ex
ARXIV_DAYS=1
ARXIV_MAX_RESULTS=10
INCLUDE_CROSS_LIST=false
```

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ARXIV_CATEGORY` | arXiv category，多个可用逗号分隔，例如 `cs.AI,cs.LG` | `hep-ex` |
| `ARXIV_DAYS` | 抓取过去几天的新论文；日常任务建议设为 `1` | `3` |
| `ARXIV_MAX_RESULTS` | 每次最多处理多少篇源论文 | `10` |
| `INCLUDE_CROSS_LIST` | 是否包含 cross-listed 论文 | `false` |

注意：程序不会再因为论文不足而扩展时间窗口。过去 24 小时只有 3 篇就只处理 3 篇。

### Related Paper 检索

```env
RELATED_PER_PAPER=5
RELATED_SEARCH_LIMIT=20
MAX_QUERY_TERMS=5
```

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `RELATED_PER_PAPER` | 每篇源论文最多保留多少篇相关论文 | `5` |
| `RELATED_SEARCH_LIMIT` | 每次检索从 OpenAlex/Semantic Scholar 拉取多少候选论文 | `20` |
| `MAX_QUERY_TERMS` | 每篇论文最多使用多少个内部检索短语 | `5` |

相关论文检索顺序是：OpenAlex 最近一年高引用论文 -> Semantic Scholar 最近一年高引用论文 -> arXiv 关键词检索降级。OpenAlex 和 Semantic Scholar 不需要配置 API key。

### LLM 和费用

```env
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
USD_CNY_RATE=7.2

# 可选：使用非 OpenAI 官方模型或不同供应商时，手动覆盖价格（美元/百万 token）
LLM_INPUT_PRICE_USD_PER_1M=0.15
LLM_OUTPUT_PRICE_USD_PER_1M=0.60
```

LLM 输出固定为中文摘要和中文关注点；关键词固定为英文技术术语，便于检索。

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | OpenAI 或兼容服务的 API key；不配置时自动降级为本地关键词提取 | 空 |
| `OPENAI_API_BASE` | OpenAI 兼容 API base URL，也可用 `OPENAI_BASE_URL` | 空 |
| `LLM_MODEL` | Chat completion 模型名 | `gpt-4o-mini` |
| `USD_CNY_RATE` | 费用估算使用的美元兑人民币汇率 | `7.2` |
| `LLM_INPUT_PRICE_USD_PER_1M` | 自定义输入 token 价格，美元/百万 token | 按内置模型表 |
| `LLM_OUTPUT_PRICE_USD_PER_1M` | 自定义输出 token 价格，美元/百万 token | 按内置模型表 |

### 邮件通知

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_SSL=false
EMAIL_FROM=your_email@example.com
EMAIL_PASSWORD=your_email_password_or_app_password
EMAIL_TO=recipient@example.com
TRANSLATE_TITLES=false
```

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SMTP_SERVER` | SMTP 服务器地址 | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP 端口；`465` 会使用 SSL，其他端口默认 STARTTLS | `587` |
| `SMTP_USE_SSL` | 是否强制使用 SSL 连接 | `false` |
| `EMAIL_FROM` | 发件人邮箱 | 空 |
| `EMAIL_PASSWORD` | 邮箱密码或应用专用密码/授权码 | 空 |
| `EMAIL_TO` | 收件人邮箱，多个收件人请用逗号分隔 | 空 |
| `TRANSLATE_TITLES` | 是否把源论文标题翻译成中文显示在邮件中 | `false` |

常见邮箱配置示例：

```env
# Gmail
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_SSL=false

# 163 邮箱
SMTP_SERVER=smtp.163.com
SMTP_PORT=465
SMTP_USE_SSL=true
```

## GitHub Actions 部署

在 GitHub 仓库的 Settings -> Secrets and variables -> Actions 中添加：

必填 Secrets：

| Secret Name | 说明 |
|-------------|------|
| `EMAIL_FROM` | 发件人邮箱 |
| `EMAIL_PASSWORD` | 邮箱密码或应用专用密码/授权码 |
| `EMAIL_TO` | 收件人邮箱 |

推荐 Secrets：

| Secret Name | 说明 |
|-------------|------|
| `SMTP_SERVER` | SMTP 服务器地址；不配置时本地默认是 `smtp.gmail.com`，但 Actions 建议显式配置 |
| `SMTP_PORT` | SMTP 端口；不配置时本地默认是 `587`，但 Actions 建议显式配置 |
| `OPENAI_API_KEY` | LLM API key；不配置时会使用本地关键词降级逻辑 |
| `OPENAI_API_BASE` | OpenAI 兼容 API base URL |

可选 Variables：

| Variable Name | 说明 | 示例 |
|---------------|------|------|
| `ARXIV_CATEGORY` | 默认 arXiv category | `hep-ex` |
| `ARXIV_MAX_RESULTS` | 默认源论文数量 | `10` |
| `RELATED_PER_PAPER` | 默认相关论文数量 | `5` |
| `SMTP_USE_SSL` | 是否强制 SMTP SSL | `false` |
| `INCLUDE_CROSS_LIST` | 是否包含 cross-listed 论文 | `false` |
| `RELATED_SEARCH_LIMIT` | related paper 候选数量 | `20` |
| `MAX_QUERY_TERMS` | 内部检索短语数量 | `5` |
| `TRANSLATE_TITLES` | 是否翻译源论文标题 | `false` |
| `LLM_MODEL` | 默认模型 | `gpt-4o-mini` |
| `USD_CNY_RATE` | 美元兑人民币估算汇率 | `7.2` |

workflow 默认每天 UTC 0:00 运行，也可以在 Actions 页面手动触发并指定 category、days、max_results 和 related_per_paper。

## 项目结构

```text
.
├── main.py                 # CLI 参数解析和主流程编排
├── config.py               # .env 加载、默认值和通用配置解析
├── arxiv_client.py         # arXiv 查询、Atom 解析、最近论文筛选
├── openalex_client.py      # OpenAlex 高引用相关论文检索
├── semantic_scholar_client.py # Semantic Scholar 高引用相关论文检索
├── llm_analyzer.py         # LLM 调用、JSON 解析、本地关键词降级
├── digest.py               # 源论文分析和相关论文检索编排
├── pricing.py              # token usage 汇总和人民币费用估算
├── report.py               # 控制台报告输出
├── email_renderer.py       # HTML 邮件内容渲染
├── email_notifier.py       # SMTP 发送
└── translation.py          # 可选标题/摘要翻译
```

## 参考项目

本项目的改造参考了 [TideDra/zotero-arxiv-daily](https://github.com/TideDra/zotero-arxiv-daily) 的几个思路：

- 用配置指定 arXiv category
- 用 OpenAI 兼容 API 生成论文摘要信息
- 将论文信息整理为 HTML 邮件
- 在自动化 workflow 中通过 GitHub Secrets 注入敏感配置

这里没有引入 Zotero 语料库、embedding reranker 或全文 PDF 抽取，保持当前项目轻量。
