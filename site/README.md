# site/ — 山路管制查詢站（第一階段骨架）

純靜態 HTML/CSS/JS，無 npm、無 build，函式庫全走 CDN（MapLibre GL JS 4.7.1、Turf.js 7.1.0、Inter）。

## 本機開啟

```
python -m http.server 8765 --directory "E:\climbing source\site"
```

然後開 http://localhost:8765/ 。（不能用 `file://` 直接開，`fetch` 讀不到 `data/events.geojson`。）

## 檔案

- `index.html` 版面骨架 → `style.css` 色票與元件（色票見 SPEC §2）→ `app.js` 全部邏輯。
- `data/events.geojson` 前端唯一資料來源，由 `scripts/fetch_events.py` 產生（見下方「資料更新」）。
- `data/sample-events-v2.geojson` 前端第二階段 fixture（LineString 區段＋`rules`＋`meta.generated_at`，非真實公告）。

## 第二階段功能（SPEC §7a／§7b-決議／§7d）

- **網址參數**：`?data=sample-events-v2.geojson` 覆寫 `config.dataUrl`（只接受 `data/` 下的相對檔名）。
- **區段**：事件幾何為 `LineString` 時整段上色（底 8px 半透明＋頂 3px 實線，不在路線上降到 0.35），徽章與里程藥丸放區段中點；`geometry: null` 不畫標記，只列在「其他公告」並標「（無法定位）」。
- **時間模式**：起終點下方切「出發／抵達」＋ `datetime-local`；OSRM `annotations=duration` 累積成每頂點秒數 → 每筆事件預計經過時刻，再用 `rules` 判 `closed`／`release`／`open`／`unknown`，清單頂端顯示「本次出發會遇到 N 筆管制」。
- **路線偏好：台21**：OSM 把望高隧道段標成不可通行，OSRM 一定繞台18；此模式改為 OSRM 起點→`splice.fromM` 內插點 ＋ `tw21.geojson` 子段（`splice.speedKmh` 估時）＋ OSRM 末端→終點三段拼接，起點較靠塔塔加時自動反轉，任一段失敗顯示紅色錯誤條並退回「自動」。
- `config.js` 另有 `roadLines`（里程折線路徑）、`splice`、`etaRefreshOnTimeChange` 三組設定。

## 例外時段與例假日（SPEC §9a／§9b／§9d）

- **網址參數** `?holidays=sample-holidays.json` 覆寫 `config.holidaysUrl`（與 `?data=` 同規則：只取檔名掛在 `data/` 下，含協定的網址一律用預設）；`data/holidays.json` 抓不到時退回「只算週六日」，並在 ⓘ 面板顯示「假日資料未載入」。
- **`rules[].effect` 四種**：`closed` 封閉中（紅）／`release` 時段放行（琥珀）／`lane` 車道管制中（藍，可通行但車道縮減）／`exempt` 該時段不受本事件其他規則約束，命中即顯示「不在管制時段（例假日不管制／12:00–13:00 不管制）」；判定順序 exempt → closed → release → lane，都沒命中為 open，完全沒規則為 unknown。`days` 可用 `"daily"`、`["mon",…]` 或 `["holiday"]`（週六日與國定假日，扣掉 `holidays.json` 的補行上班日）。
- **摘要「會遇到 N 筆管制」只算 `closed` 與 `release`**：`lane` 不計，`status: "ended"` 的事件不計且卡片與 popup 都不顯示「預計 … 經過」行。

## config.js 可調什麼

| 值 | 說明 |
|---|---|
| `basemapStyleUrl` | 深色底圖 style（預設 OpenFreeMap `styles/dark`）；抓不到時自動退回 `basemapRasterFallback`（CARTO dark_all） |
| `osrmBaseUrl` / `nominatimUrl` | 路線與地理編碼服務（公開 demo，請節制呼叫） |
| `geocodeViewbox` | 地理編碼優先範圍；框內找不到才放寬全台 |
| `matchDistanceMeters` | 事件距路線 ≤ 此值視為「在路線上」（SPEC §4，預設 600 m） |
| `defaultOrigin` / `defaultDestination` | 頁面載入自動規劃的起終點 |
| `dataUrl` / `mapCenter` / `mapZoom` | 資料檔路徑與初始視野 |

## 資料合約

`data/events.geojson` 的 `properties` 欄位定義見 `SPEC.md` §3（17 個欄位，不要自行增減）；
第二階段的 `scripts/fetch_events.py` 必須產出同樣結構。

## 資料更新

`data/events.geojson` 由 `scripts/fetch_events.py` 產生（TDX 公路局快訊 + 人工常態規則檔）：

```
.venv/Scripts/python.exe scripts/fetch_events.py            # 線上抓 TDX（讀 .env 憑證）
.venv/Scripts/python.exe scripts/fetch_events.py --offline  # 用離線樣本，不打網路
.venv/Scripts/python.exe scripts/test_fetch_events.py       # SPEC §8c 驗收測試
```

TDX 沒有常態性管制（例如台21夜間封閉），這類規則寫在 `scripts/manual_rules.json`：
每筆欄位同 events properties，改完更新該筆 `last_verified` 並重跑上面的指令。

- **`data/holidays.json` 怎麼更新**：`.venv/Scripts/python.exe scripts/build_holidays.py`（預設今年＋明年；來源＝data.gov.tw 資料集 14718「中華民國政府行政機關辦公日曆表」，下載連結由 dataset API 動態取得，不寫死）。政院每年公布次年行事曆後重跑一次即可；`holidays`＝放假日、`workdays`＝落在週六日的補行上班日（2026／2027 來源無補班日，故為空陣列），下載失敗時輸出空 `holidays` 並在 `source` 標明「查無」，前端退回只算週六日。
- **`rules[].effect` 語意（`parse_news.py` 產生）**：`lane`＝車道縮減但仍可通行（「封閉外側車道」「單線雙向管制通行」等，由 `is_lane_control()` 判定，除非同時出現「全線封閉／道路封閉／禁止通行」；這類公告 `type` 一律 `construction`，**不再產生 `closed`**）；`exempt`＝該時段不受本事件其他規則約束（「例假日不施工／不管制」→ `days: ["holiday"]` 全天；「中午12時至13時不管制」→ `days: "daily"` 的時段 exempt）。
