# OPEN_ITEMS
- [ ] 使用者確認 TDX 帳號是否可用、取得 client id/secret 放進 `.env`（使用者親自做）
- [ ] TDX 省道事件 API 是否含座標：開工後第一個要實測的假設（見 research A1/架構影響 #5）
- [ ] 骨架單截圖給使用者點頭後才派資料單
- [ ] OSRM demo 水里→塔塔加 走台18 不走台21（OSM 可能把和社–塔塔加段標為不可通行）：資料單前確認 OSM 現況；必要時加「途經點」或改 ORS
- [ ] 2026-09-10 verifier 誤用 `taskkill /F /IM chrome.exe`，可能關掉使用者的 Chrome；之後驗收單禁區加「不得 taskkill 全域瀏覽器行程，headless 用獨立 --user-data-dir 與 --remote-debugging-port 自行關閉」
- [x] parse_news：車道封閉→construction＋effect lane；例假日/中午不管制→effect exempt＋holidays.json（2026-09-10 23:40 完成）
- [x] tw21 折線終點已重指派到 145K+035（規則 2；144K–145K 段幾何被拉伸 2.7 倍，該區間定位誤差可達數百公尺，已知）
- [ ] TDX News 無深連結，source_url 目前退回 168 首頁；找公路局公告的可連結 URL 模式
- [x] app.js `?data=`/`?holidays=` 改為只取 basename
- [x] status=ended 不再顯示 ETA 行、不計入摘要
- [x] 第三階段：repo https://github.com/Jerrythepopper/taiwan-road-control-map 已建、Pages 已上線 https://jerrythepopper.github.io/taiwan-road-control-map/ （2026-09-10 23:15）
- [x] Secrets 已設、update-data workflow 手動觸發成功（2026-09-10 23:18，run 34494699958）

## 待辦（使用者 2026-09-10 23:23 定案：先擺著）
- [ ] 拼接路段時速 30 km/h 為估算；根本解＝使用者到 OSM 修 way 1120485630（access=no/highway=service/old_ref=21）→ OSRM 約一週後自動走台21，拼接可退役
- [ ] 公告按鈕深連結：TDX 無 URL，只能拿標題到公路局站搜，命中率未知
- [ ] 加其他路線（候選：台14甲、台8、台20）：build_roads 吃路線清單、fetch_events 路名清單、前端 chip 改讀 config、各線常態管制研究
- [ ] 縣道／林道（郡大林道等）不在省道里程資料內，需另一種資料源
