# NBA 助手 Agent 设计方案（plan.md）

> 本文档由"Agent 架构设计师"视角输出，目标是把当前的最小 ReAct 骨架，逐步演化为一个能完成 **比赛成绩、球员数据、薪资结构、资讯查询、交易分析、战术分析、比赛预测** 全部 7 类任务的 NBA 助手 Agent。后续编码工作将严格参照本文件分阶段推进。

---

## 1. 现状梳理

### 1.1 目录结构（当前）

```
temp/
├─ agent.py     # 简单 ReAct Agent（文本解析）
├─ llm.py       # 豆包 / OpenAI 兼容 LLM 客户端
├─ tools.py     # Tool 基类 + NBASearchTool（Tavily）
└─ .env         # LLM_API_KEY / TAVILY_API_KEY
```

### 1.2 现有能力 & 缺陷

| 维度 | 现状 | 问题 |
|---|---|---|
| LLM 调用 | OpenAI SDK + 流式 | 异常吞掉、无重试、无 token 统计 |
| 工具系统 | 单一 Tavily 搜索 | 没有结构化数据源（赛程/球员/薪资） |
| Agent 编排 | 单 Agent，文本解析 ReAct | 解析脆弱、无循环上限、无路由 |
| 状态/记忆 | 无 | 多轮对话和缓存无从谈起 |
| 工程化 | 单层目录 | 没有分包、没有日志、没有测试 |

---

## 2. 总体架构（目标态）

采用 **"Supervisor 多 Agent + 分层 Tools + 共享 Context"** 模式。

### 2.1 架构图

```
                       ┌──────────────────────────┐
                       │      用户 / CLI / API     │
                       └──────────────┬───────────┘
                                      │
                              ┌───────▼────────┐
                              │  Supervisor    │  ← 意图识别 + 任务规划 + 路由 + 汇总
                              │  (Router LLM)  │
                              └───┬──┬──┬──┬───┘
                                  │  │  │  │
            ┌─────────────────────┘  │  │  └────────────────────────┐
            │           ┌────────────┘  └───────────┐                │
            ▼           ▼                           ▼                ▼
       ┌─────────┐ ┌──────────┐               ┌──────────┐    ┌──────────────┐
       │ Data    │ │  News    │               │ Salary   │    │  Analysis    │
       │ Agent   │ │  Agent   │               │ Agent    │    │  Agent       │
       └────┬────┘ └────┬─────┘               └────┬─────┘    └──────┬───────┘
            │           │                          │                 │
            ▼           ▼                          ▼                 ▼
     ┌──────────────────────────────────────────────────────────────────────┐
     │                          Tools Layer                                 │
     │  nba_api / Tavily / Spotrac 爬虫 / 本地计算 / 缓存 / 数据库            │
     └──────────────────────────────────────────────────────────────────────┘
                                      │
                              ┌───────▼────────┐
                              │ Shared Context │  ← 用户问题、事实、中间结论、对话历史
                              └────────────────┘
```

### 2.2 角色分工

| 组件 | 职责 | 关键提示词偏向 |
|---|---|---|
| **Supervisor** | 意图分类（7 类任务 → 子 Agent），多步任务规划，结果汇总改写 | 路由 + 规划 |
| **DataAgent** | 比赛成绩 / 球员数据 / 球队数据 / 排名 / 赛程 | 严格、结构化、引用数据 |
| **NewsAgent** | 资讯、伤病、交易动态、舆论摘要 | 多源对比、给出引用 |
| **SalaryAgent** | 工资帽、球员/球队薪资、奢侈税、交易匹配、**CBA 条款检索（RAG）** | CBA 规则严谨，引用条款原文 |
| **AnalysisAgent** | 交易评估、战术分析、比赛预测 | 推理为主，**强制**消费上面三个 Agent 的事实 |

---

## 3. 工具层设计（Tools Layer）

> 原则：**事实查询走 API/爬虫，主观分析走 LLM**。所有工具继承 `Tool` 基类并提供 JSON Schema。

### 3.1 工具清单

#### A. 数据工具（接 `nba_api` / `basketball-reference`）

| 工具名 | 输入 | 输出 | 用途 |
|---|---|---|---|
| `get_scoreboard` | date | 当日比赛列表 + 比分 | 比赛成绩 |
| `get_boxscore` | game_id | 双方 box score | 单场详情 |
| `get_player_stats` | player_name, season, mode(场均/累计) | 球员数据 | 球员查询 |
| `get_team_stats` | team_name, season | 球队数据 | 球队查询 |
| `get_standings` | season, conference | 排名 | 排名 |
| `get_player_info` | player_name | 身高/体重/位置/合同 | 球员资料 |
| `get_schedule` | team_name, date_range | 赛程 | 赛程查询 |
| `get_league_leaders` | category(得分/助攻/篮板…), season | 排行榜 | 数据排行 |

#### B. 薪资工具（HTML 爬虫，源 Spotrac/HoopsHype）

| 工具名 | 输入 | 输出 |
|---|---|---|
| `get_player_salary` | player_name | 该球员未来几年合同明细（年薪、保障类型） |
| `get_team_payroll` | team_name | 球队总薪资、奢侈税位置 |
| `get_salary_cap_info` | season | 工资帽、奢侈税线、土豪线 |
| `validate_trade` | players_in/out + teams | 是否满足 CBA **硬性**交易匹配规则（薪资 125%+10 万、硬上限触发等，代码实现） |
| `query_cba_rule` | natural_language_question | 检索 CBA 协议原文（RAG），返回条款片段 + 章节引用 |

> `validate_trade` 与 `query_cba_rule` 是 **互补关系**：前者用代码硬编几条最常用的薪资匹配规则，结果确定；后者负责所有"例外条款、签换规则、Bird 权、各种 MLE/BAE/退伍军人最低、Apron 限制"等模糊/长尾问题，必须给出条款原文出处。

#### C. 资讯工具

| 工具名 | 输入 | 输出 |
|---|---|---|
| `nba_news_search` | query（已有，Tavily） | 资讯摘要 + 来源 |
| `get_injury_report` | team_name? player_name? | 伤病列表（结构化） |
| `get_transaction_feed` | days | 近 N 天官方交易/签约动态 |

#### D. 分析工具（轻量本地计算 + LLM）

| 工具名 | 输入 | 输出 |
|---|---|---|
| `compare_players` | player_a, player_b, season | 高阶数据对比表 |
| `compare_teams` | team_a, team_b, season | 球队对位对比 |
| `predict_game` | team_a, team_b, context | 胜率/比分预测（基于数据 + LLM 推理） |
| `evaluate_trade` | trade_proposal | 给出双方收益评分与理由 |
| `analyze_tactics` | team_name, recent_n_games | 战术风格（pace/3PAr/AST%/进攻类型） |

### 3.2 Tool 基类

工具统一通过 LangChain 的 `@tool` 装饰器或 `BaseTool` 子类暴露，要求：

- `name`、`description`（给 LLM 看的工具说明）
- `args_schema`：用 `pydantic.BaseModel` 定义入参，LangGraph 会自动转 function-calling schema
- 统一异常处理 + `diskcache` 缓存 + `loguru` 日志（用装饰器叠加）
- 工具失败必须返回结构化错误 `{"error": "...", "retryable": bool}`，由 Agent 决策是否换工具

### 3.3 CBA RAG 模块设计

放在 `nba_agent/rag/cba/` 下，单独的子系统，对上以一个工具 `query_cba_rule` 暴露给 `SalaryAgent`。

| 步骤 | 选型 | 说明 |
|---|---|---|
| 文档源 | NBPA 官网 2023 CBA PDF（用户本地放到 `data/cba/2023_cba.pdf`） | 600+ 页英文 |
| PDF 解析 | `pypdf` 或 `pdfplumber`（带表格优先 pdfplumber） | 保留页码 |
| 切分 | `RecursiveCharacterTextSplitter`，chunk≈800 token / overlap 120 | 按章节/条款标题优先切，再按字符 |
| 元数据 | `{article, section, page, source}` | 检索时一并返回，**必须**作为引用 |
| Embedding | 首选豆包 embedding；若无可用，回退 `bge-m3` 或 `sentence-transformers/paraphrase-multilingual-MiniLM` | 中英文都要兼容（用户提问大概率是中文） |
| 向量库 | `Chroma`（持久化到 `data/cba/chroma/`） | 简单、本地、零运维 |
| 检索 | 默认 top-k=5 + MMR 去冗 | 可后接一次轻量重排（cross-encoder，可选） |
| 输出 | "条款原文片段 + (Article X, Section Y, Page Z)" 结构化返回给 Agent | Agent 引用时必须带出处 |

`query_cba_rule` 工具的接口：

```python
class CBAQueryInput(BaseModel):
    question: str
    top_k: int = 5

# 返回
{
  "passages": [
    {"text": "...", "article": "VII", "section": "5", "page": 213},
    ...
  ]
}
```

**强约束**：`SalaryAgent` 在回答 CBA 相关问题时，必须把 `query_cba_rule` 返回的 `passages` 原样列出至少 1 条作为依据；否则 Supervisor 在汇总阶段会驳回重答。

---

## 4. Agent 编排层设计（LangGraph 实现）

### 4.1 框架选择

使用 **LangGraph**：
- `StateGraph` 直接做我们要的 Shared Context（不用自己写一套）
- `create_react_agent` 已经实现了 function-calling 风格的 ReAct，比自研文本/JSON 协议稳得多
- `supervisor` 模式（`langgraph-supervisor` 或手写 conditional edges）天然适配本项目的"1 主 4 从"结构
- `MemorySaver` / `SqliteSaver` 内置 checkpoint，多轮对话直接落地

### 4.2 共享状态（State）

用 `TypedDict` + `Annotated` 定义图状态，所有节点读写同一个 State：

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class NBAState(TypedDict):
    messages: Annotated[list, add_messages]   # 对话历史（含工具调用轨迹）
    user_query: str
    plan: list[dict]                          # Supervisor 产出的子任务列表
    facts: dict                               # key=output_key, value=子 Agent 返回的事实
    citations: list[dict]                     # 统一的引用来源（含 CBA 条款页码）
    next_agent: str                           # Supervisor 决定的下一跳
```

### 4.3 图结构（Graph）

```
                ┌─────────────┐
                │ supervisor  │ ← 入口：意图分类 + 规划 + 下一跳决策
                └──────┬──────┘
                       │ conditional_edges (按 next_agent 路由)
        ┌──────────┬───┼───┬──────────┐
        ▼          ▼       ▼          ▼
   data_agent  news_agent salary_agent analysis_agent
        │          │       │           │
        └──────────┴───┬───┴───────────┘
                       │ 写回 state.facts，回到 supervisor
                       ▼
                 ┌───────────┐
                 │ finalize  │ ← supervisor 判定 plan 已完成 → 汇总成自然语言
                 └─────┬─────┘
                       ▼
                     END
```

实现要点：
- 4 个子 Agent 都用 `create_react_agent(llm, tools=[...该领域工具])` 一行起手，挂自己的工具子集。
- `supervisor` 节点是一个普通函数 / LLM 节点，输出 `next_agent` 或 `"finalize"`。
- 子 Agent 把"事实摘要 + 引用"写入 `state.facts[output_key]`，然后无条件回到 `supervisor`。
- `finalize` 节点不调任何工具，只做整理 + 风格统一 + 引用渲染，流式输出。

### 4.4 多轮对话与记忆

- 短期记忆：`messages` 字段（LangGraph 自动管理）。
- 持久化：`SqliteSaver` checkpoint 落到 `data/checkpoints.sqlite`，每个会话一个 `thread_id`。
- 长期记忆（可选阶段 5）：把已确认的"用户偏好/常关注球队"写到独立的 KV 存储。

### 4.5 例子串一遍

用户："勇士换 LeBron 这笔交易能成吗，划算吗？"

1. `supervisor`：识别为多意图（薪资 + 数据 + 资讯 + 分析），产出 `plan`：
   ```
   [
     {agent: "salary",   task: "查 LeBron 合同 + 勇士可送出合同 + 匹配规则",   out: "salary"},
     {agent: "data",     task: "LeBron 本赛季高阶数据 + 勇士现有控前数据",      out: "stats"},
     {agent: "news",     task: "近期勇士交易传闻 + LeBron 去留态度",            out: "news"},
     {agent: "analysis", task: "结合以上事实，给出交易评估",                    out: "verdict"},
   ]
   ```
2. 图按 `next_agent` 依次跳到 `salary_agent` → `data_agent` → `news_agent`，每轮把结果写入 `state.facts`。`salary_agent` 内部会调用 `validate_trade` + `query_cba_rule`（如果涉及硬上限/签换规则）。
3. `supervisor` 看到前三步完成，路由到 `analysis_agent`，它只读 `state.facts`，不再调外部工具。
4. `finalize` 节点把 `facts` 渲染成最终回答，附 CBA 条款页码与数据来源。

---

## 5. 目录结构（目标态）

```
project/
├─ data/
│  ├─ cba/
│  │  ├─ 2023_cba.pdf         # 用户下载放入（NBPA 官网）
│  │  └─ chroma/              # 向量库持久化
│  └─ checkpoints.sqlite      # LangGraph 会话 checkpoint
├─ nba_agent/
│  ├─ config.py               # 环境变量、常量、模型名
│  ├─ llm/
│  │  └─ client.py            # ChatOpenAI 包一层（指向豆包 endpoint）
│  ├─ prompts/                # Supervisor / 各子 Agent / finalize 系统提示词
│  ├─ tools/
│  │  ├─ base.py              # 装饰器：缓存 / 重试 / 错误结构化
│  │  ├─ data/                # nba_api 封装
│  │  ├─ news/                # Tavily 等
│  │  ├─ salary/              # Spotrac 爬虫 + validate_trade
│  │  └─ analytics/           # 本地高阶指标计算
│  ├─ rag/
│  │  └─ cba/
│  │     ├─ ingest.py         # PDF → 切分 → 向量化 → 写 Chroma
│  │     ├─ retriever.py      # 检索 + (可选)重排
│  │     └─ tool.py           # query_cba_rule 工具入口
│  ├─ agents/
│  │  ├─ state.py             # NBAState (TypedDict)
│  │  ├─ supervisor.py        # 规划 + 路由节点
│  │  ├─ data_agent.py        # create_react_agent + 数据工具
│  │  ├─ news_agent.py
│  │  ├─ salary_agent.py      # 含 query_cba_rule
│  │  ├─ analysis_agent.py    # 只读 state.facts，无外部工具
│  │  └─ finalize.py          # 汇总节点
│  ├─ graph.py                # 组装 StateGraph + checkpointer
│  └─ main.py                 # CLI 入口
├─ tests/
└─ requirements.txt
```

---

## 6. 技术选型

| 类别 | 选择 | 理由 |
|---|---|---|
| LLM 客户端 | `langchain-openai` 的 `ChatOpenAI` 指向豆包 endpoint | 与 LangGraph / `create_react_agent` 原生兼容，复用现有 Key |
| Agent 框架 | **LangGraph**（核心） + `langgraph-checkpoint-sqlite` | StateGraph、create_react_agent、supervisor 路由、内置 checkpoint，省下大量自研 |
| 结构化数据 | `nba_api` | 官方源、免费、社区活跃 |
| 资讯搜索 | 继续 Tavily | 已有 Key |
| 薪资数据 | `requests + beautifulsoup4` 爬 Spotrac | 没有官方 API |
| CBA RAG - PDF | `pdfplumber`（带表格优先） | NBPA CBA PDF 含大量表格 |
| CBA RAG - 切分 | `langchain-text-splitters` | 与 LangChain 体系打通 |
| CBA RAG - Embedding | 首选豆包 embedding，回退 `bge-m3` / `sentence-transformers` | 中英文兼容 |
| CBA RAG - 向量库 | `chromadb`（本地持久化） | 零运维、易调试 |
| 缓存 | `diskcache` | 工具调用结果缓存 |
| 配置 | `pydantic-settings` | 类型安全 |
| 日志 | `loguru` | 比 logging 顺手 |
| 测试 | `pytest` + LangGraph 的 `MemorySaver` 跑测试用例 | |

---

## 7. 分阶段实现路线图

> **每一阶段都要可独立运行**，避免大重构憋大招。

### 阶段 0：LangGraph 骨架（一次性铺好底座） ✅

- [x] 建好 §5 的目录结构，迁移现有 `llm.py / tools.py / agent.py`。
- [x] `llm/client.py`：用 `ChatOpenAI`（`base_url=豆包`、`api_key`、`model`）替换原生 OpenAI 调用，保留流式。
- [x] `tools/base.py`：写好"缓存 + 重试 + 错误结构化"3 个装饰器，把现有 `NBASearchTool` 改写成 `@tool` 风格。
- [x] `agents/state.py`：定义 `NBAState`。
- [x] `graph.py`：先搭一个**最小图**：`supervisor → single_agent → finalize`，跑通"湖人最近怎么样？"。
- [x] 加 `SqliteSaver` checkpoint，验证多轮对话上下文保持。
- [x] 写 `requirements.txt`。

### 阶段 1：数据 & 资讯工具补齐 ✅

实施中改用 **basketball-reference.com** 作为主数据源（`nba_api` 走 stats.nba.com 在国内被 WAF 拦截）。
完整覆盖 plan 列出的能力，纯 HTML 爬虫 + `pandas.read_html`，不依赖代理也不依赖 API Key。

- [x] 数据工具集（7 个）：`get_daily_scoreboard / get_team_schedule / get_standings / get_team_stats / get_player_career_stats / get_player_info / get_league_leaders`。
- [x] `get_injury_report`（Tavily 限定 rotowire / espn / nba.com 等专业站点）。
- [x] 所有工具叠 `diskcache` + `with_retry` + `safe_tool` 三装饰器。
- [x] 中英文 resolver：球队名 30 队 / 热门球员中文映射；自动转 bbref / nba_api ID。
- [x] Prompt 注入"今天日期 + 当前赛季"，并加硬约束"赛果/数据必须优先用结构化工具"。
- [x] 端到端验证：跑通"湖人最近怎么样？"——Agent 主动调 `get_team_schedule`，准确拿到 5/11 vs OKC L 110-115（0-4 被横扫），不再被 Tavily 老数据误导。

### 阶段 2：薪资工具 + CBA RAG ✅

实施中改用 **HoopsHype** 作为薪资数据源（Spotrac 全站被 Cloudflare 拦截，403）。
Embedding 选 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`（118MB，多语言，
中文 query → 英文文档检索效果验证可用），可通过 `.env: EMBEDDING_MODEL_NAME` 切换。

- [x] HoopsHype 爬虫：`tools/salary/_hoopshype.py`（带最小调用间隔 + 货币解析 + Player/Team Option 标记）。
- [x] 薪资工具组（4 个）：`get_team_payroll / get_player_salary / get_salary_cap_info / validate_trade`。
  - `get_salary_cap_info`：硬编码 2023-24 / 2024-25 / 2025-26 三季工资帽体系（数据来源：NBA League Memo / Larry Coon FAQ）。
  - `validate_trade`：内置薪资匹配硬规则（`≤7.5M / 7.5M-29M / >29M` 三档），并对 Apron 状态额外提醒需要查 CBA。
- [x] **CBA RAG 模块**：
  - [x] 用户已下载 NBPA 2023 CBA PDF → `data/cba/2023_cba.pdf`（676 页）。
  - [x] `rag/cba/ingest.py`：`pdfplumber` 解析 + 页头跟踪 Article 上下文 + 跳过 TOC 页 → 切 900/150 chunk → HF embedding → Chroma 持久化。一次性产出 **1944 个 chunks**。
  - [x] `rag/cba/retriever.py`：top-k + MMR（fetch_k=4k）。
  - [x] `rag/cba/tool.py`：暴露 `query_cba_rule(question, top_k)`，返回的每条片段附 `(Article, Section, Page)` 引用。
  - [x] Prompt 引导 LLM 在调 `query_cba_rule` 前把中文俗称（"鸟权""全额中产""硬上限"）翻译为 CBA 原文术语。
- [x] 端到端验证：
  - "什么是 Bird Rights？要满足什么条件" → 调 `query_cba_rule("Qualifying Veteran Free Agent Bird Rights eligibility")`，返回 Article I §1 Page 31 原文，给出"连续 3 个赛季、效力同一支球队或仅以特定方式更换球队"的准确条件。
  - "勇士现在团队薪资多少？工资帽和奢侈税线在哪里？" → 调 `get_team_payroll(GSW)` + `get_salary_cap_info(2025-26)`，自动比对得出"勇士薪资 $208,824,825 已超过 Second Apron $207,824,000"。
  - "Apron 二轨触发会有哪些限制？另外现在全额中产是多少钱？" → 给出 Non-Taxpayer MLE = $14,104,000 + Apron 一/二轨各级限制（硬上限/MLE 类型/聚合薪资/首轮签冻结等）。

### 阶段 3：拆分为 Supervisor 多 Agent（LangGraph 正式形态） ✅

正式形态已建好——单 Agent 拆成 4 个职责清晰的 sub-agent + 1 个 Supervisor + 1 个 Finalize 节点，
LangGraph 用 `conditional_edges` 按 supervisor 输出的 plan 顺序串行调度。

- [x] `prompts/_common.py`：抽取共用片段（时区锚点、球员名翻译、硬约束）。
- [x] `prompts/supervisor.py`：Supervisor 提示词（含 4 个子 Agent 职责说明 + JSON 输出 schema + 典型分类示例）。
- [x] `prompts/sub_agents.py`：4 个 sub-agent 提示词工厂（动态注入当前日期）。
- [x] `agents/state.py`：NBAState 加 `plan / plan_reasoning / facts / visited` + 两个自定义 reducer
   - `_merge_dicts`：facts 增量节点 return 单 key 时 merge，supervisor 用 `{"__reset__": True}` 重置。
   - `_replace_list`：visited 由节点显式拼接（read-then-append），supervisor 用 `[]` 重置。
- [x] `agents/supervisor.py`：意图分类 + plan 生成；含容错 JSON 解析（兼容 ```json``` 包裹）；analysis 自动调序到最后。
- [x] `agents/sub_agents.py`：`_make_react_subagent` 工厂：用 `create_react_agent` 包装 DATA_TOOLS / NEWS_TOOLS / SALARY_TOOLS+RAG_TOOLS；每个节点把 facts 写入 `state.facts[name]`，把自己 append 到 `visited`。
- [x] `agents/sub_agents.py::_analysis_agent_node`：AnalysisAgent **不挂工具**，纯 LLM 读 `state.facts` 写分析；上下文里没有 facts 时如实说明缺数据。
- [x] `agents/finalize.py`：拼接所有 sub-agent 的 facts，让 LLM 整合输出一条干净的最终回答；空 facts 时给兜底文案。
- [x] `graph.py`：用 supervisor + 4 子 Agent + finalize 6 个节点；`route_next` 看 `(plan, visited)` 串行跳；`conditional_edges` 让每个 sub-agent 节点跑完后都回到 router 再决定下一跳；plan 跑完跳 finalize。
- [x] 端到端验证（共用单 graph 实例跑 4 个 case，全部通过）：
   - **纯薪资** `["salary"]` 60s：工资帽 + 奢侈税 + Apron 一/二轨 + 全额中产，规则提示完整。
   - **纯数据** `["data"]` 57s：湖人近 5 场战绩 1 胜 4 负，4 连败完整呈现。
   - **混合 (data+salary)** 184s：勇士战绩 + 全队薪资 + 核心球员合同明细同屏整合；SalaryAgent 收到 `prior_facts_keys=['data']` 说明 facts 跨 Agent 传递成功。
   - **带分析 (data+analysis)** 240s：DataAgent 给出东契奇/约基奇场均数据 → AnalysisAgent 不挂工具基于 facts 给出"得分单维 vs 进攻全面性"两个维度的判断 + 数据驱动结论。

### 阶段 4：分析能力（项目亮点） ✅

5 大高阶能力（球员对比 / 球队对比 / 战术分析 / 交易评估 / 比赛预测）都通过"**1 个新数据工具 + AnalysisAgent prompt 模板化**"实现——不新增独立 `compare_players` / `evaluate_trade` 等专用工具，因为它们本质都是"取数 → 分析"的组合，让 Supervisor 路由 + AnalysisAgent 模板就够了。

- [x] **新工具** `get_team_advanced_stats`：BBRef 联赛级 `advanced-team` 表，含 Pace / ORtg / DRtg / NRtg / TS% / FTr / 3PAr + 进攻四要素 + 防守四要素，**每项附联盟排名**（区分越高越好 vs 越低越好 vs 中性）。
- [x] **强化 AnalysisAgent prompt**：增加 5 大场景子模板，每个模板明确规定输出结构（事实表 + 维度判断 + 综合定性）；明确要求"胜率区间"而非绝对预测，要求引用具体数字而不能编造。
- [x] **强化 Supervisor prompt**：按"简单取数 / 多 Agent 取数 / 5 大高阶分析"三类组织路由示例；含 analysis 时强制前面至少有一个取数 Agent。
- [x] **强化 DataAgent prompt**：场景驱动的工具组合——战术分析必调 `get_team_advanced_stats`、球队对比双方都调、比赛预测同时调 schedule + advanced。
- [x] `llm_timeout` 从 60s 调到 180s（交易评估这类深 ReAct 链 LLM 推理时间偏长）。
- [x] 端到端验证：4 类高阶 query 全部通过——
   - **战术分析** "雷霆为什么防守强" `[data, analysis]` 124s：DRtg #1 + Def-eFG% #2 + Def-TOV% #2，定性"高节奏均衡压迫式防守"。
   - **球队对比** "雷霆 vs 马刺谁更均衡" `[data, analysis]` 114s：双方攻防排名差距+四要素对比，结论"马刺更均衡（无极端短板）"。
   - **比赛预测** "OKC vs Lakers" `[data, news, analysis]` 244s：双方战绩 + 伤病 + 风格碰撞 → 雷霆 85-90% 胜率 / 比分预测 118-105。
   - **交易评估** "Reaves+Hachimura ↔ Murphy III" `[data, salary, analysis]` 721s：薪资合规验证（湖人 between aprons 接收上限 100%）+ BYC 判断 + 湖人/鹈鹕双视角各 4 条评估。

### 阶段 5：体验与工程化

- [ ] CLI：`python -m nba_agent.main "湖人最近怎么样？"`，支持多轮（`thread_id` 复用）。
- [ ] 流式：`graph.astream_events()` 把 `finalize` 节点的 token 实时回吐。
- [ ] `pytest` 覆盖：工具层、Supervisor 路由分类、CBA RAG 检索召回。
- [ ] 可选：FastAPI + 简单 Web 前端。

---

## 8. 关键设计约束（务必遵守）

1. **事实必须出处可查**：任何涉及数字（得分、薪资、胜率）必须来自工具返回值，CBA 规则必须带 `query_cba_rule` 返回的条款引用；`finalize` 节点会校验 `facts/citations`，缺失出处则要求子 Agent 重答。
2. **AnalysisAgent 不能直接调外部工具**：它只读 `state.facts`，保持"分析"与"取数"解耦。
3. **function-calling 优先**：全部走 LangGraph `create_react_agent` 的 function-calling，禁止再用脆弱的文本/JSON 字符串解析。
4. **每个工具有缓存键**：`(tool_name, args_hash, date_bucket)` 作 key，控制对外请求量；CBA RAG 检索结果也缓存。
5. **失败优雅降级**：工具失败返回 `{"error": "...", "retryable": bool}`，Agent 应换工具或如实告知用户，禁止死循环（依赖 LangGraph 的 `recursion_limit` 兜底）。
6. **CBA RAG 引用强制**：`SalaryAgent` 涉及规则类回答时，必须把至少一条 `passage` 的原文 + (Article/Section/Page) 透传到 `state.citations`。

---

## 9. 立即可开工的下一步（阶段 0 的第一个 PR 范围）

1. 建好 §5 的目录骨架（含 `data/cba/`、`nba_agent/rag/cba/`）。
2. 写 `requirements.txt`：
   - 基础：`python-dotenv, pydantic, pydantic-settings, loguru, diskcache, pytest`
   - LangGraph：`langgraph, langgraph-checkpoint-sqlite, langchain-core, langchain-openai, langchain-text-splitters`
   - NBA：`nba_api, tavily-python, requests, beautifulsoup4`
   - RAG：`pdfplumber, chromadb`（embedding 模型按 §6 的选型再补）
3. 完成 §7 阶段 0 全部 checkbox：LangGraph 最小图（supervisor → single_agent → finalize）能跑通"湖人最近怎么样？"并保留多轮上下文。
4. 提醒用户：去 NBPA 官网下载 2023 CBA PDF（约 600 页）放到 `data/cba/2023_cba.pdf`，阶段 2 会用到。

> 每完成一个阶段，回到本文件勾选 checkbox，并把架构演变记入文档底部"变更日志"。

---

## 变更日志

- v0.1（初版）：完成现状梳理与目标架构设计，确定 5 阶段路线图。
- v0.2：编排层从自研 ReAct 切换到 **LangGraph**（`StateGraph` + `create_react_agent` + `SqliteSaver`）；新增 **CBA RAG** 模块（`pdfplumber` + Chroma + `query_cba_rule` 工具，挂在 `SalaryAgent` 名下）；同步更新目录结构、技术选型与路线图。
- v0.3：完成**阶段 0** 与**阶段 1**——LangGraph 最小图能跑通、basketball-reference 全套数据工具上线、时区与硬约束完善（不再有数据陈旧/幻觉问题）。
- v0.4：完成**阶段 2**——CBA RAG 入库 1944 chunks 全流程跑通（HF embedding + Chroma + MMR）、薪资工具改用 HoopsHype（Spotrac 被 Cloudflare 拦）、新增 4 个薪资工具（`get_team_payroll / get_player_salary / get_salary_cap_info / validate_trade`），单 Agent 已能完成"薪资数字 + CBA 条款"的组合回答。
- v0.5：完成**阶段 3**——单 Agent 升级为 **Supervisor 多 Agent**：Supervisor LLM 输出 plan JSON → router 按 plan 串行调度 DataAgent / NewsAgent / SalaryAgent / AnalysisAgent → Finalize 整合输出。State 引入自定义 reducer (`_merge_dicts` + `_replace_list`) 支持每轮重置 facts/visited；AnalysisAgent 严格不挂工具、只读前置 facts，与"取数 Agent"解耦。删除遗留的 `SINGLE_AGENT_PROMPT` / `single_agent.py`。4 类典型场景（纯数据/纯薪资/混合/带分析）全部跑通。
- v0.6：完成**阶段 4**——新增 `get_team_advanced_stats` 工具（联赛级球队高阶数据 + 联盟排名，正确处理"越低越好/越高越好/中性"的指标方向），强化 AnalysisAgent prompt 加入 5 大场景子模板，强化 Supervisor 高阶分类示例，强化 DataAgent 场景驱动工具组合。`llm_timeout` 60→180s 应对深 ReAct 链。4 类高阶 query（战术分析 / 球队对比 / 比赛预测 / 交易评估）全部跑通，交易评估能给出双视角薪资合规 + BYC 判断 + 球员对位三维评估。
