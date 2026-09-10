"""把 TDX `Live/News/Highway` 的自由文字公告解析成結構化事件欄位。

TDX 的 News DTO 沒有座標、沒有里程、沒有路名欄位（見 research/2026-09-10-tdx-probe.md §3），
台18/台21 與 `132K+300` 這類樁號只以自由文字嵌在 Title / Description 裡，
所以這裡全部靠正則解析。解析寬鬆：抓不到就記進 `parse_warnings[]`，不丟事件。

對外只有一支純函式：
    parse(item: dict) -> dict | None      # 非台18/台21 回 None
"""

from __future__ import annotations

import datetime as _dt
import re

from roadgeom import format_km, parse_km

# --- 路名 -----------------------------------------------------------------

# 路名變體：台/臺 + 可有空白 + 18/21 + 可有「線」。實例：「台18線」「臺 21 線」「台２１線」
ROAD_PATTERNS = [
    ("台18線", re.compile(r"[台臺]\s*18\s*線?")),
    ("台21線", re.compile(r"[台臺]\s*21\s*線?")),
]

# 全形數字 → 半形（實例：「台２１線」→「台21線」）
_FULLWIDTH = str.maketrans("０１２３４５６７８９ＫＫ：＋～－", "0123456789KK:+~-")

# 需要排除的近似路名（避免「台21甲線」誤判成台21線本線）。實例：「台21甲線」
EXCLUDE_NEAR = re.compile(r"[台臺]\s*(?:18|21)\s*[甲乙丙丁]")


def normalize(text: str) -> str:
    if not text:
        return ""
    return text.translate(_FULLWIDTH)


def detect_road(text: str) -> str | None:
    """回傳 `台18線` / `台21線` / None。同時命中兩者時取先出現的。"""
    t = normalize(text)
    hits = []
    for name, pat in ROAD_PATTERNS:
        for m in pat.finditer(t):
            # 「台21甲線」不算台21線本線
            if EXCLUDE_NEAR.match(t, m.start()):
                continue
            hits.append((m.start(), name))
    if not hits:
        return None
    hits.sort()
    return hits[0][1]


# --- 里程 -----------------------------------------------------------------

# 里程樁號序列。實例：「132K+300」「70K」「43.1K」「42K 至 43K+200」
MILEPOST_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*[Kk]\s*(?:\+\s*(\d{1,3}))?")

# 子句切分：里程通常與路名同一子句。實例：「台21線雙向39K+420埔里路段，自115年…」
CLAUSE_SPLIT = re.compile(r"[，。；、\n]")


def _milepost_meters(m: re.Match) -> int:
    return parse_km(f"{m.group(1)}K" + (f"+{m.group(2)}" if m.group(2) else ""))


def extract_mileage(text: str, road: str, warnings: list) -> tuple[int | None, int | None]:
    """取 (from_m, to_m)，單位公尺。只有一個里程 → to = from（點事件）。

    先只看「含該路名的子句」，避免混合公告誤取別條路的里程
    （實例 NewsID 78599：「台14線東向57K+400至57K+800…、台21線雙向39K+420埔里路段」）。
    子句裡找不到才退回全文掃描並記 warning。
    """
    t = normalize(text)
    pat = dict(ROAD_PATTERNS)[road]

    candidates = []
    for clause in CLAUSE_SPLIT.split(t):
        if pat.search(clause):
            found = [_milepost_meters(m) for m in MILEPOST_RE.finditer(clause)]
            if found:
                candidates = found
                break

    if not candidates:
        found = [_milepost_meters(m) for m in MILEPOST_RE.finditer(t)]
        if found:
            warnings.append("里程不在含路名的子句內，改用全文第一組里程（可能取到鄰近路線）")
            candidates = found

    if not candidates:
        warnings.append("解析不到里程樁號")
        return None, None
    if len(candidates) == 1:
        return candidates[0], candidates[0]
    return candidates[0], candidates[1]


# --- 方向 -----------------------------------------------------------------

# 實例：「台21線雙向132K+300…」「台21線北上30K+735至30K+367」「台18線西向35K+800」
BIDIR_RE = re.compile(r"雙向")


def detect_direction(text: str, from_m, to_m) -> str:
    """台18/台21 里程皆自平地往山上遞增，因此 from<to 視為往山上。"""
    t = normalize(text)
    if BIDIR_RE.search(t):
        return "雙向"
    if from_m is None or to_m is None or from_m == to_m:
        return ""
    return "往山上" if from_m < to_m else "往山下"


# --- 時段規則 --------------------------------------------------------------

_TIME = r"(?:(上午|下午|凌晨)\s*)?(\d{1,2})\s*(?:[:：]\s*(\d{1,2})|時\s*(?:(\d{1,2})\s*分)?)"

# 每日時段區間。實例：「每日8時起至17時止」「每日7時至17時」「每日17:30~翌日7:00」
DAILY_RANGE_RE = re.compile(
    r"每\s*[日天]\s*" + _TIME + r"\s*(?:起)?\s*(?:至|到|~|-|～)\s*(?:翌日|隔日|次日)?\s*" + _TIME
)

# 放行原文。實例：「每整點放行10分鐘」「整點放行10分鐘」「每20分鐘後放行1次」「每施工20分鐘後放行1次」
RELEASE_NOTE_RE = re.compile(r"(?:每|採)?\s*(?:整點|半點|施工\s*\d+\s*分鐘後|\d+\s*分鐘後)?\s*放行\s*\d*\s*(?:分鐘|次)?")

CLOSED_RE = re.compile(r"封閉|禁止通行|全線封閉|不得通行")
RELEASE_RE = re.compile(r"放行")
# 單線雙向這類「可通行但受管制」原文。實例：「採單線雙向管制通行」「依現況單線機動管制」
CONTROLLED_PASS_RE = re.compile(r"單線[^，。]{0,6}管制通行|機動管制|管制通行")


def _to_hhmm(mark, hh, mm1, mm2) -> str:
    h = int(hh)
    m = int(mm1 or mm2 or 0)
    if mark == "下午" and h < 12:
        h += 12
    if mark == "凌晨" and h == 12:
        h = 0
    h = h % 24
    return f"{h:02d}:{m:02d}"


def extract_rules(text: str) -> tuple[list, str]:
    """回傳 (rules[], schedule 文字)。無「每日/每天」時段者回 ([], "")。"""
    t = normalize(text)
    rules = []
    m = DAILY_RANGE_RE.search(t)
    if not m:
        return [], ""
    g = m.groups()
    start = _to_hhmm(g[0], g[1], g[2], g[3])
    end = _to_hhmm(g[4], g[5], g[6], g[7])

    note = ""
    if RELEASE_RE.search(t):
        effect = "release"
        rm = RELEASE_NOTE_RE.search(t)
        note = rm.group(0).strip() if rm else "定時放行"
    elif CLOSED_RE.search(t):
        effect = "closed"
    elif CONTROLLED_PASS_RE.search(t):
        # 單線雙向／機動管制：可通行但受管制，效果歸類為 release，原文留在 note
        effect = "release"
        cm = CONTROLLED_PASS_RE.search(t)
        note = cm.group(0).strip() if cm else ""
    else:
        # 只有施工時段、沒有封閉也沒有放行／管制通行字樣（實例 NewsID 78486
        # 「每日8時至17時，路段多有工程車輛出入…減速慢行」）：不產生 rules，
        # 免得前端把單純的施工時段誤判成「封閉中」；時段仍留在 schedule 文字。
        return [], f"每日 {start}–{end}（施工時段）"

    rules.append({"days": "daily", "from": start, "to": end, "effect": effect, "note": note})
    schedule = f"每日 {start}–{end}" + (f"，{note}" if note else "")
    return rules, schedule


# --- 日期 -----------------------------------------------------------------

# 民國年月日。實例：「115年1月20日」「114年11月10日」
ROC_YMD_RE = re.compile(r"(?<!\d)(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 西元年月日。實例：「2026年1月20日」
AD_YMD_RE = re.compile(r"(?<!\d)(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 斜線／連字號格式。實例：「115/1/20」「2026-01-20」
SLASH_RE = re.compile(r"(?<!\d)(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})(?!\d)")


def _mk_date(y: int, mo: int, d: int) -> str | None:
    if y < 1911:
        y += 1911  # 民國 → 西元
    try:
        return _dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def extract_dates(text: str, warnings: list) -> tuple[str, str]:
    """依出現順序取前兩個日期為 start / end；只有一個 → start = end。"""
    t = normalize(text)
    found = []
    for rx in (ROC_YMD_RE, AD_YMD_RE, SLASH_RE):
        for m in rx.finditer(t):
            iso = _mk_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if iso:
                found.append((m.start(), iso))
    if not found:
        warnings.append("解析不到日期")
        return "", ""
    found.sort()
    seen, dates = set(), []
    for _, iso in found:
        if iso not in seen:
            seen.add(iso)
            dates.append(iso)
    if len(dates) == 1:
        return dates[0], dates[0]
    return dates[0], dates[1]


# --- type / status ---------------------------------------------------------

# 時段管制關鍵字。實例：「整點放行10分鐘管制」「管制時段」
TIMED_RE = re.compile(r"放行|管制時段|時段管制")


def detect_type(text: str, rules: list) -> str:
    """放行優先於封閉：132K+300 那筆同時有「封閉」與「整點放行」，屬時段管制（SPEC §8c）。"""
    t = normalize(text)
    if TIMED_RE.search(t):
        return "timed"
    if CLOSED_RE.search(t):
        return "closure"
    if rules:
        return "timed"
    return "construction"


def detect_status(start_date: str, end_date: str, today: _dt.date | None = None) -> str:
    today = today or _dt.date.today()
    if not start_date and not end_date:
        return "active"
    s = _dt.date.fromisoformat(start_date) if start_date else None
    e = _dt.date.fromisoformat(end_date) if end_date else None
    if s and today < s:
        return "scheduled"
    if e and today > e:
        return "ended"
    return "active"


# --- 主函式 ---------------------------------------------------------------

TDX_SOURCE_NAME = "公路局即時路況快訊（TDX）"
# TDX News DTO 多數沒有 NewsURL（實測 196 筆全部為空），退回公路局即時路況官網首頁，不編造深連結。
TDX_FALLBACK_URL = "https://168.thb.gov.tw/"


def parse(item: dict, today: _dt.date | None = None) -> dict | None:
    """單筆 TDX News → events properties（不含 id / fetched_at / geometry）。

    非台18/台21 回 None。
    """
    title = (item.get("Title") or "").strip()
    desc = (item.get("Description") or "").strip()
    text = f"{title}\n{desc}"

    road = detect_road(text)
    if road is None:
        return None

    warnings: list = []
    from_m, to_m = extract_mileage(text, road, warnings)
    rules, schedule = extract_rules(text)
    start_date, end_date = extract_dates(text, warnings)

    # TDX 自帶的 StartTime/EndTime 若有值就優先（實測樣本皆為 None，留作線上資料的退路）
    for key, target in (("StartTime", "start"), ("EndTime", "end")):
        raw = item.get(key)
        if raw:
            try:
                iso = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
                if target == "start":
                    start_date = iso
                else:
                    end_date = iso
            except ValueError:
                warnings.append(f"{key} 格式無法解析：{raw[:24]}")

    ev_type = detect_type(text, rules)
    status = detect_status(start_date, end_date, today)

    summary = desc.split("，")[0] if desc else title
    if len(summary) > 60:
        summary = summary[:60] + "…"

    return {
        "source": "tdx",
        "source_id": str(item.get("NewsID") or ""),
        "road": road,
        "direction": detect_direction(text, from_m, to_m),
        "from_km": format_km(from_m),
        "to_km": format_km(to_m),
        "from_m": from_m,
        "to_m": to_m,
        "type": ev_type,
        "status": status,
        "title": title,
        "summary": summary,
        "description": desc,
        "schedule": schedule,
        "rules": rules,
        "start_date": start_date,
        "end_date": end_date,
        "source_name": TDX_SOURCE_NAME,
        "source_url": (item.get("NewsURL") or "").strip() or TDX_FALLBACK_URL,
        "news_category": item.get("NewsCategory"),
        "parse_warnings": warnings,
    }
