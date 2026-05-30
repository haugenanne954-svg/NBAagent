# NBA Agent — 基于 LangGraph 的多 Agent NBA 智能问答助手

基于 **LangGraph Supervisor 多 Agent 架构**的 NBA 智能问答系统，支持比赛数据、新闻资讯、薪资合同、CBA 劳资协议查询，以及球员对比、交易评估、战术分析、比赛预测等高阶分析。

## 功能特性

- **7 类任务全覆盖**：比赛成绩 / 球员数据 / 球队数据 / 资讯查询 / 薪资结构 / 交易分析 / 战术分析与比赛预测
- **Supervisor 多 Agent 协作**：Supervisor 自动识别意图、生成执行计划，按需调度 4 个专业子 Agent，跨 Agent 传递事实数据
- **CBA 协议 RAG 查询**：对 676 页 NBPA 2023 CBA PDF 建立向量索引，支持语义检索条款原文并附带精确引用（Article / Section / Page）
- **幻觉防控**：所有数字必须来自工具返回，CBA 规则必须带条款引用，finalize 节点校验出处完整性
- **中英文混合输入**：支持"湖人"、"詹姆斯"、"SGA"等中文/缩写输入，自动解析为对应标识符
- **多轮对话**：SQLite Checkpointer 持久化对话状态，同一 thread_id 跨会话保留上下文
- **磁盘缓存 + 速率限制**：工具调用结果磁盘缓存，basketball-reference / HoopsHype 请求自动限速

## 架构概览

```
                       ┌──────────────────────────┐
                       │      用户 / CLI          │
                       └──────────────┬───────────┘
                                      │
                              ┌───────▼────────┐
                              │  Supervisor    │  ← 意图识别 + 任务规划 + 路由
                              └───┬──┬──┬──┬───┘
                                  │  │  │  │
            ┌─────────────────────┘  │  │  └──────────────────┐
            │           ┌────────────┘  └───────────┐          │
            ▼           ▼                           ▼          ▼
       ┌─────────┐ ┌──────────┐               ┌──────────┐ ┌──────────────┐
       │ Data    │ │  News    │               │ Salary   │ │  Analysis    │
       │ Agent   │ │  Agent   │               │ Agent    │ │  Agent       │
       └────┬────┘ └────┬─────┘               └────┬─────┘ └──────┬───────┘
            │           │                          │              │
            ▼           ▼                          ▼              ▼
     ┌────────────────────────────────────────────────────────────────┐
     │                     Tools Layer                               │
     │  basketball-reference / Tavily / HoopsHype / CBA RAG / 缓存   │
     └────────────────────────────────────────────────────────────────┘
                                      │
                              ┌───────▼────────┐
                              │ Shared Context │  ← facts / citations / messages
                              └────────────────┘
```

### Agent 分工

| Agent | 职责 | 工具数 | 说明 |
|-------|------|--------|------|
| **Supervisor** | 意图分类 + 生成执行计划（JSON plan） | 0 | temperature=0.0，输出 plan 并调度子 Agent |
| **DataAgent** | 比赛成绩 / 球员数据 / 球队数据 / 排名 / 高阶统计 | 8 | 数据源：basketball-reference.com |
| **NewsAgent** | 资讯搜索 / 伤病报告 | 2 | 数据源：Tavily API |
| **SalaryAgent** | 薪资合同 / 工资帽 / CBA 规则查询 | 4 + 1 RAG | 数据源：HoopsHype + 硬编码官方数字 + CBA RAG |
| **AnalysisAgent** | 对比 / 评估 / 预测 / 战术分析 | 0 | 无工具，只读前置 Agent 的 facts 做推理 |
| **Finalize** | 整合各 Agent 输出为最终回答 | 0 | 按 data→news→salary→analysis 顺序组织输出 |

## 快速开始

### 环境要求

- Python 3.11+
- 网络可访问 LLM API 端点（兼容 OpenAI 接口，如豆包 / Ark 等）
- 可选：Tavily API Key（NewsAgent 依赖）

### 安装

```bash
pip install -r requirements.txt
```

### 配置

在项目根目录创建 `.env` 文件：

```env
# ── 必填：LLM 配置（兼容 OpenAI 接口） ──
LLM_API_KEY=your-api-key
LLM_MODEL_ID=your-model-id
LLM_BASE_URL=https://your-api-endpoint/v1

# ── 可选 ──
LLM_TIMEOUT=180
TAVILY_API_KEY=your-tavily-key
EMBEDDING_MODEL_NAME=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
HF_ENDPOINT=https://hf-mirror.com
CBA_COLLECTION_NAME=cba_2023
```

### 构建 CBA 向量库（首次运行）

将 NBPA 2023 CBA PDF 放到 `data/cba/2023_cba.pdf`，然后执行：

```bash
python -m nba_agent.rag.cba.ingest
# 强制重建：
python -m nba_agent.rag.cba.ingest --force
```

### 运行

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

## 项目结构

```
├─ data/
│  ├─ cba/
│  │  ├─ 2023_cba.pdf              # NBPA 2023 CBA 协议 PDF（需手动放入）
│  │  └─ chroma/                    # Chroma 向量库持久化
│  ├─ checkpoints.sqlite            # LangGraph 会话 checkpoint
│  └─ tool_cache/                   # diskcache 工具结果缓存
├─ nba_agent/
│  ├─ __init__.py
│  ├─ main.py                       # CLI 入口
│  ├─ config.py                     # 全局配置（环境变量 + 路径常量）
│  ├─ graph.py                      # LangGraph 状态图构建与路由
│  ├─ agents/
│  │  ├─ state.py                   # NBAState 共享状态定义
│  │  ├─ supervisor.py              # Supervisor 节点
│  │  ├─ sub_agents.py              # 4 个子 Agent 节点工厂
│  │  └─ finalize.py                # Finalize 汇总节点
│  ├─ llm/
│  │  └─ client.py                  # ChatOpenAI 客户端（兼容豆包/Ark）
│  ├─ prompts/
│  │  ├─ _common.py                 # 共用 prompt 片段
│  │  ├─ supervisor.py              # Supervisor 提示词
│  │  ├─ sub_agents.py              # 4 个子 Agent 提示词（含 5 大分析场景模板）
│  │  └─ finalize.py                # Finalize 提示词
│  ├─ tools/
│  │  ├─ base.py                    # 通用装饰器（缓存/重试/错误结构化）
│  │  ├─ data/                      # 8 个数据查询工具（basketball-reference）
│  │  │  ├─ _bbref.py               #   爬取层（速率限制 + 注释剥离）
│  │  │  ├─ _resolver.py            #   中英文→标识符解析
│  │  │  ├─ scoreboard.py           #   每日比分
│  │  │  ├─ team_schedule.py        #   球队赛程
│  │  │  ├─ standings.py            #   联盟排名
│  │  │  ├─ player_stats.py         #   球员数据 + 基本信息
│  │  │  ├─ team_stats.py           #   球队基础统计
│  │  │  ├─ advanced_stats.py       #   球队高阶数据
│  │  │  └─ leaders.py              #   联盟排行榜
│  │  ├─ news/                      # 2 个资讯工具（Tavily）
│  │  │  ├─ search.py               #   NBA 资讯搜索
│  │  │  └─ injury.py               #   伤病报告
│  │  └─ salary/                    # 4 个薪资工具（HoopsHype + 硬编码）
│  │     ├─ _hoopshype.py           #   HoopsHype 爬取层
│  │     ├─ _slugs.py               #   球队缩写→URL slug 映射
│  │     ├─ cap_info.py             #   工资帽/Apron/MLE 数字
│  │     ├─ player_salary.py        #   单球员合同明细
│  │     ├─ team_payroll.py         #   球队薪资总览
│  │     └─ trade_validator.py      #   交易薪资匹配核查
│  ├─ rag/
│  │  └─ cba/                       # CBA 协议 RAG 子系统
│  │     ├─ ingest.py               #   PDF → 切分 → 向量化 → Chroma
│  │     ├─ retriever.py            #   检索 + MMR 去冗余
│  │     └─ tool.py                  #   query_cba_rule 工具入口
│  └─ flow/
│     ├─ __init__.py                 # 流式能力导出
│     ├─ normalize.py                # LangGraph 原始事件 → 统一 flow event
│     ├─ runner.py                   # graph.astream_events 运行器
│     └─ terminal.py                 # CLI 事件渲染
├─ tests/
│  ├─ probe_tools.py                 # 工具层直接 invoke 验证
│  ├─ smoke_checkpoint.py            # SQLite checkpointer 落库验证
│  ├─ smoke_multi_agent.py          # 阶段 3 端到端 smoke test
│  ├─ smoke_phase4.py               # 阶段 4 端到端 smoke test
│  ├─ smoke_multi_turn.py           # 多轮对话状态恢复验证
│  └─ test_phase5.py                # 阶段 5 快速 pytest 覆盖
├─ requirements.txt
└─ .env                              # 环境变量配置
```

## 工具清单

### 数据工具（8 个）— basketball-reference.com

| 工具 | 说明 |
|------|------|
| `get_daily_scoreboard` | 某日全部比赛比分 |
| `get_team_schedule` | 球队近 N 场赛程/赛果 |
| `get_standings` | 东西部排名 |
| `get_player_career_stats` | 球员近 N 季场均数据 |
| `get_player_info` | 球员基础信息 |
| `get_team_stats` | 球队赛季场均数据 |
| `get_team_advanced_stats` | 球队高阶数据（Pace/ORtg/DRtg/四要素 + 联盟排名） |
| `get_league_leaders` | 联盟数据排行榜 |

### 资讯工具（2 个）— Tavily API

| 工具 | 说明 |
|------|------|
| `nba_news_search` | NBA 资讯搜索 |
| `get_injury_report` | 伤病报告 |

### 薪资工具（4 个）— HoopsHype + 硬编码

| 工具 | 说明 |
|------|------|
| `get_team_payroll` | 球队薪资总览 |
| `get_player_salary` | 单球员多年合同明细 |
| `get_salary_cap_info` | 工资帽/Apron/MLE 数字（2023-24 ~ 2025-26 三赛季） |
| `validate_trade` | 交易薪资匹配核查（三档规则 + Apron 状态提醒） |

### RAG 工具（1 个）— Chroma 向量库

| 工具 | 说明 |
|------|------|
| `query_cba_rule` | CBA 条款语义检索，返回条款原文 + (Article, Section, Page) 引用 |

## 使用示例

| 问题类型 | 示例 | 涉及 Agent |
|----------|------|------------|
| 纯数据 | "湖人最近怎么样？" | DataAgent |
| 纯薪资 | "勇士现在团队薪资多少？工资帽在哪？" | SalaryAgent |
| 薪资 + 规则 | "什么是 Bird Rights？要满足什么条件？" | SalaryAgent (RAG) |
| 数据 + 薪资 | "勇士战绩和全队薪资情况" | DataAgent → SalaryAgent |
| 战术分析 | "雷霆为什么防守强？" | DataAgent → AnalysisAgent |
| 球队对比 | "雷霆 vs 马刺谁更均衡？" | DataAgent → AnalysisAgent |
| 比赛预测 | "OKC vs Lakers 谁赢？" | DataAgent → NewsAgent → AnalysisAgent |
| 交易评估 | "Reaves+Hachimura 换 Murphy III 合理吗？" | DataAgent → SalaryAgent → AnalysisAgent |

## 技术选型

| 类别 | 选择 | 理由 |
|------|------|------|
| Agent 框架 | **LangGraph** + `langgraph-checkpoint-sqlite` | StateGraph / create_react_agent / supervisor 路由 / 内置 checkpoint |
| LLM 客户端 | `langchain-openai` ChatOpenAI | 与 LangGraph 原生兼容，可接豆包/Ark 等 OpenAI 兼容端点 |
| 结构化数据 | basketball-reference.com | 官方源、免费、国内可访问（替代被 WAF 拦截的 nba_api） |
| 资讯搜索 | Tavily | 已有 Key，限定专业站点 |
| 薪资数据 | HoopsHype | 爬虫可访问（替代被 Cloudflare 拦截的 Spotrac） |
| CBA RAG - PDF 解析 | `pdfplumber` | 支持表格优先抽取 |
| CBA RAG - 切分 | `langchain-text-splitters` | RecursiveCharacterTextSplitter，chunk≈900/overlap 150 |
| CBA RAG - Embedding | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 多语言，中文 query→英文文档检索效果可用 |
| CBA RAG - 向量库 | `chromadb` | 本地持久化，零运维 |
| 缓存 | `diskcache` | 工具调用结果磁盘缓存 |
| 配置 | `pydantic-settings` | 类型安全 |
| 日志 | `loguru` | 简洁易用 |

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_API_KEY` | 是 | — | LLM API 密钥 |
| `LLM_MODEL_ID` | 是 | — | 模型 ID |
| `LLM_BASE_URL` | 是 | — | OpenAI 兼容接口地址 |
| `LLM_TIMEOUT` | 否 | 180 | 超时秒数 |
| `TAVILY_API_KEY` | 否 | None | NewsAgent 依赖，未配置时新闻工具返回错误 |
| `EMBEDDING_MODEL_NAME` | 否 | sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | RAG Embedding 模型 |
| `HF_ENDPOINT` | 否 | None | HuggingFace 镜像端点（国内可设 hf-mirror.com） |
| `CBA_COLLECTION_NAME` | 否 | cba_2023 | Chroma 集合名 |

## 测试

```bash
# 工具层直接验证（不调 LLM）
python -m tests.probe_tools

# SQLite checkpointer 验证
python -m tests.smoke_checkpoint

# 多 Agent 端到端验证
python -m tests.smoke_multi_agent

# 高阶分析验证
python -m tests.smoke_phase4

# 多轮对话验证
python -m tests.smoke_multi_turn

# 阶段 5 快速单元测试（不调 LLM / 不访问外网）
python -m pytest -q tests/test_phase5.py
```

## 阶段 5 工程化能力

- **CLI 多轮与流式输出**：`--thread` 复用 SQLite checkpoint，`--stream` 通过 `graph.astream_events()` 输出 Supervisor plan、子 Agent 开始/完成事件和 Finalize token。
- **统一 Flow 层**：`nba_agent.flow` 将 LangGraph 原始事件归一化为稳定的 `plan / agent_start / agent_done / answer_delta / done / error` 事件，CLI 与 Web 共用同一套逻辑。
- **Web/SSE**：`python -m nba_agent.main --serve` 启动 FastAPI 页面，`GET /api/stream` 返回真实 SSE 流，不再等待完整回答后模拟分段。
- **pytest 覆盖**：`tests/test_phase5.py` 覆盖路由、state reducer、事件归一化、SSE 格式和 CBA 引用渲染，适合快速回归。

## 关键设计约束

1. **事实必须出处可查**：数字必须来自工具返回，CBA 规则必须带条款引用
2. **AnalysisAgent 不调外部工具**：只读 `state.facts`，保持分析与取数解耦
3. **function-calling 优先**：全部走 LangGraph `create_react_agent`，禁止文本/JSON 字符串解析
4. **工具有缓存键**：`(tool_name, args_hash, date_bucket)` 作 key，控制对外请求量
5. **失败优雅降级**：工具失败返回 `{"error": "...", "retryable": bool}`，Agent 换工具或如实告知用户
6. **CBA RAG 引用强制**：SalaryAgent 涉及规则类回答时，必须透传至少一条条款原文 + 引用

## 开发路线

- [x] **阶段 0**：LangGraph 骨架（最小图 + SQLite checkpoint + 多轮对话）
- [x] **阶段 1**：数据 & 资讯工具补齐（basketball-reference 8 个工具 + Tavily 2 个工具）
- [x] **阶段 2**：薪资工具 + CBA RAG（HoopsHype 4 个工具 + Chroma RAG 1944 chunks）
- [x] **阶段 3**：Supervisor 多 Agent（1 Supervisor + 4 子 Agent + Finalize + conditional_edges 路由）
- [x] **阶段 4**：分析能力（5 大高阶场景 + `get_team_advanced_stats` + prompt 模板化）
- [x] **阶段 5**：体验与工程化（CLI `--stream` / 真实 SSE 流式 / `nba_agent.flow` / `tests/test_phase5.py` / Web 前端）
