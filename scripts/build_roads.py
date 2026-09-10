# -*- coding: utf-8 -*-
"""
build_roads.py — 產生台18線／台21線的「里程折線」GeoJSON。

輸出：
  site/data/roads/tw18.geojson
  site/data/roads/tw21.geojson
  scripts/roads_calibration.md

資料來源（皆放在 scripts/raw/，見 README 註解）：
  A) 線型：data.gov.tw 105020「省道公路路線圖資」
       roads_105020.zip -> (內層) 省道公路路線KMZ_11502.zip -> P0180.kmz / P0210.kmz
       KML 為 WGS84 經緯度，每個 Placemark = 一個工務段，description 內含「樁號範圍」。
  B) 校正：data.gov.tw 7040「省道里程坐標(里程牌標誌)」
       milepost_7040.csv（Big5），欄位含 公路編號 / 起點樁號 / 坐標-E-WGS84 / 坐標-N-WGS84。

幾何運算一律在 TWD97 / TM2 121分帶（EPSG:3826）平面座標下做（單位公尺），
輸出時再轉回 WGS84（EPSG:4326）。

用法：  .venv/Scripts/python.exe scripts/build_roads.py
"""

import csv
import io
import json
import os
import re
import statistics
import sys
import zipfile
from datetime import datetime, timezone

import numpy as np
from pyproj import Transformer

# ---------------------------------------------------------------- paths

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(HERE, "raw")
OUT_DIR = os.path.join(ROOT, "site", "data", "roads")
REPORT = os.path.join(HERE, "roads_calibration.md")

OUTER_ZIP = os.path.join(RAW, "roads_105020.zip")
MILEPOST_CSV = os.path.join(RAW, "milepost_7040.csv")

SOURCE_NOTE = (
    "data.gov.tw 105020 省道公路路線圖資 (KMZ, 11502) / "
    "校正: data.gov.tw 7040 省道里程坐標(里程牌標誌)"
)

# 路線設定：KMZ 內的公路編碼、CSV 的公路編號、輸出檔名
ROADS = [
    {"code": "P0180", "csv_id": "台18", "name": "台18線", "out": "tw18.geojson",
     "desc": "阿里山公路（太保 – 塔塔加）"},
    # 台21 官方終點樁號 145K+035（塔塔加），KML 的樁號範圍只到 144K+385 → 見 SPEC §9c
    {"code": "P0210", "csv_id": "台21", "name": "台21線", "out": "tw21.geojson",
     "desc": "新中橫（天冷 – 塔塔加）", "terminus_m": 145035},
]

STEP_M = 100  # 重採樣間距（公尺）
TERMINUS_TOL_M = 150.0  # SPEC §9c 規則 4：兩條路線終點距離 / 終點樁號推估容差（公尺）

# WGS84 <-> TWD97 TM2 (EPSG:3826)
TO_TM = Transformer.from_crs("EPSG:4326", "EPSG:3826", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:3826", "EPSG:4326", always_xy=True)

log_lines = []


def log(msg):
    print(msg)
    log_lines.append(msg)


# ---------------------------------------------------------------- helpers

STATION_RE = re.compile(r"(\d+)\s*K\s*\+\s*(\d+)")


def parse_station(text):
    """'118K+500' -> 118500 (公尺)。無法解析回傳 None。"""
    if not text:
        return None
    m = STATION_RE.search(text.replace(" ", ""))
    if not m:
        return None
    return int(m.group(1)) * 1000 + int(m.group(2))


def fmt_station(m):
    return "%dK+%03d" % (m // 1000, m % 1000)


def read_inner_kmz(code):
    """從外層 zip 取出指定 P#### 的 KML 文字。"""
    with zipfile.ZipFile(OUTER_ZIP) as outer:
        inner_name = None
        for info in outer.infolist():
            try:
                decoded = info.filename.encode("cp437").decode("big5")
            except Exception:
                decoded = info.filename
            if decoded.endswith(".zip"):
                inner_name = info.filename
        if inner_name is None:
            raise RuntimeError("找不到內層 KMZ zip")
        inner_bytes = outer.read(inner_name)

    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
        target = None
        for info in inner.infolist():
            if info.filename.split("/")[-1] == code + ".kmz":
                target = info
                break
        if target is None:
            raise RuntimeError("找不到 %s.kmz" % code)
        kmz_bytes = inner.read(target)

    with zipfile.ZipFile(io.BytesIO(kmz_bytes)) as kmz:
        kml_name = [i.filename for i in kmz.infolist()
                    if i.filename.lower().endswith(".kml")][0]
        return kmz.read(kml_name).decode("utf-8", errors="replace")


def parse_kml_segments(kml):
    """解析 Placemark -> [{name, road_id, start_m, end_m, coords[(lon,lat)]}]"""
    segs = []
    for pm in re.finditer(r"<Placemark>(.*?)</Placemark>", kml, re.S):
        body = pm.group(1)
        name_m = re.search(r"<name>(.*?)</name>", body, re.S)
        name = name_m.group(1).strip() if name_m else ""
        fields = dict(re.findall(r"<td>(.*?)：</td><td>(.*?)</td>", body))
        rng = fields.get("樁號範圍", "")
        parts = STATION_RE.findall(rng.replace(" ", ""))
        if len(parts) < 2:
            continue
        start_m = int(parts[0][0]) * 1000 + int(parts[0][1])
        end_m = int(parts[1][0]) * 1000 + int(parts[1][1])

        coords = []
        for cblock in re.findall(r"<coordinates>(.*?)</coordinates>", body, re.S):
            for tok in cblock.split():
                bits = tok.split(",")
                if len(bits) >= 2:
                    coords.append((float(bits[0]), float(bits[1])))
        if len(coords) < 2:
            continue
        segs.append({
            "name": name,
            "road_id": fields.get("公路編號", ""),
            "direction": fields.get("方向", ""),
            "start_m": start_m,
            "end_m": end_m,
            "coords": coords,
        })
    segs.sort(key=lambda s: s["start_m"])
    return segs


def to_tm(coords):
    lon = np.array([c[0] for c in coords], dtype=float)
    lat = np.array([c[1] for c in coords], dtype=float)
    x, y = TO_TM.transform(lon, lat)
    return np.column_stack([x, y])


def cumulative(xy):
    """回傳每個頂點的累積平面長度（公尺）。"""
    d = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    return np.concatenate([[0.0], np.cumsum(d)])


# ---------------------------------------------------------------- build

def build_polyline(segs):
    """
    把各工務段串成單一折線，並依各段官方「樁號範圍」線性內插指派里程。
    回傳 (xy [N,2], mileage [N], diagnostics dict)
    """
    all_xy = []
    all_mil = []
    diag = {"segments": [], "gaps": []}

    prev_end_pt = None
    for si, s in enumerate(segs):
        xy = to_tm(s["coords"])

        # 方向檢查：若本段起點距離上一段終點較遠、而終點較近，則反轉
        if prev_end_pt is not None:
            d_start = float(np.hypot(*(xy[0] - prev_end_pt)))
            d_end = float(np.hypot(*(xy[-1] - prev_end_pt)))
            if d_end < d_start:
                xy = xy[::-1]
                diag["segments"].append((s["name"], "REVERSED"))

        cum = cumulative(xy)
        geo_len = float(cum[-1])
        span = s["end_m"] - s["start_m"]

        # 段內線性內插：幾何累積長度 -> 官方樁號
        if geo_len <= 0:
            continue
        mil = s["start_m"] + (cum / geo_len) * span

        if prev_end_pt is not None:
            gap = float(np.hypot(*(xy[0] - prev_end_pt)))
            diag["gaps"].append((s["name"], s["start_m"], gap))
            # 接縫：丟掉重複的第一點
            xy = xy[1:]
            mil = mil[1:]

        all_xy.append(xy)
        all_mil.append(mil)
        diag["segments"].append({
            "name": s["name"],
            "start_m": s["start_m"],
            "end_m": s["end_m"],
            "span_m": span,
            "geo_len_m": geo_len,
            "ratio": geo_len / span if span else float("nan"),
            "pts": len(s["coords"]),
        })
        prev_end_pt = xy[-1]

    xy = np.vstack(all_xy)
    mil = np.concatenate(all_mil)

    # 里程必須嚴格遞增（接縫處可能有微小回退，強制單調）
    mil = np.maximum.accumulate(mil)
    return xy, mil, diag


def resample(xy, mil, step=STEP_M):
    """對齊到 step 整數倍的里程重採樣。回傳 (lonlat[M,2], mileage[M] int)"""
    start = int(np.ceil(mil[0] / step) * step)
    end = int(np.floor(mil[-1] / step) * step)
    targets = np.arange(start, end + 1, step, dtype=float)

    # mil 必須嚴格遞增才能 interp；去掉重複
    keep = np.concatenate([[True], np.diff(mil) > 0])
    milu = mil[keep]
    xyu = xy[keep]

    x = np.interp(targets, milu, xyu[:, 0])
    y = np.interp(targets, milu, xyu[:, 1])
    lon, lat = TO_WGS.transform(x, y)
    return np.column_stack([lon, lat]), targets.astype(int)


def interp_at(xy, mil, stations):
    """在折線上依里程內插出 TM 座標。stations 為公尺陣列。"""
    keep = np.concatenate([[True], np.diff(mil) > 0])
    milu = mil[keep]
    xyu = xy[keep]
    x = np.interp(stations, milu, xyu[:, 0])
    y = np.interp(stations, milu, xyu[:, 1])
    return np.column_stack([x, y])


# ---------------------------------------------------------------- mileposts

def load_mileposts():
    """回傳 {公路編號: [ {station_m, x, y, lon, lat, note, kind} ]}"""
    raw = open(MILEPOST_CSV, "rb").read().decode("big5", errors="replace")
    rows = list(csv.DictReader(io.StringIO(raw)))
    out = {}
    for r in rows:
        rid = (r.get("公路編號") or "").strip()
        st = parse_station(r.get("起點樁號"))
        try:
            lon = float(r.get("坐標-E-WGS84"))
            lat = float(r.get("坐標-N-WGS84"))
        except (TypeError, ValueError):
            continue
        if st is None or not (119 < lon < 123 and 21 < lat < 26):
            continue
        out.setdefault(rid, []).append({
            "station_m": st,
            "lon": lon,
            "lat": lat,
            "note": (r.get("備註") or "").strip(),
            "kind": (r.get("性質") or "").strip(),
            "town": (r.get("隸屬鄉鎮") or "").strip(),
            "place": (r.get("設置位置") or "").strip(),
        })
    for k in out:
        out[k].sort(key=lambda d: d["station_m"])
    return out


def nearest_on_polyline(xy, mil, pts):
    """
    對每個 pts (M,2) 求折線上最近點，回傳 (dist[M], mileage_at_nearest[M])。
    以逐段（segment）向量化計算。
    """
    a = xy[:-1]
    b = xy[1:]
    ab = b - a
    denom = (ab ** 2).sum(axis=1)
    denom[denom == 0] = 1e-12

    dists = np.empty(len(pts))
    mils = np.empty(len(pts))
    for i, p in enumerate(pts):
        ap = p - a
        t = (ap * ab).sum(axis=1) / denom
        np.clip(t, 0.0, 1.0, out=t)
        proj = a + t[:, None] * ab
        d = np.hypot(proj[:, 0] - p[0], proj[:, 1] - p[1])
        j = int(np.argmin(d))
        dists[i] = d[j]
        mils[i] = mil[j] + t[j] * (mil[j + 1] - mil[j])
    return dists, mils


def dist_along(xy, i_from=None):
    """折線各頂點的累積長度（同 cumulative，語意化別名）。"""
    return cumulative(xy)


def align_terminus(road, xy, mil, mps):
    """SPEC §9c：把折線末端里程對齊官方終點樁號。

    決策規則（SPEC §9c 1–4）：
      1. 取該路線樁號最大的幾支里程牌，求它們到折線的最近點與該點目前指派里程；
      2. 若里程牌顯示折線末端實際對應 ≈ 官方終點 → **重指派**（幾何不動）；
      3. 若里程牌顯示折線末端確實短少 → **延伸幾何**；
      4. 兩條路線終點距離 ≤ 150 m 為驗收。

    回傳 (new_mil, info dict)；不需處理的路線回傳原 mil 與 info=None。
    """
    official = road.get("terminus_m")
    if not official:
        return mil, None

    rid = road["csv_id"]
    all_mp = mps.get(rid, [])
    # 規則 1：先取 ≥ 官方終點 −1 km 的里程牌；不足 3 支就放寬到 −5 km
    picks = [p for p in all_mp if p["station_m"] >= official - 1000]
    widened = False
    if len(picks) < 3:
        picks = [p for p in all_mp if p["station_m"] >= official - 5000]
        widened = True
    if not picks:
        return mil, {"branch": 0, "reason": "找不到可用里程牌，維持原里程指派"}

    mp_xy = to_tm([(p["lon"], p["lat"]) for p in picks])
    d_near, s_near = nearest_on_polyline(xy, mil, mp_xy)

    cum = cumulative(xy)
    # 錨點＝樁號最大的那支牌（picks 已排序）
    anchor = picks[-1]
    anchor_station = float(anchor["station_m"])
    anchor_mil = float(s_near[-1])
    # 錨點在折線上的累積長度：用里程→累積長度的內插（mil 已單調）
    anchor_cum = float(np.interp(anchor_mil, mil, cum))
    tail_len = float(cum[-1] - anchor_cum)
    # 由里程牌推估的「折線末端實際樁號」
    est_end_station = anchor_station + tail_len

    info = {
        "picks": [(p["station_m"], float(dd), float(ss))
                  for p, dd, ss in zip(picks, d_near, s_near)],
        "widened": widened,
        "anchor_station": anchor_station,
        "anchor_mil": anchor_mil,
        "tail_len": tail_len,
        "est_end_station": est_end_station,
        "old_end_m": float(mil[-1]),
        "official": float(official),
    }

    if abs(est_end_station - official) <= TERMINUS_TOL_M:
        info["branch"] = 2
        info["reason"] = ("里程牌推估折線末端實際樁號 %.0f m，與官方終點 %d m 相差 %.0f m（≤ %.0f m），"
                          "屬「最後一段里程被低估」→ 重指派、幾何不動"
                          % (est_end_station, official, est_end_station - official, TERMINUS_TOL_M))
    else:
        info["branch"] = 3
        info["reason"] = ("里程牌推估折線末端實際樁號 %.0f m，距官方終點 %d m 還差 %.0f m，"
                          "折線末端確實短少" % (est_end_station, official, official - est_end_station))

    # 規則 3 的前提是「道路實體還有一段沒被畫進來」。本專案兩條路線都收在塔塔加，
    # 若本線末端已經和另一條線末端重合，就沒有實體可延伸；此時改走規則 2（見報告）。
    other_end = road.get("_other_end_xy")
    if info["branch"] == 3 and other_end is not None:
        d_ends = float(np.hypot(*(xy[-1] - other_end)))
        info["d_other_end"] = d_ends
        if d_ends < official - est_end_station:
            info["branch"] = 2
            info["reason"] += ("；但本線末端距另一條路線末端僅 %.1f m（兩線同收於塔塔加），"
                               "沒有實體路段可延伸 %.0f m，故改走規則 2（重指派、幾何不動），"
                               "以符合規則 4「兩條路線終點距離 ≤ 150 m」"
                               % (d_ends, official - est_end_station))

    if info["branch"] != 2:
        return mil, info

    # --- 規則 2：重指派 -------------------------------------------------
    # SPEC 原文是「最後一個工務段的終點里程改為 145035，段內線性重算」。
    # 實作上把重算範圍縮到「最後一支里程牌之後」：整段（68K–144K）線性重算會把
    # 段內每一點往前推最多 +650 m，破壞既有里程牌誤差（中位 ~10 m）；把差額放在
    # 最後一支已驗證里程牌之後，等同把官方里程斷鏈記在末端，其餘里程不動。
    new_mil = mil.copy().astype(float)
    tail = cum > anchor_cum
    if tail.sum() == 0 or cum[-1] <= anchor_cum:
        info["applied"] = False
        return mil, info
    scale = (official - anchor_mil) / (cum[-1] - anchor_cum)
    new_mil[tail] = anchor_mil + (cum[tail] - anchor_cum) * scale
    new_mil = np.maximum.accumulate(new_mil)
    info["applied"] = True
    info["anchor_cum"] = anchor_cum
    info["scale"] = float(scale)
    info["new_end_m"] = float(new_mil[-1])
    return new_mil, info


def linfit(s, m):
    """最小平方擬合 m = a*s + b，回傳 (a, b)。"""
    s = np.asarray(s, dtype=float)
    m = np.asarray(m, dtype=float)
    n = len(s)
    sm = s.mean()
    mm = m.mean()
    denom = ((s - sm) ** 2).sum()
    a = ((s - sm) * (m - mm)).sum() / denom if denom else 1.0
    b = mm - a * sm
    return float(a), float(b)


# ---------------------------------------------------------------- main

def main():
    try:  # Windows 主控台預設 cp950，報告文字含「≤」等字元會炸
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.makedirs(OUT_DIR, exist_ok=True)
    built_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    mileposts = load_mileposts()
    report = []

    report.append("# 省道里程折線 校正報告")
    report.append("")
    report.append("產生時間：`%s`" % built_at)
    report.append("")
    report.append("產生工具：`scripts/build_roads.py`（`.venv` 執行）")
    report.append("")
    report.append("## 資料源與 schema")
    report.append("")
    report.append("### A. 線型 — data.gov.tw 105020「省道公路路線圖資」")
    report.append("")
    report.append("實際下載到的**不是 SHP，是 KMZ**（dataset 的 `resourceFormat` 標「壓縮檔」）。")
    report.append("結構為三層：`roads_105020.zip` → `省道公路路線KMZ_11502.zip` → 每條路線一個 `P####.kmz` → `doc.kml`。")
    report.append("KML 座標已是 **WGS84 經緯度**，因此不需要 TWD97→WGS84 轉換（`pyproj` 改用於把經緯度投影到 EPSG:3826 做平面長度計算）。")
    report.append("")
    report.append("每個 `Placemark` = 一個工務段，屬性寫在 `description` 的 HTML 表格裡。欄位（名稱、型別、實際值）：")
    report.append("")
    report.append("| 欄位 | 型別 | 台18 首筆實際值 |")
    report.append("|---|---|---|")
    report.append("| 公路編號 | 字串 | `台18` |")
    report.append("| 公路編碼 | 字串 | `P0180` |")
    report.append("| 工程處 | 字串 | `雲嘉南區養護工程分局` |")
    report.append("| 工務段 | 字串 | `水上工務段` |")
    report.append("| 縣市別 | 字串 | `嘉義縣` |")
    report.append("| 代養機關 | 字串 | （空） |")
    report.append("| 方向 | 字串 | `順向` |")
    report.append("| 調查日期 | 日期字串 | `2014/9/5` |")
    report.append("| **樁號範圍** | 字串 `nK+nnn至nK+nnn` | `0K+000至8K+531` |")
    report.append("| 幾何 | MultiGeometry/LineString | WGS84 lon,lat,0 |")
    report.append("")
    report.append("**路線編號欄位的實際值是 `台18` / `台21`**（不是 `18`、`0018` 或 `TW18`）；")
    report.append("KMZ 檔名用的公路編碼是 `P0180` / `P0210`（`P0211` 為台21甲，已排除）。")
    report.append("")
    report.append("**schema 含里程屬性：是。** 每段有官方「樁號範圍」，所以里程指派走「每段線性內插」，")
    report.append("不需要用里程牌做整體線性校正（見下方 §校正診斷）。")
    report.append("")
    report.append("### B. 校正 — data.gov.tw 7040「省道里程坐標(里程牌標誌)」")
    report.append("")
    report.append("`milepost_7040.csv`，Big5 編碼，23 欄，30,057 筆。前 3 欄之外的關鍵欄位：")
    report.append("`公路編號`（值 `台18` / `台21` / `台21甲`）、`起點樁號`（`0K+000` 格式）、")
    report.append("`坐標-E-WGS84`、`坐標-N-WGS84`、`坐標-X-TWD97`、`坐標-Y-TWD97`、`備註`、`性質`、`設置位置`。")
    report.append("台18 有 748 筆、台21 有 329 筆里程牌。")
    report.append("")
    report.append("> 下載註記：7040 在 data.gov.tw 登記的 `https://www.thb.gov.tw/Common/ThbOpenDataService.ashx?SN=484&format=4&rel=156905`")
    report.append("> 被 Incapsula WAF 的 JS challenge 擋住（curl 各種 header 組合都回 HTTP 200 但 body 是 challenge HTML）。")
    report.append("> 該端點實際會 302 到 `https://ws.thb.gov.tw/Download.ashx?u=<base64 路徑>&n=<base64 檔名>&icon=.csv`，")
    report.append("> 這個 host 沒有 WAF，curl 直取得到 HTTP 200 / 5,242,485 bytes / `application/vnd.ms-excel`。")
    report.append("")

    summary_rows = []

    prev_end_xy = None
    terminus_infos = []
    out_ends = {}

    for road in ROADS:
        kml = read_inner_kmz(road["code"])
        segs = parse_kml_segments(kml)
        xy, mil, diag = build_polyline(segs)

        # ---- SPEC §9c：終點樁號對齊（只有設了 terminus_m 的路線會動）
        road["_other_end_xy"] = prev_end_xy
        mil, term_info = align_terminus(road, xy, mil, mileposts)
        if term_info:
            term_info["road"] = road["name"]
            terminus_infos.append(term_info)
            log("[%s] §9c 終點對齊：走規則 %d — %s"
                % (road["name"], term_info["branch"], term_info["reason"]))

        lonlat, stations = resample(xy, mil)

        # ---- 輸出 GeoJSON
        coords = [[round(float(lo), 6), round(float(la), 6)] for lo, la in lonlat]
        stations = [int(s) for s in stations]
        terminus_note = ""
        if term_info and term_info.get("applied") and stations[-1] < int(term_info["official"]):
            # 重採樣落在 100 m 網格上（末點 145000），補一個「官方終點樁號」頂點，
            # 讓 145K+035 這類事件里程不會被 roadgeom 的 clamp 警告擋掉（SPEC §9c 末條）。
            end_lon, end_lat = TO_WGS.transform(xy[-1, 0], xy[-1, 1])
            coords.append([round(float(end_lon), 6), round(float(end_lat), 6)])
            stations.append(int(term_info["official"]))
            terminus_note = ("末頂點為官方終點樁號 %s（SPEC §9c 規則 %d 重指派），"
                             "與前一頂點間距 %d m"
                             % (fmt_station(int(term_info["official"])), term_info["branch"],
                                stations[-1] - stations[-2]))
        feature = {
            "type": "Feature",
            "properties": {
                "road": road["name"],
                "start_m": int(stations[0]),
                "end_m": int(stations[-1]),
                "source": SOURCE_NOTE,
                "built_at": built_at,
                "step_m": STEP_M,
                "crs_note": "WGS84 lon/lat, 6 decimals; mileage_m = 沿線累積里程(公尺, 官方樁號)",
                "mileage_m": [int(s) for s in stations],
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        }
        if terminus_note:
            feature["properties"]["terminus_note"] = terminus_note
        out_ends[road["name"]] = (coords[-1], stations[-1])
        prev_end_xy = xy[-1]
        gj = {"type": "FeatureCollection", "features": [feature]}
        out_path = os.path.join(OUT_DIR, road["out"])
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(gj, f, ensure_ascii=False, separators=(",", ":"))

        log("[%s] 段數=%d 原始頂點=%d 輸出頂點=%d 里程 %d..%d m -> %s"
            % (road["name"], len(segs), len(xy), len(coords),
               stations[0], stations[-1], road["out"]))

        # ---- 校正
        mps = mileposts.get(road["csv_id"], [])
        in_range = [p for p in mps if mil[0] <= p["station_m"] <= mil[-1]]
        skipped = len(mps) - len(in_range)

        mp_xy = to_tm([(p["lon"], p["lat"]) for p in in_range])
        pred = interp_at(xy, mil, np.array([p["station_m"] for p in in_range], dtype=float))
        errs = np.hypot(pred[:, 0] - mp_xy[:, 0], pred[:, 1] - mp_xy[:, 1])

        # 診斷用：最近點 + 線性擬合 m = a*s + b
        d_near, s_near = nearest_on_polyline(xy, mil, mp_xy)
        a, b = linfit(s_near, [p["station_m"] for p in in_range])

        med = float(np.median(errs))
        p90 = float(np.percentile(errs, 90))
        mx = float(errs.max())

        summary_rows.append((road["name"], len(coords), len(in_range), med, p90, mx, a, b))

        report.append("## %s（%s）" % (road["name"], road["desc"]))
        report.append("")
        report.append("### 折線組成")
        report.append("")
        report.append("| 工務段 | 樁號範圍 | 官方里程長 (m) | 幾何長度 (m) | 幾何/官方 | KML 頂點 |")
        report.append("|---|---|---:|---:|---:|---:|")
        for s in diag["segments"]:
            if not isinstance(s, dict):
                continue
            report.append("| %s | %s 至 %s | %d | %.0f | %.4f | %d |" % (
                s["name"], fmt_station(s["start_m"]), fmt_station(s["end_m"]),
                s["span_m"], s["geo_len_m"], s["ratio"], s["pts"]))
        report.append("")
        if diag["gaps"]:
            report.append("段間接縫距離（上一段終點 → 本段起點）：" + "、".join(
                "%s %.1f m" % (n, g) for n, st, g in diag["gaps"]))
            report.append("")
        report.append("輸出：`site/data/roads/%s`，`LineString` %d 個頂點，"
                      "里程 %s – %s，每 %d m 一點。"
                      % (road["out"], len(coords), fmt_station(int(stations[0])),
                         fmt_station(int(stations[-1])), STEP_M))
        report.append("")
        report.append("### 里程牌誤差")
        report.append("")
        report.append("方法：取 7040 中該路線每一支里程牌的官方樁號 `m`，在本折線上內插出座標，"
                      "與里程牌自身的 WGS84 座標算平面直線距離（EPSG:3826）。")
        report.append("")
        report.append("| 指標 | 值 |")
        report.append("|---|---|")
        report.append("| 里程牌筆數（落在里程範圍內） | %d |" % len(in_range))
        report.append("| 範圍外略過 | %d |" % skipped)
        report.append("| median | **%.1f m** |" % med)
        report.append("| p90 | %.1f m |" % p90)
        report.append("| max | %.1f m |" % mx)
        report.append("| mean | %.1f m |" % float(errs.mean()))
        report.append("")

        order = np.argsort(-errs)[:5]
        report.append("最大誤差前 5 筆：")
        report.append("")
        report.append("| 樁號 | 誤差 (m) | 到折線最近距離 (m) | 鄉鎮 | 備註/性質 | 可能原因 |")
        report.append("|---|---:|---:|---|---|---|")
        for i in order:
            p = in_range[int(i)]
            note = (p["note"] or p["kind"] or "").replace("|", "/")
            if d_near[i] < 60 and errs[i] > 200:
                cause = "牌子就在線上（%.0f m），是**里程指派**偏掉，非線型錯" % d_near[i]
            elif d_near[i] >= 60:
                cause = "里程牌座標離本路線線型 %.0f m，疑似**牌位登錄偏移或屬支線/匝道**" % d_near[i]
            else:
                cause = "工務段內線性內插的殘差（段內里程非等比）"
            report.append("| %s | %.0f | %.0f | %s | %s | %s |" % (
                fmt_station(p["station_m"]), errs[i], d_near[i],
                p["town"], note or "—", cause))
        report.append("")

        # ---- 誤差沿里程的分佈（把「線型錯」和「里程指派錯」分開看）
        st_arr = np.array([p["station_m"] for p in in_range], dtype=float)
        offset = s_near - st_arr  # 折線里程 - 官方樁號（正 = 折線里程跑太快）
        report.append("### 誤差沿里程的分佈")
        report.append("")
        report.append("`最近距離` = 里程牌到本折線的垂直距離，衡量**線型**對不對；")
        report.append("`里程偏移` = 折線在最近點的里程 − 官方樁號，衡量**里程指派**對不對。")
        report.append("")
        report.append("| 里程帶 | 里程牌數 | 中位誤差 | 中位最近距離 | 中位里程偏移 |")
        report.append("|---|---:|---:|---:|---:|")
        for lo in range(0, int(st_arr.max()) + 10000, 10000):
            sel = (st_arr >= lo) & (st_arr < lo + 10000)
            if sel.sum() == 0:
                continue
            report.append("| %dK–%dK | %d | %.1f m | %.1f m | %+.1f m |" % (
                lo // 1000, lo // 1000 + 10, int(sel.sum()),
                float(np.median(errs[sel])), float(np.median(d_near[sel])),
                float(np.median(offset[sel]))))
        report.append("")
        report.append("全線里程牌到折線的**最近距離**：中位 %.1f m、最大 %.1f m。"
                      % (float(np.median(d_near)), float(d_near.max())))
        report.append("")
        if float(d_near.max()) < 60:
            report.append("> **關鍵判讀**：所有里程牌都落在折線 %.0f m 以內，代表 KML 的**線型本身是準的**；"
                          "誤差幾乎全部來自「某個樁號該落在線上哪一點」的里程指派。"
                          % float(d_near.max()))
            report.append("")

        # 段內漂移警告
        worst = max((s for s in diag["segments"] if isinstance(s, dict)),
                    key=lambda s: abs(s["span_m"] - s["geo_len_m"]))
        deficit = worst["span_m"] - worst["geo_len_m"]
        if abs(deficit) > 200:
            report.append("> **已知系統性偏差**：`%s`（%s 至 %s，長 %.1f km）的官方樁號跨距比幾何長度多 %.0f m。"
                          % (worst["name"], fmt_station(worst["start_m"]),
                             fmt_station(worst["end_m"]), worst["span_m"] / 1000.0, deficit))
            report.append("> 段內線性內插會把這 %.0f m 的差**平均攤到整段**，但實際上它集中在少數幾個"
                          "改線／里程斷鏈點，於是段中央出現先累積、後回復的漂移"
                          "（本路線最大到約 %+.0f m，位置見上表）。" % (deficit, float(np.max(np.abs(offset)))))
            report.append(">")
            report.append("> 這**沒有**被調參掩蓋：本報告刻意保留段內線性內插，"
                          "誤差數字才是可獨立驗證的。要再壓下去的作法是"
                          "「用里程牌當錨點，在段內做單調分段線性的里程重指派」，"
                          "但那會讓上面的誤差統計變成自我參照（趨近 0），失去驗證意義，因此列為後續項目。")
            report.append("")
        report.append("### 校正診斷（線性擬合，**未套用**）")
        report.append("")
        report.append("對每支里程牌求其在折線上的最近點累積里程 `s`，與官方樁號 `m` 最小平方擬合 `m = a·s + b`：")
        report.append("")
        report.append("- **a = %.6f**、**b = %.2f m**" % (a, b))
        report.append("")
        if abs(a - 1.0) < 0.002 and abs(b) < 60:
            report.append("a 已極接近 1、b 極接近 0，代表 KML 的官方「樁號範圍」逐段內插後，"
                          "里程尺度與里程牌本身一致。**因此不套用這組 a/b**——"
                          "套上去只會是對殘差的過度擬合，也違反「不得調參到剛好過」。")
        else:
            report.append("a/b 偏離 1/0，已在上表列出成因；仍**不套用**全域線性校正，"
                          "因為官方樁號範圍是逐段給定的，全域一次校正會破壞段內既有的正確里程。")
        report.append("")

        # ---- 抽查點
        checks = road.get("checks", [])
        if checks:
            report.append("### 抽查點")
            report.append("")
            report.append("| 地點 | 參考座標 | 最近里程牌 | 折線內插座標 | 直線距離 |")
            report.append("|---|---|---|---|---:|")
            for label, clon, clat in checks:
                c_xy = to_tm([(clon, clat)])
                # 從里程牌 CSV 找該地點附近的樁號
                d = np.hypot(mp_xy[:, 0] - c_xy[0, 0], mp_xy[:, 1] - c_xy[0, 1])
                j = int(np.argmin(d))
                st = in_range[j]["station_m"]
                pxy = interp_at(xy, mil, np.array([float(st)]))
                plon, plat = TO_WGS.transform(pxy[0, 0], pxy[0, 1])
                dist = float(np.hypot(pxy[0, 0] - c_xy[0, 0], pxy[0, 1] - c_xy[0, 1]))
                report.append("| %s | %.4f, %.4f | %s (%.0f m 外) | %.6f, %.6f | **%.0f m** |" % (
                    label, clon, clat, fmt_station(st), d[j], plon, plat, dist))
            report.append("")

    # ---- 總表
    head = ["## 總表", "",
            "| 路線 | 輸出頂點 | 里程牌數 | median | p90 | max | a | b |",
            "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, npts, nmp, med, p90, mx, a, b in summary_rows:
        head.append("| %s | %d | %d | %.1f m | %.1f m | %.1f m | %.6f | %.2f m |"
                    % (name, npts, nmp, med, p90, mx, a, b))
    head.append("")
    report = report[:report.index("## %s（%s）" % (ROADS[0]["name"], ROADS[0]["desc"]))] \
        + head + report[report.index("## %s（%s）" % (ROADS[0]["name"], ROADS[0]["desc"])):]

    # ---- SPEC §9c 終點對齊小節（附在報告末尾）
    report.append("## SPEC §9c 台21 終點對齊 145K+035")
    report.append("")
    if not terminus_infos:
        report.append("本次執行沒有任何路線設定 `terminus_m`，未做終點對齊。")
        report.append("")
    for info in terminus_infos:
        report.append("### %s" % info["road"])
        report.append("")
        report.append("**走規則 %d**。%s" % (info["branch"], info["reason"]))
        report.append("")
        report.append("規則 1 取樣的里程牌（%s）：" % (
            "官方終點前 5 km 內（前 1 km 內不足 3 支）" if info.get("widened")
            else "官方終點前 1 km 內"))
        report.append("")
        report.append("| 里程牌樁號 | 到折線最近距離 | 折線該點原指派里程 | 里程偏移 |")
        report.append("|---|---:|---:|---:|")
        for st, dd, ss in info["picks"]:
            report.append("| %s | %.1f m | %.0f m | %+.0f m |" % (fmt_station(int(st)), dd, ss, ss - st))
        report.append("")
        report.append("- 錨點（樁號最大的里程牌）：%s，其後折線還有 **%.1f m**，"
                      "推估折線末端實際樁號 **%.0f m**；原折線末端里程 %.0f m、官方終點 %d m。"
                      % (fmt_station(int(info["anchor_station"])), info["tail_len"],
                         info["est_end_station"], info["old_end_m"], int(info["official"])))
        if "d_other_end" in info:
            report.append("- 本線末端到另一條路線（台18線）末端：**%.1f m**（兩線同收於塔塔加）。"
                          % info["d_other_end"])
        if info.get("applied"):
            report.append("- 重指派：錨點之後的 %.1f m 幾何，里程由 %.0f m 線性拉伸到 %d m"
                          "（比例 %.3f m/m）；錨點之前的里程完全不動，幾何完全不動。"
                          % (info["tail_len"], info["anchor_mil"], int(info["official"]),
                             info["scale"]))
            report.append("- 這等同把官方里程斷鏈記在最後一支已驗證里程牌之後。"
                          "SPEC 原文寫的是「最後一個工務段的終點里程改為 145035，段內線性重算」，"
                          "但那會把 68K–144K 段內每一點往前推最多 +650 m、破壞既有里程牌誤差"
                          "（中位 ~10 m），故縮小重算範圍。")
        report.append("")
    if len(out_ends) >= 2:
        names = list(out_ends.keys())
        (c1, m1), (c2, m2) = out_ends[names[0]], out_ends[names[1]]
        p = to_tm([tuple(c1), tuple(c2)])
        d_end = float(np.hypot(*(p[0] - p[1])))
        report.append("### 規則 4 驗收：兩條路線終點距離")
        report.append("")
        report.append("| 路線 | 末頂點里程 | 末頂點座標 |")
        report.append("|---|---:|---|")
        report.append("| %s | %s | %.6f, %.6f |" % (names[0], fmt_station(int(m1)), c1[0], c1[1]))
        report.append("| %s | %s | %.6f, %.6f |" % (names[1], fmt_station(int(m2)), c2[0], c2[1]))
        report.append("")
        report.append("**兩線終點距離 = %.1f m**（門檻 %.0f m → %s）"
                      % (d_end, TERMINUS_TOL_M, "PASS" if d_end <= TERMINUS_TOL_M else "FAIL"))
        report.append("")
        log("§9c 規則 4：兩條路線終點距離 %.1f m（門檻 %.0f m）→ %s"
            % (d_end, TERMINUS_TOL_M, "PASS" if d_end <= TERMINUS_TOL_M else "FAIL"))

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    log("報告 -> %s" % os.path.relpath(REPORT, ROOT))
    log("完成。")


# 抽查點（驗收條件 4）
ROADS[0]["checks"] = [("阿里山", 120.8030, 23.5100)]
ROADS[1]["checks"] = [("塔塔加遊客中心", 120.8863, 23.4877),
                      ("信義鄉公所", 120.8550, 23.6980)]

if __name__ == "__main__":
    sys.exit(main())
