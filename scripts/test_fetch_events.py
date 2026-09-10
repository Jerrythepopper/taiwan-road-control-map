"""SPEC §8c 資料單驗收測試。

跑法（不打網路，輸出到暫存檔，不動 site/data/events.geojson）：
    .venv/Scripts/python.exe scripts/test_fetch_events.py

任一項失敗 → 印 [FAIL] 並 sys.exit(1)。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(__file__).resolve().parent / "fetch_events.py"
ENV_PATH = ROOT / ".env"

FAILURES: list = []
PASSES: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSES if ok else FAILURES).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def load_env_values(path: Path) -> list:
    """只取 .env 的「值」用來做反向 grep，不印出。"""
    vals = []
    if not path.exists():
        return vals
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        v = line.split("=", 1)[1].strip().strip('"').strip("'")
        if len(v) >= 8:  # 太短的值（空值、佔位符）不列入，避免假陽性
            vals.append(v)
    return vals


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "events.test.geojson"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--offline", "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            check("fetch_events.py --offline 執行成功", False, f"returncode={proc.returncode}")
            return 1
        check("fetch_events.py --offline 執行成功", True)

        raw = out.read_text(encoding="utf-8")
        gj = json.loads(raw)
        feats = gj.get("features", [])

        # 基本結構
        check("輸出為 FeatureCollection 且含 meta.generated_at",
              gj.get("type") == "FeatureCollection" and bool(gj.get("meta", {}).get("generated_at")),
              f"features={len(feats)}")

        # §8c-1 TDX NewsID 67297（台21 132K+300 明隧道整點放行）
        f67297 = next((f for f in feats if f["properties"].get("source_id") == "67297"), None)
        ok = f67297 is not None
        if ok:
            p, g = f67297["properties"], f67297["geometry"]
            ok = (p["type"] == "timed"
                  and g is not None and g["type"] == "LineString" and len(g["coordinates"]) >= 2
                  and any(r.get("effect") == "release" for r in p.get("rules", [])))
            detail = (f"type={p['type']}, geom={g and g['type']}, "
                      f"rules={[r.get('effect') for r in p.get('rules', [])]}")
        else:
            detail = "找不到 source_id=67297"
        check("§8c-1 NewsID 67297 存在、type=timed、LineString、rules 含 release", ok, detail)

        # §8c-2 manual_rules 台21 夜間封閉（110K+900–145K+035，跨午夜 closed 17:30–07:00）
        fnight = next((f for f in feats
                       if f["properties"]["road"] == "台21線"
                       and f["properties"].get("from_km") == "110K+900"
                       and f["properties"].get("to_km") == "145K+035"), None)
        ok = fnight is not None
        if ok:
            rules = fnight["properties"].get("rules", [])
            ok = any(r.get("effect") == "closed" and r.get("from") == "17:30"
                     and r.get("to") == "07:00" and r["to"] < r["from"]  # to<from = 跨午夜
                     for r in rules)
            detail = f"rules={rules}"
        else:
            detail = "找不到 台21線 110K+900–145K+035"
        check("§8c-2 台21 夜間封閉存在且 rules 為跨午夜 closed 17:30–07:00", ok, detail)

        # §8c-3 台18 至少 5 筆成功解析出里程
        n18 = sum(1 for f in feats
                  if f["properties"]["road"] == "台18線"
                  and f["properties"].get("from_km") and f["properties"].get("to_km")
                  and f["geometry"] is not None)
        check("§8c-3 台18線至少 5 筆解析出里程且有幾何", n18 >= 5, f"實際 {n18} 筆")

        # §8c-4 輸出檔不含 .env 的任一值
        vals = load_env_values(ENV_PATH)
        hits = sum(1 for v in vals if v in raw)
        check("§8c-4 輸出檔反向 grep .env 值 = 0 命中",
              hits == 0 and len(vals) > 0,
              f"檢查 {len(vals)} 個值，命中 {hits}（值本身不印出）")

    print(f"\n=== 結果：{len(PASSES)} PASS / {len(FAILURES)} FAIL ===")
    if FAILURES:
        for name in FAILURES:
            print(f"  失敗：{name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
