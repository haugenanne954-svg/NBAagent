# NBA Agent 🏀

基于 **LangGraph Supervisor 多 Agent 架构**的 NBA 智能问答助手，用中文回答关于 NBA 比赛数据、新闻资讯、薪资合同和 CBA 劳资协议的问题。

## 功能概览

| 能力 | 说明 | 数据源 |
|------|------|--------|
| 比赛数据查询 | 比分、赛程、球员统计、球队战绩、联盟排名、排行榜、高阶数据 | basketball-reference.com |
| 新闻资讯检索 | 球员/球队新闻、伤病报告 | Tavily（限定 nba.com / espn / rotowire 等） |
| 薪资合同分析 | 球员合同明细、球队薪资总览、工资帽体系、交易薪资匹配验证 | HoopsHype + 硬编码官方数字 |
| CBA 协议检索 | 2023 NBA CBA 劳资协议原文 RAG 查询 | Chroma 向量库（本地） |
| 综合分析 | 球员/球队对比、战术分析、交易评估、比赛预测 | LLM 推理（基于前置 Agent 数据） |

## 架构

```
用户提问
  ↓
┌──────────────────────────────────────────────────┐
│  Supervisor (意图分类 → 输出 JSON plan)            │
│    ↓ router 按 plan 顺序逐个派发                    │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐          │
│  │ Data │  │ News │  │Salary│  │Analy.│          │
│  │Agent │  │Agent │  │Agent │  │Agent │          │
│  └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘          │
│     ↓         ↓         ↓         ↓               │
│  [8个工具]  [2个工具]  [4个工具    [纯LLM]         │
│                       +RAG]                       │
│                     ↓                             │
│  Finalize (整合 facts → 最终回答)                   │
└──────────────────────────────────────────────────┘
```

**执行流程**：
1. **Supervisor** 分析用户问题，输出有序 plan（如 `["data", "salary", "analysis"]`）
2. **Router** 按 plan 逐个派发到对应子 Agent
3. 每个子 Agent 将结果写入 `state.facts`，后续 Agent 可引用前置结果
4. 所有 plan 执行完毕后进入 **Finalize**，整合各 Agent 输出为最终回答
5. 状态通过 SQLite Checkpointer 持久化，支持多轮对话

## 项目结构

```
nba_agent/
├── __init__.py              # 项目根包
├── main.py                  # CLI 入口（单次/交互式）
├── config.py                 # 全局配置（.env + 路径常量）
├── graph.py                 # LangGraph 状态图构建
├── agents/
│   ├── __init__.py
│   ├── state.py             # 共享状态定义（NBAState）
│   ├── supervisor.py        # Supervisor 节点：意图分类 + plan 生成
│   ├── sub_agents.py        # 4 个子 Agent 节点工厂
│   └── finalize.py         # Finalize 节点：整合最终回答
├── llm/
│   ├── __init__.py
│   └── client.py            # ChatOpenAI 客户端（兼容豆包/Ark）
├── prompts/
│   ├── __init__.py
│   ├── _common.py           # 共用 prompt 片段（时间锚点/翻译规则/硬约束）
│   ├── supervisor.py        # Supervisor prompt
│   ├── sub_agents.py        # 4 个子 Agent prompt
│   └── finalize.py          # Finalize prompt
├── tools/
│   ├── __init__.py           # 工具汇总导出
│   ├── base.py              # 通用装饰器（缓存/重试/错误结构化）
│   ├── data/
│   │   ├── __init__.py
│   │   ├── _bbref.py        # basketball-reference 抓取层
│   │   ├── _resolver.py     # 中英文→bbref/nba_api 标识符解析
│   │   ├── scoreboard.py    # 每日比分
│   │   ├── team_schedule.py # 球队赛程
│   │   ├── standings.py     # 联盟排名
│   │   ├── player_stats.py  # 球员数据 + 基本信息
│   │   ├── team_stats.py    # 球队基础统计
│   │   ├── advanced_stats.py# 球队高阶数据（Pace/ORtg/DRtg/四要素）
│   │   └── leaders.py       # 联盟排行榜
│   ├── news/
│   │   ├── __init__.py
│   │   ├── injury.py        # 伤病报告（Tavily）
│   │   └── search.py        # NBA 资讯搜索（Tavily）
│   └── salary/
│       ├── __init__.py
│       ├── _hoopshype.py    # HoopsHype 薪资页抓取
│       ├── _slugs.py        # 球队缩写→HoopsHype URL slug 映射
│       ├── cap_info.py      # 工资帽/Apron/MLE 数字（硬编码）
│       ├── player_salary.py # 单球员合同明细
│       ├── team_payroll.py  # 球队薪资总览
│       └── trade_validator.py# 交易薪资匹配核查
├── rag/
│   ├── __init__.py
│   └── cba/
│       ├── __init__.py
│       ├── ingest.py        # CBA PDF 入库（pdfplumber→Chroma）
│       ├── retriever.py     # CBA RAG 检索接口
│       └── tool.py          # query_cba_rule LangChain 工具
└── flow/                    # 阶段 5：流式输出与事件归一化
    ├── __init__.py
    ├── normalize.py         # LangGraph 原始事件 → 统一 flow event
    ├── runner.py            # graph.astream_events 运行器
    └── terminal.py          # CLI 事件渲染
```

## 快速开始

### 1. 环境准备

```bash
# Python 3.11+
pip install -r requirements.txt
```

主要依赖：
- `langchain` / `langgraph` / `langchain-openai` / `langchain-chroma` / `langchain-huggingface`
- `nba_api` — NBA 官方静态数据
- `tavily-python` — Tavily 搜索 API
- `pdfplumber` / `chromadb` — CBA RAG 管线
- `loguru` / `pydantic-settings` / `diskcache`

### 2. 配置

在项目**上级目录**创建 `.env` 文件：

```env
# LLM（兼容 OpenAI 接口，可接豆包/Ark 或其他提供商）
LLM_API_KEY=your-api-key
LLM_MODEL_ID=your-model-id
LLM_BASE_URL=https://your-api-endpoint/v1
LLM_TIMEOUT=180

# Tavily（可选，NewsAgent 需要）
TAVILY_API_KEY=your-tavily-key

# RAG embedding（可选，有默认值）
EMBEDDING_MODEL_NAME=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
HF_ENDPOINT=https://hf-mirror.com   # 国内镜像
CBA_COLLECTION_NAME=cba_2023
```

### 3. 构建 CBA 向量库（首次运行）

将 2023 NBA CBA PDF 放到 `data/cba/2023_cba.pdf`，然后：

```bash
python -m nba_agent.rag.cba.ingest
# 强制重建：
python -m nba_agent.rag.cba.ingest --force
```

### 4. 运行

```bash
# 一次性问答
python -m nba_agent.main "湖人最近怎么样？"

# 交互式多轮对话
python -m nba_agent.main --interactive --thread my-session

# CLI 流式输出：展示 plan / 子 Agent 进度 / finalize token
python -m nba_agent.main --stream --thread my-session "湖人最近怎么样？"

# 交互式 + 流式
python -m nba_agent.main --interactive --stream --thread my-session

# 启动 Web 服务（含 SSE 流式接口）
python -m nba_agent.main --serve --port 8000

# 开启 DEBUG 日志
python -m nba_agent.main -v "对比东契奇和约基奇"
```

## 阶段 5：体验与工程化

- **CLI**：支持单次问答、交互式多轮、`--thread` checkpoint 复用，以及 `--stream` 实时输出执行进度和最终回答 token。
- **Flow 层**：`nba_agent.flow` 基于 `graph.astream_events()` 归一化 LangGraph 事件，输出 `plan / agent_start / agent_done / answer_delta / done / error`。
- **Web/SSE**：`GET /api/stream` 直接消费 Flow 层事件，FastAPI 前端可以实时展示 Agent pipeline 与回答增量。
- **测试**：新增 `tests/test_phase5.py`，覆盖路由、状态 reducer、流式事件归一化、SSE 格式和 CBA 引用渲染。

## 工具列表

### Data Tools（8 个）

| 工具 | 说明 |
|------|------|
| `get_daily_scoreboard` | 某日全部比赛比分（按 ET 日期） |
| `get_team_schedule` | 球队近 N 场赛程/赛果（含季后赛） |
| `get_standings` | 东西部排名（战绩/胜率/胜场差） |
| `get_player_career_stats` | 球员近 N 季场均数据 |
| `get_player_info` | 球员基础信息（位置/身高/体重/选秀等） |
| `get_team_stats` | 球队赛季场均数据 |
| `get_team_advanced_stats` | 球队高阶数据（Pace/ORtg/DRtg/四要素+联赛排名） |
| `get_league_leaders` | 联盟数据排行榜 |

### News Tools（2 个）

| 工具 | 说明 |
|------|------|
| `nba_news_search` | NBA 资讯搜索（Tavily） |
| `get_injury_report` | 伤病报告（Tavily） |

### Salary Tools（4 个）

| 工具 | 说明 |
|------|------|
| `get_team_payroll` | 球队薪资总览（HoopsHype） |
| `get_player_salary` | 单球员多年合同明细 |
| `get_salary_cap_info` | 工资帽/Apron/MLE 数字 |
| `validate_trade` | 交易薪资匹配核查 |

### RAG Tools（1 个）

| 工具 | 说明 |
|------|------|
| `query_cba_rule` | CBA 条款语义检索（Chroma + MMR） |

## 使用示例

```
你> 湖人最近怎么样？
→ DataAgent: 查赛程 + 战绩

你> 勇士薪资和最近战绩如何？
→ DataAgent + SalaryAgent

你> 对比一下东契奇和约基奇
→ DataAgent(双方数据) + AnalysisAgent(对比分析)

你> 这笔交易合不合理？
→ DataAgent(球员实力) + SalaryAgent(薪资匹配+CBA) + AnalysisAgent(综合评估)

你> 今晚 OKC vs Lakers 谁会赢？
→ DataAgent(双方数据) + NewsAgent(伤病) + AnalysisAgent(比赛预测)
```

## 设计要点

- **中文优先**：所有 prompt、输出均为中文，球员/球队名支持中英文混合输入
- **幻觉防控**：硬约束 prompt + 工具返回结构化错误 + 数字必须以工具返回为准
- **跨 Agent 信息传递**：`facts` 字典让后续 Agent 能引用前置 Agent 查到的数据，避免重复查询
- **时间感知**：每轮运行时动态注入时间锚点（北京时间 + 美东时间），自动处理赛季/时区换算
- **磁盘缓存**：`tools/base.py` 提供基于 diskcache 的缓存装饰器，减少重复网络请求
- **速率限制**：bbref / HoopsHype 爬取层内置线程安全的请求节流

## License

MIT
