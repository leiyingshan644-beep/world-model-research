# 世界模型论文调研流水线

从顶会检索 → 相关性筛选 → 批量下载 → AI 总结 → 本地浏览 → **研究 Idea 生成**，六步完成世界模型方向论文调研。

**覆盖会议：** NeurIPS、ICML、ICLR、CVPR、CoRL（2021—2025）

---

## 项目结构

```
world-model-research/
├── config.py          # 所有配置：API Key、路径、关键词、评分权重
├── collect.py         # 阶段1：检索论文元数据
├── filter.py          # 阶段2：关键词打分 + 手动标记相关度
├── download.py        # 阶段3：批量下载 PDF
├── summarize.py       # 阶段4：AI 生成结构化总结
├── browse.py          # 阶段5：本地 Web 浏览界面（port 5000）
├── requirements.txt
├── utils/
│   ├── db.py          # SQLite 读写封装
│   └── pdf_parser.py  # PDF 文字提取
├── tests/             # 单元测试（59 个）
├── papers.db          # 数据库（论文元数据 + AI 总结）
├── pdfs/              # PDF 文件（按会议/年份存放）
└── idea_gen/          # 研究 Idea 生成子模块（见下方）
    ├── extract_gaps.py      # Step 1：提取每篇论文的研究空白
    ├── generate_ideas.py    # Step 2：聚合生成 + 精炼 Idea
    ├── translate_ideas.py   # 无 API 时用免费翻译补充中文
    ├── ideas_web.py         # Idea 浏览界面（port 5001）
    ├── gaps/                # 每篇论文的 gap JSON（中间产物）
    ├── ideas_draft/         # 草稿 Idea Markdown
    └── ideas_final/         # 精炼后最终 Idea Markdown（双语）
```

---

## 快速开始

### 1. 配置

打开 `config.py`，填写 API Key（支持阿里百炼 / DeepSeek / 任意 OpenAI 兼容接口）：

```python
LLM_API_KEY  = "sk-xxxxxx"
LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL    = "qwen-plus"
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 完整调研流程

```bash
# 检索全部会议元数据
python collect.py

# 自动打分 + 标记相关度
python filter.py --auto

# 下载高相关论文 PDF
python download.py --high

# AI 生成总结（需要 API Key）
python summarize.py --label high

# 启动论文浏览界面
python browse.py              # → http://localhost:5000

# 生成研究 Idea（需要 API Key）
python idea_gen/extract_gaps.py
python idea_gen/generate_ideas.py --step all
python idea_gen/ideas_web.py  # → http://localhost:5001
```

---

## 各模块说明

### `collect.py` — 检索元数据

```bash
python collect.py                    # 检索所有会议（2021-2025）
python collect.py --venue neurips    # 只检索 NeurIPS
python collect.py --year 2024        # 只检索 2024 年
python collect.py --url https://arxiv.org/abs/2410.13571  # 添加单篇 arXiv 论文
```

数据来源：OpenAlex API、CVF Open Access、arXiv、FIB-Lab 汇总库。重复运行安全（`INSERT OR IGNORE`，已有数据不会被覆盖）。

### `filter.py` — 相关性打分与标记

```bash
python filter.py --auto      # 自动打分并按阈值标记 high/mid/low
python filter.py --review    # 只对未标记论文交互标记
```

评分基于关键词权重，针对视觉生成类世界模型调优：`world model`、`cosmos`、`hunyuan`、`video diffusion` 等权重较高；`dreamer`、`td-mpc` 等 RL 类权重较低。

### `download.py` — 下载 PDF

```bash
python download.py --high                # 只下载 high 论文
python download.py --id arxiv:2410.13571 # 下载单篇
```

### `summarize.py` — AI 生成总结

```bash
python summarize.py --label high         # 批量总结 high 论文
python summarize.py --id arxiv:2410.13571
```

输出字段：核心问题 / 核心创新 / 方法 / 实验结果 / 不足与空白，存入 SQLite。

### `browse.py` — 论文浏览界面（port 5000）

```bash
python browse.py
```

功能：
- 按会议、年份、标记、状态、标签筛选
- 关键词搜索 / 已浏览论文自动标灰（DB 持久化）/ 序号显示
- 自定义标签系统（支持全局删除 + 30 秒撤销）
- 每篇论文手动评分加成（`±` 按钮）
- 查看 AI 总结 + 编辑"我的思考"
- 点击"打开 PDF"用系统阅读器直接查看

---

## Idea 生成子模块（`idea_gen/`）

基于论文库自动生成研究 Idea，每个 Idea 是一份小型调研报告，含中英双语。

### 流程

```
extract_gaps.py     →    generate_ideas.py    →    ideas_web.py
（提取200篇论文的         （三阶段：批次聚合          （浏览最终 Idea，
  研究空白 gap）           → 生成草稿 → 精炼）         port 5001）
```

**Step 1 — 提取研究空白：**

```bash
python idea_gen/extract_gaps.py           # 处理全部（可重跑，已提取跳过）
python idea_gen/extract_gaps.py --dry-run # 只看选纸统计，不调 API
```

选纸策略：Top-100（按相关度）+ 分层抽样 100 篇（mid × 80 + low × 20）。

**Step 2 — 生成 Idea：**

```bash
python idea_gen/generate_ideas.py --step all  # 一次跑完 2a+2b+2c
python idea_gen/generate_ideas.py --step 2a   # 批次主题聚合
python idea_gen/generate_ideas.py --step 2b   # 生成草稿 Idea（两轮×15篇）
python idea_gen/generate_ideas.py --step 2c   # 精炼：合并相似 / 拆解宽泛
```

**（无 API 时）补充中文翻译：**

```bash
python idea_gen/translate_ideas.py        # 用免费 Google 翻译补 _zh 字段
python idea_gen/translate_ideas.py --draft
```

**Step 3 — 浏览 Idea：**

```bash
python idea_gen/ideas_web.py   # → http://localhost:5001
```

功能：列表搜索、英文/中文/双语切换、参考文献链接回论文浏览器、进度控制页。

每个 Idea 报告包含：
- 当前问题（Current Problem）
- 创新点（Innovation）
- 解决方法（Proposed Method）
- 来源文献（链接至 `http://localhost:5000/paper/{id}`）
- 中文版（关键术语括注英文，如：世界模型(World Model)）

---

## 运行测试

```bash
python -m pytest tests/ -v
```

---

## 注意事项

- `config.py` 已加入 `.gitignore`，API Key 不会被提交
- `idea_gen/gaps/`、`ideas_draft/`、`ideas_final/` 已加入 `.gitignore`（为运行时产物）
- AI 生成内容可能存在幻觉，关键信息请回原文核对
- arXiv 下载有频率限制，`download.py` 已内置延迟，勿并发运行
