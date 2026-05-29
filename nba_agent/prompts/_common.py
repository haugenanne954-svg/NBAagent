"""所有 Agent 共用的上下文片段（日期/时区/球员名翻译规范）。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_CN = ZoneInfo("Asia/Shanghai")


def current_season(today: datetime) -> tuple[str, int]:
    """返回 ("2025-26", 2026)。"""
    y = today.year + 1 if today.month >= 10 else today.year
    return f"{y - 1}-{str(y)[-2:]}", y


def time_anchor_block(now_utc: datetime | None = None) -> str:
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    cn_now = now_utc.astimezone(_CN)
    et_now = now_utc.astimezone(_ET)
    season_str, season_year = current_season(et_now)
    return (
        "【时间锚点（必须用以下时间，不要用训练知识）】\n"
        f"- 北京时间（用户视角）：{cn_now.strftime('%Y-%m-%d %H:%M (%A) %Z')}\n"
        f"- 美东时间 ET（NBA 排期用这个）：{et_now.strftime('%Y-%m-%d %H:%M (%A) %Z')}\n"
        f"- 当前 NBA 赛季：{season_str}（赛季末尾年份 = {season_year}，bbref / nba_api 用这个年份表示）\n"
        "\n"
        "【时区换算规则】\n"
        "- NBA 比赛按 ET 记录。用户用'今晚/昨晚/刚刚'时，先换算成 ET 日期再传给工具。\n"
        "- ET 凌晨~中午（即北京时间下午/晚上）时，'今天的比赛'通常指 ET 昨天（已经打完）。\n"
        "- 不确定就先试 ET yesterday，没找到再试 ET today。\n"
    )


PLAYER_NAME_RULES = """【球员名翻译规则】
- BBRef 数据源不识别中文，**必须把中文姓名翻译成英文全名再调工具**：
  - "詹姆斯" → "LeBron James"
  - "贾巴里·史密斯" / "小贾巴里" → "Jabari Smith Jr."
  - "杨瀚森" → "Yang Hansen"
  - "塔图姆" → "Jayson Tatum"
  - "东契奇" → "Luka Doncic"
  - "字母哥" → "Giannis Antetokounmpo"
  - "亚历山大" / "SGA" → "Shai Gilgeous-Alexander"
  - "克林根" → "Donovan Clingan"
- 含后缀（Jr./Sr./III）和连字符姓（Gilgeous-Alexander）的球员，**完整带上后缀和连字符**。
- 球队名传中文（"湖人"）或英文/缩写（"Lakers"/"LAL"）都可识别。
"""


HARD_CONSTRAINTS = """【硬约束】
- 工具返回 `{"error": ...}` 时，换工具或如实告诉用户；不要编造结果。
- 工具明确返回"没有比赛 / No games played"或"未检索到"时，**严禁编造**任何这天的比赛、对阵、比分。
- 涉及数字（比分、薪资、得分、胜率）**必须以工具返回为准**，严禁凭记忆。
"""
