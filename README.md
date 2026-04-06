# 世界模型论文调研流水线

从顶会检索 → 相关性筛选 → 批量下载 → AI 总结 → 本地浏览，五步完成世界模型方向论文调研。

**覆盖会议：** NeurIPS、ICML、ICLR、CVPR、CoRL（2021—2025）

---

## 项目结构

```
world-model-research/
├── config.py          # 所有配置：API Key、路径、关键词
├── collect.py         # 阶段1：检索论文元数据
├── filter.py          # 阶段2：关键词打分 + 手动标记相关度
├── download.py        # 阶段3：批量下载 PDF
├── summarize.py       # 阶段4：AI 生成结构化总结
├── browse.py          # 阶段5：本地 Web 浏览界面
├── requirements.txt
├── utils/
│   ├── db.py          # SQLite 读写封装（papers + summaries 表）
│   └── pdf_parser.py  # PDF 文字提取
├── tests/             # 单元测试（31 个，覆盖全部模块）
├── papers.db          # 数据库（论文元数据 + AI 总结）
└── pdfs/              # PDF 文件（按会议/年份存放）
    ├── neurips/2023/
    ├── icml/2024/
    └── ...
```

---

## 快速开始

### 1. 配置

打开 `config.py`，填写你的 DeepSeek 或 Qwen API Key：

```python
LLM_API_KEY  = "sk-xxxxxx"                      # 填入你的 API Key
LLM_BASE_URL = "https://api.deepseek.com/v1"    # 或 Qwen 的地址
LLM_MODEL    = "deepseek-chat"
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 完整调研流程

```bash
# 检索全部会议元数据（约 5-15 分钟）
python collect.py

# 自动打分 + 手动标记相关度（按 h/m/l/s + 回车）
python filter.py

# 下载高相关论文 PDF
python download.py --high

# AI 生成总结（需要 API Key）
python summarize.py --label high

# 启动浏览界面
python browse.py
# 浏览器访问 http://localhost:5000
```

---

## 各模块说明

### `collect.py` — 检索元数据

```bash
python collect.py                    # 检索所有会议（2021-2025）
python collect.py --venue neurips    # 只检索 NeurIPS
python collect.py --year 2024        # 只检索 2024 年
```

数据来源：
- **Semantic Scholar API**（主要来源，支持按会议/年份过滤）
- **清华 FIB-Lab 汇总库**（`tsinghua-fib-lab/world-model`，补充 arXiv 论文）

### `filter.py` — 相关性打分与标记

```bash
python filter.py             # 自动打分 + 逐篇交互标记
python filter.py --auto      # 只自动打分，不弹出交互
python filter.py --review    # 只对未标记论文进行标记
```

交互按键：`h` = high | `m` = mid | `l` = low | `s` = skip | `q` = 退出

### `download.py` — 下载 PDF

```bash
python download.py              # 下载所有非 skip 论文
python download.py --high       # 只下载 high 相关度论文
python download.py --limit 20   # 本次最多下载 20 篇
```

PDF 存放路径：`pdfs/{venue}/{year}/{arxiv_id}.pdf`，已存在文件自动跳过。

### `summarize.py` — AI 生成总结

```bash
python summarize.py --label high              # 总结 high 论文
python summarize.py --label high,mid          # 总结 high 和 mid 论文
python summarize.py --id arxiv:2301.04589     # 总结单篇
```

输出字段（存入 SQLite）：核心问题 / 核心创新 / 方法 / 实验结果 / 不足与空白

### `browse.py` — 本地浏览界面

```bash
python browse.py
```

访问 `http://localhost:5000`，支持：
- 按会议、年份、标记、状态筛选
- 标题/摘要关键词搜索
- 查看 AI 总结详情
- 编辑"我的思考"并保存
- 点击"打开 PDF"用系统 PDF 阅读器直接查看

---

## 典型使用示例

### 示例 A：快速调研高相关论文

```bash
python collect.py                        # 检索元数据（首次约 10 分钟）
python filter.py --auto                  # 快速自动打分
python download.py --high                # 下载高相关论文
python summarize.py --label high         # AI 批量总结
python browse.py                         # 浏览总结，开始阅读
```

### 示例 B：只看 NeurIPS 2024

```bash
python collect.py --venue neurips --year 2024
python filter.py
python download.py
python browse.py
```

### 示例 C：对单篇论文生成总结

```bash
# 确保 PDF 已下载后运行：
python summarize.py --id arxiv:2301.04589
```

---

## 运行测试

```bash
python -m pytest tests/ -v
```

期望输出：31 个测试全部通过。

---

## 注意事项

- arXiv 下载有频率限制，`download.py` 已内置每次 1 秒延迟，勿并发多次运行
- `config.py` 已加入 `.gitignore`，API Key 不会被提交到 git
- AI 总结可能存在幻觉，关键信息请回原文核对
