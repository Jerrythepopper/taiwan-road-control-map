# 山路管制查詢站 — 定調規格（SPEC）

> 使用者與主對話 2026-09-10 討論定案。實作單一律引用本檔，不憑記憶重述。
> 對象：兩人自用（登山去程）。第一版只做 **台18線（阿里山公路）** 與 **台21線（新中橫）**。

## 0. 一句話

設定起點與終點 → 地圖畫出開車路線（綠色發光線）→ 路線上落在管制範圍內的省道公告以標記顯示 → 點標記或左側清單看詳細管制內容與官方公告連結。

## 1. 技術選型（已定，不重選）

| 層 | 選擇 | 理由 |
|---|---|---|
| 前端 | 純靜態 HTML/CSS/JS，CDN 載入，**不用 bundler、不用 npm build** | 兩人自用、GitHub Pages 直接放 |
| 地圖 | MapLibre GL JS（CDN） | 免費、向量、深色底圖好看 |
| 底圖 | 優先 OpenFreeMap 深色 style；若無深色 style 則用 CARTO `dark_all` raster tiles | 免費零 key |
| 路線 | OSRM 公開 demo（`router.project-osrm.org`，driving profile，geometries=geojson） | 免 key；每秒 ≤1 次 |
| 地理編碼 | Nominatim（`countrycodes=tw`），另可直接點地圖設起終點 | 免 key |
| 空間比對 | Turf.js（CDN）`pointToLineDistance` | 前端就能做 |
| 資料 | `site/data/events.geojson`（由 `scripts/` 定時產生） | 前端只讀一份檔 |
| 資料抓取 | Python 3 script（第二階段） | 公路局施工公告 + 里程座標 CSV + TDX（可選）+ 消防署災情 |
| 排程與託管 | GitHub Actions cron + GitHub Pages（第三階段） | 免費 |

依據：`research/2026-09-10-data-sources-survey.md`（省道公告無座標；里程→座標用公路局「省道里程坐標」CSV 查表，公里級精度）。

## 2. UI 定調（參考圖 `reference/ui-reference.png`，照它的結構與氣質做）

整體：全視窗深色 App，**左側欄約 400px 固定寬，右側地圖填滿**。圓角大卡片、細邊框、柔和發光。

### 色票（token，寫進 CSS 變數）
- 背景 `--bg: #0f0f10`；側欄／卡片 `--panel: #1a1a1b`；浮起卡片 `--card: #202022`
- 邊框 `--line: #2c2c2e`；主文字 `--fg: #f2f2f2`；次文字 `--muted: #9a9a9c`
- 強調（路線線條、「開放」狀態、選中卡片外框）`--accent: #5ce0b8`
- 狀態色：封閉 `--red: #ff5c5c`、時段管制 `--amber: #ffb547`、施工 `--blue: #6fa8ff`
- 字型 Inter（Google Fonts），fallback `system-ui, "Noto Sans TC", sans-serif`

### 左側欄（由上到下）
1. 標題列：小圖示圓框 + 站名「山路管制」+ 右側 ⓘ（點了顯示資料更新時間與免責：僅供參考，出發前請看官方公告）。
2. 起點／終點兩個輸入框（placeholder「起點」「終點」），右邊一顆「⇅ 交換」，下方一顆主按鈕「規劃路線」。輸入後按 Enter 或按鈕 → 地理編碼 → 畫路線。也支援「點地圖設起點／終點」兩個小按鈕（點下後下一次地圖點擊設定該點）。
3. 篩選列（像參考圖的 Show me / Sort by）：「只看進行中」toggle chip、「路線：台18 / 台21 / 全部」chip。
4. 事件清單：卡片列表。每張卡片＝左邊圓形圖示（依類型上色：封閉紅／時段管制琥珀／施工藍）＋標題（`台21線 118K+500 – 120K+000`）＋副標（`封閉 • 至 09/15` 或 `每日 07:00–17:00 整點放行`）。
   - 落在目前路線上的事件排前面且正常亮度；**不在路線上的事件放在下方「其他公告」段落，變暗顯示**（像參考圖最下面那張 Converse）。
   - 選中的卡片：綠色（accent）外框＋微光，同時地圖飛到該標記並開 popup。

### 右側地圖
- 深色底圖；路線＝兩層線（底層寬 10px、accent 色、opacity 0.25；上層寬 4px、accent 色實線）→ 發光感。
- 起點／終點：小圓點標記（起點 accent、終點白）。
- 事件標記：圓形徽章（類型色底＋白色符號：封閉「✕」、時段管制「◷」、施工「⚠」），徽章下方一顆小藥丸標籤寫里程（例 `118K+500`），像參考圖的分數藥丸。
- Popup 卡片（深色，圓角 16px）：標題列（圖示＋路線里程＋副標）→ 三格 meta 列（狀態／時段／更新時間）→ 一句摘要（粗體）→ 詳細說明（bullet）→ 一顆全寬按鈕「查看官方公告」（開新分頁到 `source_url`）。

## 3. 資料合約（`site/data/events.geojson`）

FeatureCollection；每個 Feature 為 `Point`（第一版；第二階段可能加 `LineString` 表示區間）。`properties`：

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | string | 穩定唯一值（來源+路線+里程 hash） |
| road | string | `台18線` / `台21線` |
| direction | string | `雙向` / `往山上` / `往山下`，未知留空 |
| from_km, to_km | string | 里程樁號原文，如 `118K+500` |
| type | enum | `closure` / `timed` / `construction` |
| status | enum | `active` / `scheduled` / `ended` |
| title | string | 一行標題 |
| summary | string | 一句摘要 |
| description | string | 詳細內容（可多行） |
| schedule | string | 時段管制文字，例 `每日 07:00–17:00，每整點放行 10 分鐘` |
| start_date, end_date | string | ISO 日期，未知留空 |
| source_name, source_url | string | 來源名稱與連結 |
| fetched_at | string | ISO 時間 |
| geom_precision | string | `milepost-csv`（公里級）/ `exact`（自帶座標）/ `manual` |

第一階段用 `site/data/events.geojson` 放 **手工樣本**（4～6 筆，台18 與台21 各半，含三種 type），欄位齊全，座標用下列參考點附近：
塔塔加 (120.8863, 23.4877)、阿里山 (120.8030, 23.5100)、石桌 (120.7060, 23.4620)、觸口 (120.5950, 23.4150)、信義 (120.8550, 23.6980)、水里 (120.8540, 23.8120)、和社 (120.8800, 23.6150)。

## 4. 路線↔事件比對規則

- 事件點到路線 LineString 的距離 ≤ **600 m** → 視為「在路線上」（公里級定位精度所以放寬）。
- 「在路線上」的事件依「沿路線的位置」排序（用 turf `nearestPointOnLine` 的 `location`）。
- 沒有路線時清單顯示全部事件，順序依 road 再依 from_km。

## 5. 階段切分（一單一階段）

1. **骨架單**：靜態站＋樣本資料，完整 UI 與路線規劃、比對、popup 可動。截圖給使用者點頭。
2. **資料單**：`scripts/fetch_events.py` 產生真實 `events.geojson`（公路局施工公告 → 里程 CSV 查座標；消防署災情；TDX 可選，key 從環境變數讀）。
3. **上線單**：GitHub Actions cron + Pages + 保活 commit。

## 6. 完工定義（各階段共用）

- 檔案 read-back 存在且行數合理；瀏覽器實開無 console error；**截圖人眼可辨**且各截圖 hash 互異。
- 不得把任何 API key 寫進 repo；key 一律 `.env`（已在 .gitignore）或 GitHub Secrets。

## 7. 2026-09-10 晚間增修（使用者看過骨架後定調）

### 7a. 出發／抵達時間與管制時段比對（像 Google Maps 的「出發時間」）
- 左欄起終點下方加一列：「出發時間」預設現在，可切「希望抵達」模式；用 `datetime-local` 輸入。
- OSRM 請求加 `annotations=duration`，前端沿路線累積秒數 → 任一事件點（用 `nearestPointOnLine` 的 index/location）可算出**預計經過時刻 ETA**。抵達模式＝總時長回推出發時刻。
- 事件 `properties` 新增結構化欄位 `rules`（陣列），每條 `{ "days": "daily" | ["mon",...], "from": "HH:MM", "to": "HH:MM", "effect": "closed" | "release", "note": "" }`；跨午夜（如 20:00–06:00）允許 `to < from`。`release` 表示該時段內定時放行（原文放 `note`，如「每整點放行 10 分鐘」）。
- 判定：對事件在 ETA 時套用 `rules` → `closed`（封閉中）/ `release`（時段放行）/ `open`（不在管制時段）/ `unknown`（無結構化規則，只有文字）。
- 顯示：卡片副標與 popup 加一行「預計 14:32 經過 → 封閉中（20:00–06:00）」，狀態色照 closed 紅／release 琥珀／open accent／unknown muted。清單頂端摘要加「本次出發會遇到 N 筆管制」。
- 沒有路線或沒有 ETA 時退回現況顯示（第一階段行為）。

### 7b. 路線要能走台21
- 加「途經點」：起終點之間可加最多 3 個途經點（輸入或點地圖），送 OSRM 多點路線。
- 若 OSM 把台21 和社–塔塔加段標為不可通行（待 `research/2026-09-10-route-and-current-controls.md` 確認），則：優先方案＝前端提供「路線偏好：台21 / 台18」chip，用內建途經點（如東埔／和社與塔塔加之間的中繼點）強制；若 OSRM 仍拒絕通行，改用 OpenRouteService（需免費 key，放 `config.js` 讀 `window.ORS_KEY` 或 `.env` 轉出的 `site/keys.js`，且 `keys.js` 進 .gitignore）。

### 7c. 資料單驗收測試案例
- 第二階段 `scripts/fetch_events.py` 產出的 `events.geojson` **必須包含台21 現行夜間管制**（使用者口述），來源與格式見 `research/2026-09-10-route-and-current-controls.md` Q2。

### 7d. 管制區段整段標記（使用者 22:29 補充）
- 事件幾何從 `Point` 改為 **`LineString`（from_km→to_km 沿省道實際線型）**，徽章與里程藥丸放在區段中點；舊的 Point 只在拿不到線型時退回使用。
- 線型來源：公路局「省道公路路線圖資」（data.gov.tw id 105020，SHP，含路線里程）→ `scripts/` 離線切出台18、台21 每 100 m 一點的里程折線 `site/data/roads/{tw18,tw21}.geojson`（屬性含累積里程）；事件的 from_km/to_km 直接在這條折線上內插取子段。里程牌 CSV 只做校正與退路。
- 地圖畫法：區段疊在路線上方，寬 8px、類型色（封閉紅／時段管制琥珀／施工藍）、半透明底＋實線頂層；未在路線上的區段仍畫但 opacity 降到 0.35。
- 路線↔事件比對改為「事件區段與路線的重疊長度 > 0 或最近距離 ≤ 600 m」；ETA 取區段起點（往山上）／終點（往山下）方向對應的一端，方向未知取中點。
- 里程藥丸文字改為 `118K+500 – 120K+000`。

### 7b-決議（2026-09-10 22:40，依 research/2026-09-10-route-and-current-controls.md Q1）
- 事實：OSM 在台21 望高隧道附近（way 1120485630）標 `access=no`、`highway=service`、`old_ref=21`，切斷和社–塔塔加；OSRM 與 ORS 都吃同一份 OSM，途經點救不了。
- 決議：**前端「路線偏好：台21」＝拼接路線**。步驟：①OSRM 起點→台21 110K 附近拼接點（座標由 `tw21.geojson` 內插）②直接取 `tw21.geojson` 110K→145K 子段當路線幾何，時長用 30 km/h 估算③OSRM 145K（塔塔加）→終點。三段合併成一條 LineString，`annotations` 秒數同樣拼接。反向（下山）對稱。
- 「路線偏好：自動」＝純 OSRM（現況）。ORS 暫不接（同樣受 OSM 影響），`.env` 的 ORS key 先閒置。
- 附帶：OSM 那條 tag 可能是舊線改隧道後的殘留，日後可由使用者自行到 OSM 修正，不在本專案範圍。

## 8. 資料層設計（2026-09-10 22:45，依 research/2026-09-10-tdx-probe.md 與 route-and-current-controls.md）

### 8a. 事實
- TDX `GET /v2/Road/Traffic/Live/News/Highway` 可用（token 實測 200），全量約 196 筆公路局快訊，台18 約 12 筆、台21 約 8 筆；**無座標、無結構化里程**，路名與 `132K+300` 這類里程是 Title/Description 自由文字。
- TDX 只含臨時性施工／事故快訊，**不含台21 夜間封閉這種常態規則**（110K+900–145K+035，每日 17:30–翌日 07:00，自 2013 起）。
- 168 施工查詢頁互動失敗；公路局公告頁與阿里山國家風景區彙整頁可讀但為 HTML 文字。

### 8b. 兩個來源、一支 script
`scripts/fetch_events.py`（用 `.venv`）產出 `site/data/events.geojson`：
1. **TDX 快訊**：讀 `.env` 取 token → 抓 `News/Highway` → 只留 Title/Description 含「台18」「台21」（含全形、「台 18 線」「臺18」變體）→ 正則解析：
   - 里程：`(\d+)[Kk]\+?(\d{3})?` 序列，取第一個為 from、第二個為 to（只有一個＝點事件，to=from）。
   - 時段規則：`每日|每天` + `(\d{1,2})[:：時](\d{2})?` 區間 → `rules[]`；「整點放行 N 分鐘」「每半點」→ `effect:"release"` 並保留原文於 `note`；「封閉|禁止通行|全線封閉」無時間→ `closed` 全天；「夜間」+時間→跨午夜 closed。
   - 日期：民國 `(\d{3})年(\d{1,2})月(\d{1,2})日` 或 `115/1/20` 或西元；區間「自…至…」→ start/end。
   - type：含「封閉|禁止通行」→ closure；含「放行|管制時段|時段」→ timed；其餘→ construction。
   - status：今天在 [start,end] → active；start 在未來→ scheduled；end 已過→ ended；無日期→ active。
   - 解析不到里程的公告仍輸出（`geometry: null`，`parse_warnings[]` 記原因），前端列在「其他公告」。
2. **常態規則檔** `scripts/manual_rules.json`（人工維護，每筆含 source_url、last_verified）：第一版至少含台21 夜間封閉；格式與 events 相同但由人寫。
3. **幾何**：from/to 里程 → 在 `site/data/roads/tw18|tw21.geojson` 上內插子段 → `LineString`（點事件→前後各 100 m 的短段）；`geom_precision: "route-interp"`。
4. **id**：`sha1(source + road + from_km + to_km + title)[:12]`；TDX 另存 `source_id: NewsID`。
5. 輸出附 `meta: { generated_at, sources: [{name, fetched_at, count}] }`（放在 FeatureCollection 頂層自訂欄位）。
6. Log 摘要印到 stdout：各來源筆數、解析成功／警告數、台18/台21 各幾筆。

### 8c. 資料單驗收測試（必過）
- events.geojson 含 TDX NewsID 67297（台21 132K+300 明隧道白天整點放行）且 type=timed、幾何為 LineString、rules 至少一條 release。
- 含 manual_rules 的台21 夜間封閉（110K+900–145K+035）且 rules 為跨午夜 closed 17:30–07:00。
- 台18 至少 5 筆成功解析出里程。
- 不含任何 token/secret；`.env` 未動。
