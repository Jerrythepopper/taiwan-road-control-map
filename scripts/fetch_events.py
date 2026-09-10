"""產生 `site/data/events.geojson`：TDX 公路局快訊 + 人工常態規則檔。

來源（SPEC §8b）：
  1. TDX `GET /v2/Road/Traffic/Live/News/Highway`（臨時性施工／事故快訊，自由文字）
  2. `scripts/manual_rules.json`（常態性管制規則，人工維護，例如台21夜間封閉）

幾何：里程 → `site/data/roads/{tw18,tw21}.geojson` 內插子段 → LineString。

用法：
    .venv/Scripts/python.exe scripts/fetch_events.py              # 線上抓 TDX
    .venv/Scripts/python.exe scripts/fetch_events.py --offline    # 讀離線樣本，不打網路
    .venv/Scripts/python.exe scripts/fetch_events.py --out <path> # 指定輸出路徑

安全：TDX 憑證只從 `.env` 讀，token 不印出、不寫檔。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import parse_news  # noqa: E402
import roadgeom  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
OFFLINE_SAMPLE = ROOT / "research" / "tdx-samples" / "News_Highway_full.json"
MANUAL_RULES = Path(__file__).resolve().parent / "manual_rules.json"
DEFAULT_OUT = ROOT / "site" / "data" / "events.geojson"

TDX_API = "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/Live/News/Highway"
TDX_SOURCE_LABEL = "TDX 路況資訊v2 Live/News/Highway"
MANUAL_SOURCE_LABEL = "scripts/manual_rules.json（人工維護常態規則）"

GEOM_PRECISION = "route-interp"


def now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


# --- 取資料 ---------------------------------------------------------------


def fetch_tdx_online() -> list:
    """線上抓 TDX 全量快訊。token 流程沿用 scripts/tdx_probe.py（不印出 secret）。"""
    import requests
    from tdx_probe import get_token, load_env  # 重用既有、已驗證不外洩 secret 的流程

    # 本機讀 .env；CI（GitHub Actions）沒有 .env 時退回環境變數（GitHub Secrets 注入）
    env = load_env(ENV_PATH) if ENV_PATH.exists() else dict(os.environ)
    client_id = env.get("TDX_CLIENT_ID", "")
    client_secret = env.get("TDX_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("[FATAL] .env 缺 TDX_CLIENT_ID 或 TDX_CLIENT_SECRET", file=sys.stderr)
        sys.exit(1)

    token, status, err = get_token(client_id, client_secret)
    if token is None:
        print(f"[FATAL] TDX token 取得失敗 (HTTP {status})：{err}", file=sys.stderr)
        sys.exit(2)
    print(f"[TDX] token OK（HTTP {status}，長度 {len(token)}，內容不印出）")

    resp = requests.get(
        TDX_API,
        params={"$top": 1000, "$format": "JSON"},
        headers={"authorization": f"Bearer {token}"},
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"[FATAL] TDX API HTTP {resp.status_code}", file=sys.stderr)
        sys.exit(3)
    data = resp.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def fetch_tdx_offline() -> list:
    with OFFLINE_SAMPLE.open("r", encoding="utf-8") as f:
        return json.load(f)


# --- 組事件 ---------------------------------------------------------------


def make_id(source: str, road: str, from_km: str, to_km: str, title: str) -> str:
    raw = f"{source}{road}{from_km}{to_km}{title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def to_feature(props: dict, from_m, to_m, fetched_at: str) -> dict:
    warnings = list(props.get("parse_warnings") or [])
    geometry, geo_warnings = roadgeom.line_string(props["road"], from_m, to_m)
    warnings.extend(geo_warnings)

    out = {k: v for k, v in props.items() if k not in ("from_m", "to_m", "source")}
    out["id"] = make_id(
        props.get("source", "manual"), props["road"], props.get("from_km", ""),
        props.get("to_km", ""), props.get("title", ""),
    )
    out["fetched_at"] = fetched_at
    out["geom_precision"] = GEOM_PRECISION if geometry else "unknown"
    out["parse_warnings"] = warnings
    return {"type": "Feature", "properties": out, "geometry": geometry}


def build_tdx_features(items: list, fetched_at: str, today: _dt.date) -> list:
    feats = []
    for item in items:
        props = parse_news.parse(item, today=today)
        if props is None:
            continue
        feats.append(to_feature(props, props.get("from_m"), props.get("to_m"), fetched_at))
    return feats


def build_manual_features(fetched_at: str, today: _dt.date) -> list:
    if not MANUAL_RULES.exists():
        return []
    with MANUAL_RULES.open("r", encoding="utf-8") as f:
        rows = json.load(f)
    feats = []
    for row in rows:
        props = dict(row)
        props.setdefault("direction", "")
        props.setdefault("rules", [])
        props.setdefault("parse_warnings", [])
        props["source"] = "manual"
        props["source_id"] = ""
        props["status"] = parse_news.detect_status(
            props.get("start_date", ""), props.get("end_date", ""), today
        )
        from_m = roadgeom.parse_km(props.get("from_km", ""))
        to_m = roadgeom.parse_km(props.get("to_km", ""))
        if from_m is None or to_m is None:
            props["parse_warnings"].append("manual_rules.json 里程樁號格式無法解析")
        feats.append(to_feature(props, from_m, to_m, fetched_at))
    return feats


def dedupe(features: list) -> list:
    """同 id 的處理（manual 先進、優先保留）。

    SPEC §8b-4 的 id 公式不含 NewsID，實測會撞號：NewsID 79329 與 79469 的
    Title 完全相同（台21線北上65K+740至65K+226 水社隧道），只有施工日期不同。
    這裡不丟資料——來源不同（source_id 不同）就在 id 後綴 `-<source_id>` 區隔；
    真正整筆重複（同來源同 id）才略過。
    """
    seen, out = {}, []
    for f in features:
        p = f["properties"]
        fid = p["id"]
        sid = p.get("source_id") or ""
        if fid in seen:
            if seen[fid] == sid:
                continue  # 完全重複
            p["id"] = f"{fid}-{sid}"
            p.setdefault("parse_warnings", []).append(
                f"id 與另一筆公告相同（同路線/里程/標題），已加後綴 -{sid} 區隔"
            )
            out.append(f)
            continue
        seen[fid] = sid
        out.append(f)
    return out


# --- 輸出與摘要 -----------------------------------------------------------


def write_geojson(path: Path, features: list, sources: list) -> None:
    fc = {
        "type": "FeatureCollection",
        "meta": {"generated_at": now_iso(), "sources": sources},
        "features": features,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=2)
        f.write("\n")


def print_summary(features: list, sources: list, raw_count: int, out_path: Path) -> None:
    n18 = sum(1 for f in features if f["properties"]["road"] == "台18線")
    n21 = sum(1 for f in features if f["properties"]["road"] == "台21線")
    warned = [f for f in features if f["properties"].get("parse_warnings")]
    no_geom = [f for f in features if f["geometry"] is None]
    by_type = {}
    for f in features:
        by_type[f["properties"]["type"]] = by_type.get(f["properties"]["type"], 0) + 1

    print("\n=== 摘要 ===")
    print(f"TDX 來源總筆數（未篩選）: {raw_count}")
    for s in sources:
        print(f"來源 {s['name']}: 採用 {s['count']} 筆（fetched_at {s['fetched_at']}）")
    print(f"輸出事件總數: {len(features)}（台18線 {n18} / 台21線 {n21}）")
    print(f"type 分布: {by_type}")
    print(f"解析警告筆數: {len(warned)}；無幾何(geometry:null)筆數: {len(no_geom)}")
    for f in warned:
        p = f["properties"]
        print(f"  [warn] {p['road']} {p.get('from_km','')}–{p.get('to_km','')} "
              f"{p.get('source_id') or 'manual'}: {'; '.join(p['parse_warnings'])}")
    print(f"輸出檔: {out_path}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="產生 site/data/events.geojson")
    ap.add_argument("--offline", action="store_true", help="讀 research/tdx-samples 全量樣本，不打網路")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="輸出路徑")
    args = ap.parse_args()

    today = _dt.date.today()
    fetched_at = now_iso()

    if args.offline:
        print(f"[來源] 離線樣本 {OFFLINE_SAMPLE}")
        items = fetch_tdx_offline()
    else:
        print("[來源] TDX 線上 API")
        items = fetch_tdx_online()
    raw_count = len(items)

    tdx_feats = build_tdx_features(items, fetched_at, today)
    manual_feats = build_manual_features(fetched_at, today)
    features = dedupe(manual_feats + tdx_feats)

    # 排序：路線 → 起點里程
    features.sort(key=lambda f: (
        f["properties"]["road"],
        roadgeom.parse_km(f["properties"].get("from_km", "")) or 0,
    ))

    sources = [
        {
            "name": TDX_SOURCE_LABEL + ("（離線樣本）" if args.offline else ""),
            "fetched_at": fetched_at,
            "count": len(tdx_feats),
        },
        {"name": MANUAL_SOURCE_LABEL, "fetched_at": fetched_at, "count": len(manual_feats)},
    ]

    out_path = Path(args.out)
    write_geojson(out_path, features, sources)
    print_summary(features, sources, raw_count, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
