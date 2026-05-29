"""中英文 → bbref / nba_api 标识符 解析器。

- 球队：中文常用名/英文全名/缩写 → bbref 3 字母 abbreviation
- 球员：中英文常见球星 → 英文全名（再由 _bbref.lookup_player_path 走 bbref 搜索拿真实 URL）
"""
from __future__ import annotations

from nba_api.stats.static import players as _nba_players
from nba_api.stats.static import teams as _nba_teams


# nba_api 缩写 → bbref 缩写 的不一致映射
_NBA_TO_BBREF_ABBR = {
    "BKN": "BRK",   # 篮网
    "CHA": "CHO",   # 黄蜂
    "PHX": "PHO",   # 太阳
}


# 中文球队名 → nba_api 3 字母缩写
_TEAM_CN: dict[str, str] = {
    "湖人": "LAL", "洛杉矶湖人": "LAL",
    "凯尔特人": "BOS", "波士顿凯尔特人": "BOS", "绿军": "BOS",
    "勇士": "GSW", "金州勇士": "GSW",
    "雷霆": "OKC", "俄克拉荷马雷霆": "OKC",
    "掘金": "DEN", "丹佛掘金": "DEN",
    "热火": "MIA", "迈阿密热火": "MIA",
    "公牛": "CHI", "芝加哥公牛": "CHI",
    "尼克斯": "NYK", "纽约尼克斯": "NYK",
    "篮网": "BKN", "布鲁克林篮网": "BKN",
    "76人": "PHI", "费城76人": "PHI",
    "猛龙": "TOR", "多伦多猛龙": "TOR",
    "雄鹿": "MIL", "密尔沃基雄鹿": "MIL",
    "骑士": "CLE", "克利夫兰骑士": "CLE",
    "活塞": "DET", "底特律活塞": "DET",
    "魔术": "ORL", "奥兰多魔术": "ORL",
    "步行者": "IND", "印第安纳步行者": "IND",
    "老鹰": "ATL", "亚特兰大老鹰": "ATL",
    "黄蜂": "CHA", "夏洛特黄蜂": "CHA",
    "奇才": "WAS", "华盛顿奇才": "WAS",
    "马刺": "SAS", "圣安东尼奥马刺": "SAS",
    "鹈鹕": "NOP", "新奥尔良鹈鹕": "NOP",
    "灰熊": "MEM", "孟菲斯灰熊": "MEM",
    "火箭": "HOU", "休斯顿火箭": "HOU",
    "独行侠": "DAL", "达拉斯独行侠": "DAL", "小牛": "DAL",
    "国王": "SAC", "萨克拉门托国王": "SAC",
    "森林狼": "MIN", "明尼苏达森林狼": "MIN",
    "开拓者": "POR", "波特兰开拓者": "POR",
    "太阳": "PHX", "菲尼克斯太阳": "PHX",
    "爵士": "UTA", "犹他爵士": "UTA",
    "快船": "LAC", "洛杉矶快船": "LAC",
}


def resolve_team(name_or_abbr: str) -> dict | None:
    """把"湖人 / Lakers / Los Angeles Lakers / LAL"等任意写法转成统一对象。

    返回：{"nba_abbr": "LAL", "bbref_abbr": "LAL", "full_name": "Los Angeles Lakers", "id": 1610612747}
    找不到返回 None。
    """
    if not name_or_abbr:
        return None

    s = name_or_abbr.strip()

    nba_abbr: str | None = None
    if s in _TEAM_CN:
        nba_abbr = _TEAM_CN[s]

    if nba_abbr is None and len(s) == 3 and s.isalpha() and s.isupper():
        if _nba_teams.find_team_by_abbreviation(s):
            nba_abbr = s

    if nba_abbr is None:
        hits = _nba_teams.find_teams_by_full_name(s)
        if hits:
            nba_abbr = hits[0]["abbreviation"]

    if nba_abbr is None:
        hits = [t for t in _nba_teams.get_teams() if s.lower() in t["nickname"].lower()]
        if hits:
            nba_abbr = hits[0]["abbreviation"]

    if nba_abbr is None:
        return None

    team = _nba_teams.find_team_by_abbreviation(nba_abbr)
    return {
        "nba_abbr": nba_abbr,
        "bbref_abbr": _NBA_TO_BBREF_ABBR.get(nba_abbr, nba_abbr),
        "full_name": team["full_name"],
        "id": team["id"],
        "city": team["city"],
        "nickname": team["nickname"],
    }


# 中文/简写球员名 → 英文全名
_PLAYER_CN: dict[str, str] = {
    "詹姆斯": "LeBron James", "勒布朗·詹姆斯": "LeBron James", "勒布朗": "LeBron James",
    "库里": "Stephen Curry", "斯蒂芬·库里": "Stephen Curry",
    "杜兰特": "Kevin Durant", "凯文·杜兰特": "Kevin Durant", "KD": "Kevin Durant",
    "字母哥": "Giannis Antetokounmpo",
    "约基奇": "Nikola Jokic", "尼古拉·约基奇": "Nikola Jokic",
    "东契奇": "Luka Doncic", "卢卡·东契奇": "Luka Doncic",
    "塔图姆": "Jayson Tatum",
    "亚历山大": "Shai Gilgeous-Alexander", "SGA": "Shai Gilgeous-Alexander",
    "莫兰特": "Ja Morant",
    "爱德华兹": "Anthony Edwards",
    "恩比德": "Joel Embiid",
    "哈登": "James Harden",
    "威少": "Russell Westbrook", "威斯布鲁克": "Russell Westbrook",
    "保罗": "Chris Paul",
    "欧文": "Kyrie Irving", "凯里·欧文": "Kyrie Irving",
    "利拉德": "Damian Lillard",
    "戴维斯": "Anthony Davis", "浓眉": "Anthony Davis",
    "锡安": "Zion Williamson",
    "巴特勒": "Jimmy Butler",
    "字母弟": "Thanasis Antetokounmpo",
    "霍勒迪": "Jrue Holiday",
    "布克": "Devin Booker",
    "拉塞尔": "D'Angelo Russell",
    "里夫斯": "Austin Reaves",
    "雷迪克": "JJ Redick",
}


def resolve_player_name(name: str) -> str:
    """把中文 / 简写 / 英文姓 转为英文全名。

    - "詹姆斯" → "LeBron James"
    - "LeBron James" → "LeBron James"（原样返回）
    - 在 _PLAYER_CN 表里命中则用映射；否则原样返回让 nba_api 静态库自己匹配。
    """
    if not name:
        return name
    s = name.strip()
    if s in _PLAYER_CN:
        return _PLAYER_CN[s]
    return s


def resolve_player(name: str) -> dict | None:
    """把球员名解析成 {full_name, id, first_name, last_name, is_active}。

    流程：中文映射 → nba_api.players 全文搜索。
    """
    full = resolve_player_name(name)
    hits = _nba_players.find_players_by_full_name(full)
    if not hits:
        parts = full.split()
        if len(parts) >= 2:
            hits = _nba_players.find_players_by_full_name(f"{parts[0]} {parts[-1]}")
    if not hits:
        return None
    p = hits[0]
    return {
        "full_name": p["full_name"],
        "id": p["id"],
        "first_name": p["first_name"],
        "last_name": p["last_name"],
        "is_active": p["is_active"],
    }
