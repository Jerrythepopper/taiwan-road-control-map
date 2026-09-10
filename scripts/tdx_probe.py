"""TDX 路況資訊 v2 端點實測探針。

用途：確認 (1) client_credentials 能否換到 access token；(2) 「路況資訊v2」底下
Live/News 系列端點能不能回傳台18線/台21線的事件、有沒有座標/里程欄位。

安全：絕不印出或寫出 token / client_secret 本身。只印出狀態碼、筆數、欄位名稱、
命中筆數等中繼資訊。

用法：
    python scripts/tdx_probe.py

輸出：
    - 終端機列印每個端點的探測結果摘要
    - research/tdx-samples/<slug>.json：命中台18/台21的端點，前5筆原始 JSON
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
SAMPLES_DIR = ROOT / "research" / "tdx-samples"

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
API_ROOT = "https://tdx.transportdata.tw/api/basic"

# 候選端點：全部屬於「路況資訊v2」(UUID 7f07d940-91a4-495d-9465-1c9df89d709c) 這一支
# OpenAPI 底下的 Live/News 系列。這是本次 swagger 實測唯一找得到、TDX 文件明講會回
# 「最新路況新聞/事件通報」的端點家族；候選字串 Live/Event/、RoadEvent 在該 swagger
# 裡查無對應路徑，因此不生成假端點，只探測真實存在的路徑。
CANDIDATE_ENDPOINTS = [
    ("News_City_ChiayiCounty", "/v2/Road/Traffic/Live/News/City/ChiayiCounty", "台18線所在縣市"),
    ("News_City_NantouCounty", "/v2/Road/Traffic/Live/News/City/NantouCounty", "台21線所在縣市"),
    ("News_City_TaichungCity", "/v2/Road/Traffic/Live/News/City/TaichungCity", "台21線亦經台中"),
    ("News_Highway", "/v2/Road/Traffic/Live/News/Highway", "省道類別，全國，需自行篩台18/台21"),
    ("News_Freeway", "/v2/Road/Traffic/Live/News/Freeway", "國道類別，對照組"),
]

# 用來判斷回傳筆數是否命中台18/台21的關鍵字（Title/Description/RoadName 等欄位皆可能含這些字串）
ROUTE_KEYWORDS = ["台18", "台18線", "阿里山公路", "台21", "台21線", "新中橫"]

# 判斷是否含座標/里程欄位的欄位名關鍵字
POSITION_FIELD_HINTS = ["Position", "PositionLat", "PositionLon", "Lat", "Lon", "Latitude", "Longitude"]
MILEAGE_FIELD_HINTS = ["Mileage", "Mile", "StartMile", "EndMile"]
ROADNAME_FIELD_HINTS = ["RoadName", "RoadID", "RouteName", "RouteID"]


def load_env(path: Path) -> dict:
    """讀 .env，只回傳 key/value 的 dict，不印出內容。"""
    if not path.exists():
        print(f"[FATAL] 找不到 .env：{path}", file=sys.stderr)
        sys.exit(1)
    env = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def get_token(client_id: str, client_secret: str) -> tuple[str | None, int, str]:
    """回傳 (access_token 或 None, http_status, 錯誤訊息去敏後摘要)。"""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    status = resp.status_code
    if status != 200:
        # 去敏：body 裡不會含 secret（TDX 錯誤訊息通常是 invalid_client 等），但保險起見過濾
        body = resp.text
        body = redact(body, client_id, client_secret)
        return None, status, body[:500]
    data = resp.json()
    token = data.get("access_token")
    return token, status, ""


def redact(text: str, *secrets: str) -> str:
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, "***REDACTED***")
    return out


def scan_fields(obj) -> set:
    """遞迴收集 JSON 物件裡所有的 key 名稱。"""
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            keys |= scan_fields(v)
    elif isinstance(obj, list):
        for item in obj:
            keys |= scan_fields(item)
    return keys


def contains_any_text(obj, keywords) -> bool:
    """檢查 JSON 物件裡任何字串值是否含關鍵字。"""
    if isinstance(obj, dict):
        return any(contains_any_text(v, keywords) for v in obj.values())
    if isinstance(obj, list):
        return any(contains_any_text(v, keywords) for v in obj)
    if isinstance(obj, str):
        return any(kw in obj for kw in keywords)
    return False


def count_hits(items: list, keywords) -> int:
    return sum(1 for item in items if contains_any_text(item, keywords))


def probe_endpoint(token: str, slug: str, path: str, note: str) -> dict:
    url = f"{API_ROOT}{path}"
    params = {"$top": 30, "$format": "JSON"}
    headers = {"authorization": f"Bearer {token}"}
    result = {
        "slug": slug,
        "path": path,
        "note": note,
        "status": None,
        "count": 0,
        "fields": [],
        "has_position": False,
        "has_mileage": False,
        "has_roadname": False,
        "route18_hits": 0,
        "route21_hits": 0,
        "error": "",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        result["error"] = str(e)
        return result

    result["status"] = resp.status_code
    if resp.status_code != 200:
        result["error"] = redact(resp.text[:300], token)
        return result

    try:
        data = resp.json()
    except ValueError:
        result["error"] = "回應不是合法 JSON"
        return result

    # TDX v2 回應通常是 list，或包在 wrapper dict 裡（例如 {"UpdateTime":...,"Newses":[...]}）。
    # 不能只抓第一個 key（第一個常是 UpdateTime 這種 metadata），要找「值是 list」的那個 key。
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = []
        for v in data.values():
            if isinstance(v, list):
                items = v
                break
    else:
        items = []

    result["count"] = len(items)
    fields = scan_fields(items)
    result["fields"] = sorted(fields)
    result["has_position"] = any(f in fields for f in POSITION_FIELD_HINTS)
    result["has_mileage"] = any(f in fields for f in MILEAGE_FIELD_HINTS)
    result["has_roadname"] = any(f in fields for f in ROADNAME_FIELD_HINTS)
    result["route18_hits"] = count_hits(items, ["台18", "阿里山公路"])
    result["route21_hits"] = count_hits(items, ["台21", "新中橫"])
    result["_items"] = items  # 內部用，不印出，只供寫 sample 檔
    return result


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    env = load_env(ENV_PATH)
    client_id = env.get("TDX_CLIENT_ID", "")
    client_secret = env.get("TDX_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("[FATAL] .env 缺 TDX_CLIENT_ID 或 TDX_CLIENT_SECRET", file=sys.stderr)
        sys.exit(1)

    print("=== Step 1: 取得 access token ===")
    token, status, err = get_token(client_id, client_secret)
    print(f"HTTP status: {status}")
    if token is None:
        print(f"[FAIL] token 取得失敗。錯誤訊息（已去敏）：{err}")
        sys.exit(2)
    print(f"[OK] token 取得成功，長度 {len(token)}（不印出內容）")

    print("\n=== Step 2: 逐一探測候選端點 ===")
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for slug, path, note in CANDIDATE_ENDPOINTS:
        time.sleep(2)  # 避免觸發 TDX burst rate limit (429)
        r = probe_endpoint(token, slug, path, note)
        results.append(r)
        print(f"\n--- {slug} ({path}) ---")
        print(f"  說明: {note}")
        print(f"  HTTP status: {r['status']}")
        if r["error"]:
            print(f"  錯誤: {r['error']}")
        print(f"  筆數: {r['count']}")
        print(f"  欄位: {r['fields']}")
        print(f"  含座標欄位: {r['has_position']} / 含里程欄位: {r['has_mileage']} / 含路名欄位: {r['has_roadname']}")
        print(f"  台18命中: {r['route18_hits']} / 台21命中: {r['route21_hits']}")

        if r["route18_hits"] > 0 or r["route21_hits"] > 0:
            sample_path = SAMPLES_DIR / f"{slug}.json"
            items = r.get("_items", [])
            with sample_path.open("w", encoding="utf-8") as f:
                json.dump(items[:5], f, ensure_ascii=False, indent=2)
            print(f"  [已寫 sample] {sample_path}")

    print("\n=== Step 3: 反向 grep 自檢（確認終端輸出不含 secret） ===")
    # 本腳本本身不印出 client_secret / token，此段留給外部呼叫者對 log 做 grep 自檢。
    print(f"client_id 長度={len(client_id)}, client_secret 長度={len(client_secret)}（僅列長度供人工比對，不印出內容）")

    print("\n=== 完成 ===")


if __name__ == "__main__":
    main()
