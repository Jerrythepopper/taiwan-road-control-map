# -*- coding: utf-8 -*-
"""build_holidays.py — 產生 `site/data/holidays.json`（SPEC §9d 例假日資料）。

來源：政府資料開放平台資料集 **14718「中華民國政府行政機關辦公日曆表」**
（人事行政總處 dgpa）。實際下載連結不寫死，改由 dataset API 動態取得：

    GET https://data.gov.tw/api/v2/rest/dataset/14718
      -> result.distribution[]，每個年度一個 CSV（另有「_Google行事曆專用」版本，略過）
      -> resourceDownloadUrl 指向 https://www.dgpa.gov.tw/FileConversion?filename=...

CSV 欄位（UTF-8，實測含 BOM）：`西元日期,星期,是否放假,備註`
`是否放假`：**0 = 該日要上班、2 = 該日放假**（dataset notes 原文）。
`備註` 例：`開國紀念日`、`農曆除夕`、`補行上班`。

輸出格式（SPEC §9d）：
    {"holidays": ["2026-01-01", ...],   # 是否放假 = 2 的日期（含週六日）
     "workdays": ["2026-02-07", ...],   # 落在週六日、但是否放假 = 0 的補行上班日
     "source": "<dataset 頁面 URL>", "years": [2026, 2027], "built_at": "<iso>"}

前端 `isHoliday(date)`：在 workdays → false；在 holidays → true；週六日 → true；否則 false。

抓不到資料時**不手打假日清單**：輸出空 `holidays`、`source` 寫明查無，讓前端退回只算週六日。

用法：  .venv/Scripts/python.exe scripts/build_holidays.py
        .venv/Scripts/python.exe scripts/build_holidays.py --years 2026 2027
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import io
import json
import os
import re
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_PATH = os.path.join(ROOT, "site", "data", "holidays.json")

DATASET_ID = 14718
DATASET_API = "https://data.gov.tw/api/v2/rest/dataset/%d" % DATASET_ID
DATASET_PAGE = "https://data.gov.tw/dataset/%d" % DATASET_ID

# 「115年中華民國政府行政機關辦公日曆表」→ 民國年 115；「_Google行事曆專用」版本欄位不同，排除。
ROC_YEAR_RE = re.compile(r"^(\d{3})\s*年")
SKIP_RE = re.compile(r"Google")

TIMEOUT = 120


def log(msg: str) -> None:
    print(msg)


def roc_to_ad(roc: int) -> int:
    return roc + 1911


def list_distributions() -> list:
    """回傳 [(ad_year, description, url)]，同年度取 modifiedDate 較後（列表較後）者。"""
    resp = requests.get(DATASET_API, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError("dataset API success=false")
    out = {}
    for d in data["result"].get("distribution", []):
        desc = (d.get("resourceDescription") or "").strip()
        if SKIP_RE.search(desc):
            continue
        m = ROC_YEAR_RE.match(desc)
        if not m:
            continue
        url = (d.get("resourceDownloadUrl") or "").strip()
        if not url:
            continue
        out[roc_to_ad(int(m.group(1)))] = (desc, url)  # 後出現者覆蓋前者（更新版）
    return sorted((y, v[0], v[1]) for y, v in out.items())


def parse_calendar_csv(text: str, year: int) -> tuple[list, list]:
    """回傳 (holidays, workdays)。只收該年度、格式合法的列。"""
    holidays, workdays = [], []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        raw = (row.get("西元日期") or "").strip()
        flag = (row.get("是否放假") or "").strip()
        if not raw or not flag:
            continue
        try:
            d = _dt.datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            try:
                d = _dt.date.fromisoformat(raw)
            except ValueError:
                continue
        if d.year != year:
            continue
        iso = d.isoformat()
        if flag == "2":
            holidays.append(iso)
        elif flag == "0" and d.weekday() >= 5:
            # 週六(5)/週日(6) 卻要上班 = 補行上班日（備註常寫「補行上班」）
            workdays.append(iso)
    return holidays, workdays


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    this_year = _dt.date.today().year
    ap = argparse.ArgumentParser(description="產生 site/data/holidays.json")
    ap.add_argument("--years", type=int, nargs="*", default=[this_year, this_year + 1],
                    help="要收錄的西元年（預設今年與明年）")
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    wanted = sorted(set(args.years))
    holidays: list = []
    workdays: list = []
    years_done: list = []
    source = DATASET_PAGE
    notes: list = []

    try:
        dists = list_distributions()
        log("[dataset %d] 取得 %d 個年度 CSV：%s"
            % (DATASET_ID, len(dists), "、".join(str(y) for y, _, _ in dists)))
        by_year = {y: (desc, url) for y, desc, url in dists}
        for y in wanted:
            if y not in by_year:
                notes.append("資料集尚無 %d 年（民國 %d 年）檔案" % (y, y - 1911))
                log("[skip] %d：資料集尚無該年度檔案" % y)
                continue
            desc, url = by_year[y]
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            text = r.content.decode("utf-8-sig", errors="replace")
            h, w = parse_calendar_csv(text, y)
            if not h:
                notes.append("%d 年 CSV 解析不到放假日" % y)
                log("[warn] %d：CSV 解析不到放假日（HTTP %d，%d bytes）"
                    % (y, r.status_code, len(r.content)))
                continue
            holidays.extend(h)
            workdays.extend(w)
            years_done.append(y)
            log("[ok] %d（%s）：放假 %d 天、補行上班 %d 天（HTTP %d，%d bytes）"
                % (y, desc, len(h), len(w), r.status_code, len(r.content)))
    except Exception as exc:  # 網路/WAF/格式改版都走這裡：不編造假日
        notes.append("下載或解析失敗：%s" % exc)
        log("[FAIL] 取得辦公日曆表失敗：%s" % exc)

    if not years_done:
        source = "查無（%s 下載或解析失敗，未手動填補；前端請退回只算週六日）" % DATASET_PAGE
        log("[FAIL] 沒有任何年度成功，輸出空 holidays 並在 source 標明查無")

    payload = {
        "holidays": sorted(set(holidays)),
        "workdays": sorted(set(workdays)),
        "source": source,
        "years": years_done,
        "built_at": _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
    }
    if years_done and not payload["workdays"]:
        notes.append(
            "來源 CSV 在 %s 年沒有任何『週六日仍須上班』的列（即無補行上班日），"
            "workdays 因此為空陣列，非解析失敗。"
            % "、".join(str(y) for y in years_done)
        )
    if notes:
        payload["notes"] = notes

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    log("輸出 %s：holidays %d 筆、workdays %d 筆、years %s"
        % (args.out, len(payload["holidays"]), len(payload["workdays"]), payload["years"]))
    return 0 if years_done else 4


if __name__ == "__main__":
    sys.exit(main())
