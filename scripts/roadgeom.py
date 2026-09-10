"""里程 → 幾何：在省道里程折線上內插點與子段。

資料源：`site/data/roads/tw18.geojson`、`tw21.geojson`
（單一 LineString，`properties.mileage_m` 為每頂點累積里程公尺，每 100 m 一點，
 由 `scripts/build_roads.py` 產生，見 `scripts/roads_calibration.md`）。

對外 API：
    load_road("台18線") -> Road
    parse_km("118K+500") -> 118500
    point_at(road, m) -> [lon, lat]
    segment(road, m_from, m_to) -> (coords, warnings)

所有座標輸出四捨五入到小數 6 位（與 roads geojson 一致）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROADS_DIR = ROOT / "site" / "data" / "roads"

# 路名 → roads geojson 檔名
ROAD_FILES = {
    "台18線": "tw18.geojson",
    "台21線": "tw21.geojson",
}

COORD_NDIGITS = 6

# 點事件（只有一個里程）向前後各延伸的長度，公尺
POINT_HALF_SPAN_M = 100


class Road:
    """一條省道的里程折線。"""

    def __init__(self, name: str, coords: list, mileage_m: list, props: dict):
        self.name = name
        self.coords = coords          # [[lon, lat], ...]
        self.mileage_m = mileage_m    # 與 coords 等長的累積里程（遞增）
        self.props = props
        self.start_m = mileage_m[0]
        self.end_m = mileage_m[-1]

    def __repr__(self):
        return f"<Road {self.name} {self.start_m}-{self.end_m}m pts={len(self.coords)}>"


_ROAD_CACHE: dict = {}


def load_road(road_name: str) -> Road | None:
    """載入 roads geojson；未知路名回 None。結果快取。"""
    if road_name in _ROAD_CACHE:
        return _ROAD_CACHE[road_name]
    fname = ROAD_FILES.get(road_name)
    if not fname:
        return None
    path = ROADS_DIR / fname
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        gj = json.load(f)
    feat = gj["features"][0]
    coords = feat["geometry"]["coordinates"]
    mileage = feat["properties"]["mileage_m"]
    if len(coords) != len(mileage):
        raise ValueError(f"{path}: coordinates 與 mileage_m 長度不符")
    road = Road(road_name, coords, mileage, feat["properties"])
    _ROAD_CACHE[road_name] = road
    return road


# 里程樁號字串 → 公尺。實例：「118K+500」→118500、「70K」→70000、「43.1K」→43100
_KM_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*[KkＫ]\s*(?:\+\s*(\d{1,3}))?\s*$")


def parse_km(text: str) -> int | None:
    """把樁號字串轉成公尺。無法解析回 None。

    例：parse_km("118K+500") == 118500；parse_km("70K") == 70000
    """
    if text is None:
        return None
    m = _KM_RE.match(str(text))
    if not m:
        return None
    km = float(m.group(1))
    meters = int(round(km * 1000))
    if m.group(2):
        # 「+500」補到三位（「+5」視為 +500? 官方樁號一律三位，這裡照原文位數補右零）
        frac = m.group(2)
        meters += int(frac.ljust(3, "0"))
    return meters


def format_km(meters: int | None) -> str:
    """公尺 → 官方樁號字串。實例：118500 -> "118K+500"。"""
    if meters is None:
        return ""
    meters = int(round(meters))
    return f"{meters // 1000}K+{meters % 1000:03d}"


def _clamp(road: Road, m: float, warnings: list, label: str) -> float:
    if m < road.start_m:
        warnings.append(
            f"里程 {format_km(m)} 小於 {road.name} 折線起點 {format_km(road.start_m)}，已 clamp（{label}）"
        )
        return float(road.start_m)
    if m > road.end_m:
        warnings.append(
            f"里程 {format_km(m)} 超過 {road.name} 折線終點 {format_km(road.end_m)}，已 clamp（{label}）"
        )
        return float(road.end_m)
    return float(m)


def _locate(road: Road, m: float) -> tuple[int, float]:
    """回傳 (區間左端 index i, 該區間內比例 t)，使 m 落在 mileage[i]..mileage[i+1]。"""
    mil = road.mileage_m
    lo, hi = 0, len(mil) - 1
    if m <= mil[0]:
        return 0, 0.0
    if m >= mil[-1]:
        return len(mil) - 2, 1.0
    # 二分找最後一個 mil[i] <= m
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if mil[mid] <= m:
            lo = mid
        else:
            hi = mid - 1
    i = min(lo, len(mil) - 2)
    span = mil[i + 1] - mil[i]
    t = 0.0 if span == 0 else (m - mil[i]) / span
    return i, t


def _interp(road: Road, m: float) -> list:
    i, t = _locate(road, m)
    (x0, y0), (x1, y1) = road.coords[i], road.coords[i + 1]
    return [
        round(x0 + (x1 - x0) * t, COORD_NDIGITS),
        round(y0 + (y1 - y0) * t, COORD_NDIGITS),
    ]


def point_at(road: Road, m: float) -> tuple[list, list]:
    """里程（公尺）→ [lon, lat]（線性內插）。回傳 (coord, warnings)。"""
    warnings: list = []
    mm = _clamp(road, m, warnings, "point_at")
    return _interp(road, mm), warnings


def segment(road: Road, m_from: float, m_to: float) -> tuple[list, list]:
    """沿線取 m_from → m_to 的子段座標（含兩端內插點）。

    方向依 from<to：from>to 時輸出反序（例如「北上30K+735至30K+367」）。
    m_from == m_to 時自動展成前後各 POINT_HALF_SPAN_M 的短段。
    回傳 (coords, warnings)；coords 至少兩點。
    """
    warnings: list = []
    if m_from is None or m_to is None:
        return [], ["缺少里程，無法產生幾何"]

    reverse = m_from > m_to
    a, b = (m_to, m_from) if reverse else (m_from, m_to)

    if a == b:
        a = a - POINT_HALF_SPAN_M
        b = b + POINT_HALF_SPAN_M

    a = _clamp(road, a, warnings, "segment 起點")
    b = _clamp(road, b, warnings, "segment 終點")
    if a == b:  # clamp 後退化（整段都在折線範圍外）
        a = max(road.start_m, a - POINT_HALF_SPAN_M)
        b = min(road.end_m, b + POINT_HALF_SPAN_M)

    coords = [_interp(road, a)]
    ia, _ = _locate(road, a)
    ib, _ = _locate(road, b)
    for i in range(ia + 1, ib + 1):
        if road.mileage_m[i] <= a or road.mileage_m[i] >= b:
            continue
        c = road.coords[i]
        coords.append([round(c[0], COORD_NDIGITS), round(c[1], COORD_NDIGITS)])
    end = _interp(road, b)
    if end != coords[-1]:
        coords.append(end)
    if len(coords) < 2:  # 極端退化，複製一點確保是合法 LineString
        coords.append(list(coords[0]))

    if reverse:
        coords.reverse()
    return coords, warnings


def line_string(road_name: str, m_from, m_to) -> tuple[dict | None, list]:
    """便利函式：路名 + 起訖里程（公尺）→ GeoJSON LineString。"""
    road = load_road(road_name)
    if road is None:
        return None, [f"未知路線 {road_name}，無法產生幾何"]
    if m_from is None and m_to is None:
        return None, ["公告解析不到里程，geometry 留 null"]
    if m_from is None:
        m_from = m_to
    if m_to is None:
        m_to = m_from
    coords, warnings = segment(road, m_from, m_to)
    if not coords:
        return None, warnings
    return {"type": "LineString", "coordinates": coords}, warnings
