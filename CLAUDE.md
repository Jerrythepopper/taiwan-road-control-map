# 山路管制查詢站（climbing source）

兩人自用的登山去程道路管制查詢網站。第一版只做台18線（阿里山公路）、台21線（新中橫）。

- 定調規格：`SPEC.md`（改方向先改它）。UI 參考圖：`reference/ui-reference.png`。
- 資料源調查：`research/2026-09-10-data-sources-survey.md`（省道公告無座標；里程→座標靠公路局里程 CSV）。
- 目錄：`site/` 靜態前端（純 HTML/CSS/JS + CDN，無 build）；`site/data/events.geojson` 前端唯一資料檔；`scripts/` 抓資料 Python；`_proof/` 截圖與實跑證據；`_meta/OPEN_ITEMS.md` 未結事項。
- 紅線：API key 只放 `.env`／GitHub Secrets，絕不進 repo。網頁上永遠顯示資料更新時間與「僅供參考，請看官方公告」。
- 選型已定（MapLibre + OpenFreeMap/CARTO 深色底圖 + OSRM demo + Nominatim + Turf），不重選。
