# Lightweight arXiv Daily

每天自动获取指定 arXiv 领域的新文章，调用 OpenAI 兼容 LLM 分析关键词，再用关键词在 arXiv 上检索相关论文，并通过控制台或邮件输出研究 digest。

## 功能

- 获取一个或多个 arXiv category 下的新论文，例如 `hep-ex`、`cs.AI,cs.LG`
- 调用 LLM 为每篇新论文生成关键词、arXiv 查询词、中文摘要和研究关注点
- 用 LLM 生成的查询词二次检索 arXiv 相关论文
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
touch .env
```

至少需要配置邮件变量；如果要启用 LLM，需要配置：

```env
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
USD_CNY_RATE=7.2
```

`OPENAI_API_BASE` 可换成任意 OpenAI 兼容接口。

3. 运行：

```bash
# 抓取 hep-ex 最近 1 天论文，LLM 分析关键词，并检索相关论文
python main.py --category hep-ex --days 1 --max-results 30

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
| `--max-results` | 最多处理多少篇源论文 | `100` |
| `--min-results` | 最近窗口论文太少时扩展到的最小数量 | `5` |
| `--related-per-paper` | 每篇源论文保留多少篇相关论文 | `5` |
| `--related-search-limit` | 每次相关检索抓取多少候选论文 | `20` |
| `--max-query-terms` | 每篇论文最多使用多少个 LLM 查询词 | `5` |
| `--include-cross-list` | 是否包含 cross-listed 论文 | false |
| `--email` | 发送邮件通知 | false |
| `--translate` | 对源论文标题和摘要做中译 | false |
| `--skip-llm` | 跳过 LLM，使用本地关键词降级逻辑 | false |
| `--llm-model` | OpenAI 兼容模型名 | `gpt-4o-mini` |
| `--llm-base-url` | OpenAI 兼容 API base URL | `OPENAI_API_BASE` |

## 环境变量

```env
SMTP_SERVER=smtp.163.com
SMTP_PORT=465
EMAIL_FROM=your_email@163.com
EMAIL_PASSWORD=your_auth_code
EMAIL_TO=recipient@example.com

ARXIV_CATEGORY=hep-ex
ARXIV_DAYS=1
ARXIV_MAX_RESULTS=30
ARXIV_MIN_RESULTS=5
INCLUDE_CROSS_LIST=false

RELATED_PER_PAPER=5
RELATED_SEARCH_LIMIT=20
MAX_QUERY_TERMS=5

OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
USD_CNY_RATE=7.2

# 可选：使用非 OpenAI 官方模型或不同供应商时，手动覆盖价格（美元/百万 token）
LLM_INPUT_PRICE_USD_PER_1M=0.15
LLM_OUTPUT_PRICE_USD_PER_1M=0.60
```

LLM 输出固定为中文摘要和中文关注点；关键词和 arXiv 查询词固定为英文技术术语，便于检索。

## GitHub Actions 部署

在 GitHub 仓库的 Settings -> Secrets and variables -> Actions 中添加：

| Secret Name | 说明 |
|-------------|------|
| `SMTP_SERVER` | SMTP 服务器地址 |
| `SMTP_PORT` | SMTP 端口 |
| `EMAIL_FROM` | 发件人邮箱 |
| `EMAIL_PASSWORD` | 邮箱授权码 |
| `EMAIL_TO` | 收件人邮箱 |
| `OPENAI_API_KEY` | LLM API key |
| `OPENAI_API_BASE` | 可选，OpenAI 兼容 API base URL |

可选 Variables：

| Variable Name | 说明 | 示例 |
|---------------|------|------|
| `ARXIV_CATEGORY` | 默认 arXiv category | `hep-ex` |
| `ARXIV_MAX_RESULTS` | 默认源论文数量 | `30` |
| `RELATED_PER_PAPER` | 默认相关论文数量 | `5` |
| `LLM_MODEL` | 默认模型 | `gpt-4o-mini` |
| `USD_CNY_RATE` | 美元兑人民币估算汇率 | `7.2` |

workflow 默认每天 UTC 0:00 运行，也可以在 Actions 页面手动触发并指定 category、days、max_results 和 related_per_paper。

## 参考项目

本项目的改造参考了 [TideDra/zotero-arxiv-daily](https://github.com/TideDra/zotero-arxiv-daily) 的几个思路：

- 用配置指定 arXiv category
- 用 OpenAI 兼容 API 生成论文摘要信息
- 将论文信息整理为 HTML 邮件
- 在自动化 workflow 中通过 GitHub Secrets 注入敏感配置

这里没有引入 Zotero 语料库、embedding reranker 或全文 PDF 抽取，保持当前项目轻量。
