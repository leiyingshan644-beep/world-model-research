# 世界模型论文调研流水线 — 设计文档

**日期：** 2026-04-05  
**状态：** 已批准，待实现

---

## 1. 项目目标

构建一套本地运行的论文调研流水线，用于系统性收集、管理、阅读和总结世界模型（World Model）相关顶会论文，辅助确定新的研究方向。

**目标会议：** NeurIPS、ICML、ICLR、CVPR、CoRL  
**时间范围：** 2021—2025 年  
**AI 总结模型：** DeepSeek / Qwen（OpenAI 兼容接口）  
**运行环境：** Mac 本地，代码与数据全部存储在 HIKSEMI U 盘

---

## 2. 目录结构

```
/Volumes/HIKSEMI/world-model-research/
├── config.py              # 统一配置（API Key、路径、关键词）
├── collect.py             # 阶段1：检索论文元数据
├── filter.py              # 阶段2：相关性打分与手动标记
├── download.py            # 阶段3：批量下载 PDF
├── summarize.py           # 阶段4：AI 生成结构化总结
├── browse.py              # 阶段5：Flask 本地浏览界面
├── requirements.txt       # Python 依赖
├── README.md              # 项目说明与使用示例
├── utils/
│   ├── db.py              # SQLite 读写封装
│   └── pdf_parser.py      # PDF 文字提取工具
├── papers.db              # SQLite 数据库（元数据 + 总结）
├── pdfs/                  # PDF 文件，按会议/年份存放
│   ├── neurips/
│   │   ├── 2021/
│   │   └── 2025/
│   ├── icml/
│   ├── iclr/
│   ├── cvpr/
│   └── corl/
└── docs/
    └── specs/
        └── 2026-04-05-world-model-pipeline-design.md  # 本文件
```

---

## 3. 数据库 Schema

### `papers` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | arxiv_id 或 s2_id |
| `title` | TEXT | 论文标题 |
| `authors` | TEXT | 作者列表（JSON 字符串） |
| `year` | INT | 发表年份 |
| `venue` | TEXT | neurips / icml / iclr / cvpr / corl |
| `abstract` | TEXT | 摘要 |
| `arxiv_id` | TEXT | arXiv ID（可能为空） |
| `pdf_url` | TEXT | 原始下载链接 |
| `pdf_path` | TEXT | 本地 PDF 路径（下载后填充） |
| `relevance_score` | REAL | 自动打分 0.0—1.0 |
| `relevance_label` | TEXT | 手动标记：high / mid / low / skip |
| `status` | TEXT | collected / downloaded / summarized |

### `summaries` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `paper_id` | TEXT FK | → papers.id |
| `problem` | TEXT | 核心问题 |
| `innovation` | TEXT | 核心创新点 |
| `method` | TEXT | 方法概述 |
| `results` | TEXT | 实验结论 |
| `gaps` | TEXT | 不足与待解决问题 |
| `my_thoughts` | TEXT | 用户手动填写的思考（可在 Web UI 编辑） |
| `model_used` | TEXT | 生成总结所用模型名称 |
| `created_at` | TEXT | ISO 8601 时间戳 |

---

## 4. 模块设计

### 4.1 `collect.py` — 检索元数据

**数据源：**
1. Semantic Scholar API：关键词检索 + 会议过滤 + 年份过滤
2. 清华 FIB-Lab GitHub 仓库（`tsinghua-fib-lab/world-model`）README 解析，补充 arXiv 链接

**关键词组：**
```
world model, generative world model, world foundation model,
dreamer, PlaNet, TD-MPC, model-based RL,
video prediction world model, embodied world model
```

**行为：**
- 两路结果按 `arxiv_id` / `title` 去重后写入 `papers` 表
- 已存在的记录跳过（幂等）

**CLI：**
```bash
python collect.py                   # 全量检索所有会议
python collect.py --venue neurips   # 只检索指定会议
python collect.py --year 2024       # 只检索指定年份
```

---

### 4.2 `filter.py` — 相关性打分与标记

**自动打分：** 对 title + abstract 做关键词加权 TF 打分，写入 `relevance_score`（0.0—1.0）

**交互标记：** 按分数从高到低依次展示论文，用户输入 `h/m/l/s`（high/mid/low/skip）快速标记

**CLI：**
```bash
python filter.py           # 自动打分 + 交互标记
python filter.py --auto    # 只自动打分，不进入交互
python filter.py --review  # 只对未标记的论文进行交互
```

---

### 4.3 `download.py` — 下载 PDF

**策略：**
- 只下载 `relevance_label` 不为 `skip` 的论文
- 优先 arXiv 直链（`https://arxiv.org/pdf/{arxiv_id}`）；无 arXiv ID 则尝试 `pdf_url` 字段（来自 Semantic Scholar）；两者均无则跳过并在终端提示
- 存放路径：`pdfs/{venue}/{year}/{arxiv_id 或 s2_id}.pdf`
- 已存在文件跳过（断点续传）
- 下载完成后更新 `papers.pdf_path` 和 `papers.status = 'downloaded'`

**CLI：**
```bash
python download.py           # 下载全部非 skip 论文
python download.py --high    # 只下载 high 相关度论文
python download.py --limit 20  # 限制本次最多下载数量
```

---

### 4.4 `summarize.py` — AI 生成结构化总结

**流程：**
1. 用 `pdfplumber` 提取 PDF 文字，截断至模型 token 上限
2. 拼装 Prompt，要求模型按固定 JSON 格式输出（problem / innovation / method / results / gaps）
3. 解析 JSON，写入 `summaries` 表
4. 更新 `papers.status = 'summarized'`

**模型接口：** OpenAI 兼容接口，`base_url` 和 `api_key` 在 `config.py` 中配置

**CLI：**
```bash
python summarize.py --label high             # 只总结 high 论文
python summarize.py --id arxiv:2301.04589    # 总结单篇
python summarize.py --label high,mid         # 总结多个级别
```

---

### 4.5 `browse.py` — Flask 本地浏览界面

**地址：** `http://localhost:5000`

**功能：**
- **列表页**：展示所有论文，支持按会议/年份/相关度筛选，支持标题+摘要关键词搜索，显示 status 徽章
- **详情页**：论文元数据 + AI 生成总结各字段 + `my_thoughts` 可在线编辑保存
- **打开 PDF**：点击按钮调用系统命令打开本地 PDF 文件

---

## 5. `config.py` 关键配置项

```python
# 路径
BASE_DIR = "/Volumes/HIKSEMI/world-model-research"
DB_PATH  = f"{BASE_DIR}/papers.db"
PDF_DIR  = f"{BASE_DIR}/pdfs"

# AI 接口（OpenAI 兼容）
LLM_BASE_URL = "https://api.deepseek.com/v1"  # 或 Qwen 地址
LLM_API_KEY  = "your-api-key-here"
LLM_MODEL    = "deepseek-chat"

# 检索配置
TARGET_VENUES = ["neurips", "icml", "iclr", "cvpr", "corl"]
YEAR_RANGE    = (2021, 2025)
KEYWORDS      = [
    "world model", "generative world model", "world foundation model",
    "dreamer", "PlaNet", "TD-MPC", "model-based RL",
    "video prediction world model", "embodied world model"
]

# Semantic Scholar API（可选，有 key 则速率更高）
S2_API_KEY = ""
```

---

## 6. 典型使用流程

```bash
# 第一次使用，全量检索并过滤
cd /Volumes/HIKSEMI/world-model-research
python collect.py            # 检索元数据，写入 papers.db
python filter.py             # 自动打分 + 手动标记相关度

# 下载高相关论文并生成总结
python download.py --high    # 只下载 high 论文
python summarize.py --label high  # AI 生成总结

# 启动浏览界面阅读
python browse.py             # 打开 http://localhost:5000

# 后续：中相关论文补充处理
python download.py           # 下载剩余 mid/low 论文
python summarize.py --label mid
```

---

## 7. 依赖

```
requests
semanticscholar
arxiv
pandas
pdfplumber
flask
openai          # 用于 OpenAI 兼容接口
beautifulsoup4
lxml
```
