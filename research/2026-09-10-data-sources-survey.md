# 台灣登山去程道路管制查詢網站 — 資料源與工具調查

調查日期：2026-09-10
調查方式：官方頁面實際開啟（含 data.gov.tw 資料集頁面逐筆開啟）、TDX 原始 OpenAPI (Swagger JSON) 文件實抓、GitHub репо/程式碼實讀、WebSearch 交叉比對。
標記說明：**[文件]** = 官方文件白紙黑字寫的；**[實測]** = 本次調查實際打開頁面/API看到的；**[推斷]** = 根據間接證據推論，未親眼證實。

---

## A1. TDX 運輸資料流通服務平台 — 道路事件／省道即時路況

- **認證方式** [文件]：OIDC Client Credentials。Token endpoint `https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token`，需先註冊會員（Email 驗證+人工審核通過）才能在會員中心產生 Client ID / Secret（最多3組）。
  來源：https://motc-ptx.gitbook.io/tdx-xin-shou-zhi-yin/api-shi-yong-shuo-ming/api-shou-quan-yan-zheng-yu-shi-yong-fang-shi
- **免費額度／頻率限制** [文件]：未加入會員 50次/日；一般會員 20,000次/日；呼叫頻率上限為每個來源IP每秒50次（不分API Key，未來會改成依訂閱等級的API Key配額）。
  來源：https://tdx.transportdata.tw/topic/detail/358ad884-2e3a-4ff2-9b85-4c4a7b9bb1ba ；https://tdx.transportdata.tw/statistics
- **「路況資訊v2」API 分類** [實測，直接抓到原始 OpenAPI JSON]：
  UUID `7f07d940-91a4-495d-9465-1c9df89d709c`，實際下載網址 `https://tdx.transportdata.tw/webapi/File/Swagger/V2/{uuid}` 可取得完整 OAS3 JSON（Swagger UI 網頁本身是 Vue 前端渲染，WebFetch/一般抓取工具看不到內容，必須用這個原始檔網址）。
  端點清單（節錄，全部在 `/v2/Road/Traffic/...` 之下）：
  `VD/City/{City}`、`CMS/City/{City}`、`CCTV/City/{City}`、`ETag/City/{City}`、`ETagPair/City/{City}`、`Section/City/{City}`、`SectionShape/City/{City}`、`Live/City/{City}`、`CongestionLevel/City/{City}`、**`Live/News/City/{City}`**（回傳型別 `LiveNews`，即路況新聞/事件通報）。
  文件開頭寫「本平臺提供涵蓋全國尺度之路況設備資料」[實測見到的原文]，但實際端點都以 `{City}` 為查詢鍵；是否涵蓋跨縣市的省道路段（公路局管轄）**未能在本次調查中完整驗證**——[推斷] 官方另有「TDX Event（道路事件）」MCP 服務，說明文字明寫「提供查詢縣市道路、省道與高速公路道路事件查詢」（來源：https://github.com/tdxmotc/MCP ，MCP URL `https://tdx.transportdata.tw/tdx-mcp/event`），顯示 TDX 生態系內確實有涵蓋省道的事件查詢能力，但其底層對應哪一支確切 REST 端點、欄位是否含經緯度，**本次未能抓到該分類的完整 schema，查無明確答案**，禁止進一步推測。
  另外找到 `交通部道路交通事件填報系統管理後台`（`traffic.transportdata.tw/Event_backend/`），顯示 TDX 背後確實有一個跨機關（縣市/公路局/國道）的事件填報系統在餵資料，但後台頁面本身回傳 406，未能檢視內容。
- **省道即時路況官方 App「幸福公路」** [文件/實測（App Store頁面文字）]：由公路局開發，會把「施工資訊」標在地圖上，代表公路局內部確實握有把里程事件轉成地圖座標的能力，但這是App內部邏輯，不代表對外有開放API。來源：https://apps.apple.com/us/app/%E5%B9%B8%E7%A6%8F%E5%85%AC%E8%B7%AF/id604698360

**A1 結論：TDX 有結構化、需註冊、免費額度足夠的道路路況/事件類 API，且明確存在「城市為查詢鍵」的 Live/News 事件端點；但「省道專屬、保證含經緯度」的事件端點本次查無法100%鎖定並看到欄位表，這點對架構有風險，建議實際申請TDX帳號後用 `Live/News/City/{City}` 對省道所在縣市跑一次真實請求驗證。**

---

## A2. 公路局 168 即時路況（168.thb.gov.tw）

- **168.thb.gov.tw 網站本身** [實測]：受 Incapsula 機器人防護阻擋，自動化瀏覽器讀取回傳「Request unsuccessful. Incapsula incident ID」，無法直接檢視頁面內容或內部API呼叫（依安全規範不嘗試繞過機器人防護）。
- **www.thb.gov.tw「施工路段查詢」頁**（資料來源即為168網站的「交通資訊>施工路段」）[實測，成功開啟並讀到真實列表]：
  純 HTML 表格，逐筆列出「施工地點」文字＋「發布日期」，**沒有任何座標欄位、沒有JSON/API/下載連結**。範例真實資料（2026-09-10 當日）：
  「台1己線西向0K+500竹南路段，於內外車道進行路面ac破損切割修復」
  「台21線雙向20K+700國姓路段，於全車道進行公路及橋梁維修改善及災害搶修工程」
  → **這直接證實了使用者最擔心的假設：省道施工/管制公告只給「路線＋方向＋里程樁號＋地名文字」，不給經緯度座標。** 共339頁（每頁10筆），資料每日更新（今天日期的資料已在列表最前）。
  來源：https://www.thb.gov.tw/NewsConstructionRoad.aspx?n=353
- **公路局開放資料集目錄**（www.thb.gov.tw/News_thbOpenData.aspx?n=13&sms=13658）[實測]：共92頁資料集列表，逐頁瀏覽會很花時間，故改用 data.gov.tw 全文檢索交叉比對（見 A4/A6）。
- **內部未公開API線索** [推斷，來自第三方GitHub gist整理]：`www.thb.gov.tw/api/GetExpressways`、`GetExpresswayInterchangeSet`、`GetAllExpresswayStakeSet` 等為快速公路網站前端在用的內部JSON端點，非正式公開文件化API，能否穩定使用、有無限流未知。來源：https://gist.github.com/lyshie/385244be22be697f2e1ef9f123f87859

**A2結論：168/施工路段查詢＝只有網頁表格＋純文字里程地名，無公開JSON/GeoJSON、無座標。這與A1的TDX資料應是同源（TDX的Event/News很可能就是從這個系統轉出），所以座標問題的真正解法在A6，而非A2本身。**

---

## A3. 林業及自然保育署「台灣山林悠遊網」（recreation.forest.gov.tw）林道資訊

- **山林悠遊網開放資料頁**（`recreation.forest.gov.tw/Service/OpenData`）[文件，來自搜尋結果摘要，頁面本身為前端渲染SPA未能直接文字擷取]：提供國家森林遊樂區、平地森林園區、自然步道、林業軌道等資料介接，另有PDF說明檔列出欄位。
- **data.gov.tw「林道分布圖」資料集**（id 38213）[實測，完整讀到頁面內容]：
  提供機關：農業部；格式：**KML/KMZ、SHP**；更新頻率：**不定期**；上架 2016-11-25；免費。
  涵蓋81條林道，欄位含：林道名稱、主支線、地區分署、公路專線、林道規格/種類、開設年份、縣市/鄉鎮/村里、起點/終點X/Y坐標、車行長度、步行長度、中斷長度、路面鋪面種類、**管制點**、集水區、進入林班地里程、Shape長度等。
  → 有「管制點」欄位，但依欄位描述是文字/線段屬性而非獨立經緯度點；且使用者留言反映（2024-03）部分林道座標順序與里程方向不一致，機關回覆正在修正中，代表資料品質需要抱持保留態度。
  來源：https://data.gov.tw/dataset/38213
- **林道清單**（林道分布圖頁面「相關資料集」提到，未逐一開啟細查）：可能是純文字清單，非本次驗證重點。

**A3結論：林道有整體路線圖資（KML/SHP含起訖座標），但「林道管制」本身（例如颱風後封閉、雨季管制）在 data.gov.tw 查無專門即時資料集，只能靠山林悠遊網或各林管處網頁公告（文字型）。**

---

## A4. 政府資料開放平台（data.gov.tw）搜尋結果彙整

以下皆為[實測]（直接開啟data.gov.tw資料集頁面讀取欄位/格式/更新頻率），是本次調查最有價值的一批發現：

| 資料集 | 提供機關 | 格式 | 更新頻率 | 有座標？ | 連結 |
|---|---|---|---|---|---|
| 省道里程坐標(里程牌標誌) | 交通部公路局 | CSV | 每1月 | **有**（TWD97 + WGS84經緯度） | https://data.gov.tw/dataset/7040 |
| 省道公路路線圖資 | 交通部公路局 | CSV＋壓縮檔(SHP) | 不定期 | 有路線幾何（線） | https://data.gov.tw/dataset/105020 |
| 國道及省道(含快速公路以上)道路中線 | — | — | — | 有路線幾何 | https://data.gov.tw/dataset/73232 |
| 交通災情通報表（道路、橋梁部分） | 消防署(EMIC) | **JSON** | 不定期(災害觸發) | **有**：災害點座標＋前/後管制點座標各一組 | https://data.gov.tw/dataset/77182 |
| 省道速限圖資 | 公路局 | — | — | 有線型圖資 | https://data.gov.tw/dataset/105021 |
| 省道交控路側設備資料 | 公路局 | — | — | 未查 | https://data.gov.tw/dataset/29817 |
| 林道分布圖 | 農業部 | KML/KMZ/SHP | 不定期 | 有起訖點座標 | https://data.gov.tw/dataset/38213 |
| 申請進入山地管制區統計資料 | 警政署 | — | — | 僅統計數字，非結構化管制範圍 | https://data.gov.tw/dataset/41416 |

「請開放台灣入山資料」為一則**使用者建議(suggests)**，非正式資料集（來源 https://data.gov.tw/suggests/32200 ），代表入山申請本身**目前查無結構化開放資料**，僅一站式服務網（見A5）供人工申請。

data.gov.tw 站內搜尋框本身在自動化瀏覽器操作下多次回傳「沒有相符的搜尋結果」（疑似前端搜尋behaviour與人工輸入不同步），因此本節改用 Google `site:data.gov.tw` 搜尋交叉驗證每個結果都有實際開啟頁面確認存在。

---

## A5. 國家公園（太魯閣、玉山、雪霸）與警政署入山入園

- **臺灣登山申請一站式服務網**（`hike.taiwan.gov.tw`）[文件]：整合玉山、雪霸、太魯閣國家公園入園申請＋警政署入山申請＋林業保育署路線資訊。背後採用國發會 OAS3「共通性應用程式介面規範」在各機關間（警政署、林務局、營建署）做系統整合。**這個API是機關間後端對接用，未查到對一般開發者開放的公開端點文件**。
  來源：https://pdis.nat.gov.tw/zh-TW/blog/我們如何為登山申請打造一站式服務系統/
- **太魯閣/玉山/雪霸生態保護區申請**（如 www.taroko.gov.tw）[文件]：均是線上申請表單＋審核結果查詢頁面，**沒有公開資料集**可查「目前哪些路線/山屋被管制/額滿」。
- **警政署入山申請系統**（`nv2.npa.gov.tw`）[文件]：同樣是申辦表單系統，查無開放資料或公開查詢API。

**A5結論：國家公園與警政署這條線，全部是「申請表單＋人工/半自動審核」性質，沒有結構化開放資料可介接，只能靠爬公告頁或人工查詢。**

---

## A6.（關鍵問題）里程換座標：有沒有現成資料？

**結論：有，而且不只一種，這點推翻了「省道公告只有里程沒有座標就沒救了」的最壞假設——但公告本身（A2）確實不含座標，需要另外做里程↔座標轉換。**

1. **靜態資料集：「省道里程坐標(里程牌標誌)」**（data.gov.tw id 7040）[實測，完整讀到頁面全文]
   - 提供機關：交通部公路局；格式：**CSV**；更新頻率：**每月**；免費；2017年上架。
   - 欄位表（*為標準欄位）：

     | 欄位 | 說明 |
     |---|---|
     | 公路編號、公路編碼 | 路線代碼 |
     | 隸屬縣市、隸屬鄉鎮、隸屬村里 | 行政區 |
     | 管養單位、管養工務段 | — |
     | 調查日期 | date |
     | 坐標-X-TWD97、坐標-Y-TWD97 | TWD97平面座標 |
     | 坐標-E-WGS84、坐標-N-WGS84 | **WGS84經緯度** |
     | 坐標（z公尺） | 高程 |
     | 起點樁號 | 如 `72K+087`，即里程樁號 |
     | 設置位置、編號、種類、性質、牌面內容、現況、是否為公路局設置、備註、牌面方向 | 里程牌本身屬性 |

   - 精度限制 [實測，來自資料集頁面公開的使用者意見與官方回覆]：里程牌是實體整公里/半公里/百公尺牌，非連續里程；使用者回報過現地座標與圖資座標誤差可達50公尺以上（台9線190K案例），部分路段（如台61線）樁號與牌面內容落差達7.5公里（重編路線導致），公路局回覆屬「現場設置條件造成的合理誤差」，且蘇花改等路線重編後有滯後更新問題。**這代表拿這份資料做「里程→座標」查表，精度是公里等級、不是公尺等級，且遇到路線剛改編時可能有幾公里的資料延遲。**
   - 下載：`https://www.thb.gov.tw/Common/ThbOpenDataService.ashx?SN=484&format=4&rel=156905`（CSV）
   - 來源：https://data.gov.tw/dataset/7040

2. **線型資料集：「省道公路路線圖資」**（data.gov.tw id 105020）[實測]：SHP/CSV，含每條省道（含快速公路）完整路線軌跡（線幾何）＋路線里程屬性，可以拿來把任意里程點用「沿線內插」算出座標（比單純查最近里程牌準，但仍要自己寫內插程式）。更新不定期，2026年2月剛因蘇花公路路線調整更新過一次。來源：https://data.gov.tw/dataset/105020

3. **動態API：TDX「路段編碼」(Road Section Encoding)** [實測，直接抓到原始OpenAPI JSON，UUID `e2718568-e098-4714-ac7d-7fa7d551e613`]
   - 關鍵端點：`GET /v2/Road/Link/RoadClass/{RoadClass}/Mileage/{RoadName}/{Direction}/{FromMileage}/to/{ToMileage}` → 回傳 `LinkID`＋`StartMile`/`EndMile`；再用 `GET /v2/Road/Link/Shape/Geometry/GeoJson/{LinkID}` 拿到該路段線型座標（GeoJSON）。
   - 反向：`GET /v2/Road/CNode/GeoLocating/Coordinate/{locationX}/{locationY}/{Range}`（座標→最近路口節點，搜尋半徑上限500公尺），可做「座標→里程」的近似反查。
   - 限制：沒有「輸入里程直接吐一個經緯度點」的單一端點，要組合兩支API；回傳的是路段(Link)層級的起訖里程，不是精確到公尺的單點；需要TDX帳號授權（見A1）。
   - 來源（原始OAS3文件）：https://tdx.transportdata.tw/webapi/File/Swagger/V2/e2718568-e098-4714-ac7d-7fa7d551e613

**A6總結：省道公告本身不含座標（A2已證實），但公路局至少提供三條可行的里程→座標轉換路徑：① 每月更新的里程牌CSV（最簡單，公里級精度，直接查表）②路線SHP＋自寫內插（精度較好但要自己算）③TDX路段編碼API（官方動態查詢，需要組合呼叫、需要註冊）。對兩人自用專案，方案①（CSV查表/最近點）性價比最高，先做，不夠精準再上③。**

---

## B1. Google Maps Platform（2026）

- **計價方式** [文件，來自2026年多篇第三方定價彙整文章交叉比對，非Google官方頁面逐字截圖]：Google已於2025年底以「訂閱制」（Starter/Essentials/Pro等，約$100~$1200/月）搭配「每SKU免費額度」取代舊制「每月$200美金額度打通用」的模式。Essentials類SKU（含Dynamic Maps、Static Maps、Geocoding）約有每月10,000次免費事件，Pro類（含Directions/Routes等）約5,000次免費事件，Directions API本身列為Legacy服務，價格約$5/1,000次請求。**此為第三方部落格整理，非本次直接截官方定價頁證實，建議實作前務必自行登入Google Cloud Console核對最新價格（此類定價近年變動頻繁）。**
- **道路封閉資訊** [推斷/查無明確官方文件]：搜尋結果中出現「Routes API回傳事故/施工/封閉類型與精確經緯度」的說法，但來源是第三方API整合服務網站的行銷文字，並非Google官方文件的原文引用，**本次未能在Google官方developers.google.com文件中直接找到「公開結構化道路封閉列表」這項功能的官方確認，查無法證實**。已知的官方管道是「Waze Partner Feed」，讓機關單位「餵」封路資料給Waze/Google Maps顯示，但那是資料提供方向（政府→Google），不是開發者可以「查詢」封路清單的API。
  來源：https://developers.google.com/waze/data-feed/road-closure-information

**B1結論：Google Maps Platform可以拿來做底圖/路線規劃，但（a）2026年計價制度變動大需要自己重新核價（b）沒有查到官方對外公開的「結構化封路查詢API」，封路資訊只在Google自家App內顯示，開發者拿不到。且台灣林道/產業道路在Google路網資料完整度上通常也不夠。**

---

## B2. 免費 OSM 方案

- **底圖**[文件]：OpenFreeMap（完全免費、免API key、MapLibre GL相容）是目前最無負擔的選項；Carto底圖免費額度為每月500萬次tile請求。
- **OSRM 公開demo server**（router.project-osrm.org）[文件，來自官方GitHub Wiki的API Usage Policy]：僅供「合理、非商業」用途；**不得超過每秒1次請求**（服務整體上限5000請求/分鐘）；不保證上線時間、延遲或資料更新；若商業使用需公開可存取且附上正確歸屬，**禁止轉售存取權**；官方可隨時無理由收回存取權限。
  來源：https://github.com/Project-OSRM/osrm-backend/wiki/API%20Usage%20Policy
  → 對兩人自用網站，demo server技術上夠用，但長期穩定性不受保證，建議把「換成自架OSRM或收費服務」列為已知風險而非現在就做。
- **OpenRouteService免費方案**[文件，來自官方restrictions頁面＋第三方定價彙整交叉比對]：官方restrictions頁只列「單次查詢」限制（如Directions單次最遠6000公里、Isochrones最多5個點/10個級距/120公里範圍、Matrix最多3500個位置），未在該頁列出每日/每分鐘配額；第三方資料彙整指出免費方案約為**每日2,000～2,500次請求、每分鐘40次並行**（各服務共用同一份配額）。建議實作前直接登入官方帳號後台核對目前實際數字。
  來源：https://openrouteservice.org/restrictions/ ；https://account.heigit.org/info/plans（此頁為前端渲染，未能直接文字擷取）

**B2結論：底圖用OpenFreeMap/OSM系免費且無金鑰即可上線；路線規劃兩人自用量，OSRM demo或OpenRouteService免費key都足夠，OpenRouteService較穩定（有明確帳號與配額），OSRM demo較簡單但屬於「借用他人資源看臉色」性質。**

---

## B3. 免費託管與排程

- **GitHub Pages + GitHub Actions** [文件]：公開(public)repo的Actions分鐘數無限制（免費）；`schedule.cron`最短間隔為**5分鐘**（設更短會被靜默忽略、不會報錯也不會跑）；**排程workflow在repo連續60天無任何commit活動後會被GitHub自動停用**，需要不定期有真人commit或用一個「保活」workflow定期提交才能維持排程長期運作。
  來源：https://devactivity.com/insights/github-actions-cron-schedules-a-hidden-free-tier-hurdle-impacting-developer-productivity/ ；https://cronuru.com/guides/github-actions-scheduled-workflows
- **Cloudflare Workers/Pages** [文件]：免費方案為**每日10萬次請求**（以UTC計算，非月累計），换算月上限約300萬次（若平均分散）；可作為需要伺服器端邏輯（例如代理TDX呼叫、做座標轉換）時比GitHub Actions更即時的替代方案，Workers本身也有Cron Triggers可排程。
  來源：https://eastondev.com/blog/en/posts/dev/20260526-cloudflare-free-limits/

**B3結論：對兩人自用、資料每日更新1~2次即可的需求，GitHub Pages（靜態站）+ GitHub Actions（每天固定時間跑爬蟲/轉檔）完全免費夠用，唯一要注意「60天無commit會被停用」這個坑；若之後想要即時查詢（不只是定時快照），可以加Cloudflare Workers做輕量API代理。**

---

## B4. GitHub 是否已有類似專案

**查無**任何完整實作「台灣省道路況/林道管制」＋「路線規劃疊圖」的活躍開源專案。實測GitHub網頁搜尋（`github.com/search?type=repositories`）結果：

- 關鍵字 `TDX RoadEvent` → **0 個repo**
- 關鍵字 `省道 管制`（中文）→ **0 個repo**（GitHub搜尋對中文關鍵字命中率本身就低，非代表真的完全没有，但至少沒有以此為repo名稱/描述關鍵字的專案）
- 關鍵字 `thb.gov.tw` → **1個repo**：`kiang/thb-traffic`（PHP，0 star，最後更新2025-06-03）。實際讀取其`parse.php`原始碼確認：這個repo做的是**2016年（民國105年）公路局交通量調查測站**的座標轉換（把TWD97/度分秒座標轉WGS84經緯度，含一套通用的TWD97轉經緯度函式可直接參考借用），**不是**即時施工/封閉資料，且屬於一次性/過時的小工具，非長期維護專案。
  來源：https://github.com/kiang/thb-traffic/blob/master/parse.php
- `tdxmotc/SampleCode`、`tdxmotc/MCP`（官方repo）：官方範例程式與官方MCP server，可作為串接TDX的起手式參考，但不是「路況+路線」的完整應用。
  來源：https://github.com/tdxmotc/SampleCode ；https://github.com/tdxmotc/MCP
- `mini-taiwan-pulse`（ianlkl11234s）：使用TDX資料做交通事件追蹤，但聚焦公車/交通脈動類主題，非登山/省道封閉。

**B4結論：這是一個目前沒有人做過（或至少沒有以開源形式公開）的組合題，代表「數據層拼接」的工要自己扛，但也代表市場沒有現成輪子可以抄近路，唯一能借的是`kiang/thb-traffic`的TWD97座標轉換函式和官方TDX SampleCode的認證/呼叫範例。**

---

## B5. 現成的成品服務

- **健行筆記App**[文件，來自App介紹頁彙整]：主打步道軌跡記錄與離線地圖、部分內建林務局步道路況消息，**是登山步道路況**，不是開車去程的省道/林道封閉查詢，用途不同。
  來源：https://apps.apple.com/tw/app/健行筆記/id1342475719
- **公路局「幸福公路」App**[文件]：官方即時路況+施工資訊App，涵蓋國道/快速公路/省道，會在地圖上標出施工位置（代表官方內部有能力做，但這是封閉App功能非開放API/開放資料，見A1）。
  來源：https://apps.apple.com/us/app/幸福公路/id604698360
- **Google地圖本身**：一般封路會反映在導航路線調整，但如B1所述沒有查到開發者可讀取的結構化封路清單API，且林道等級道路收錄通常不完整。

**B5結論：沒有任何一個現成服務同時做到「起訖點路線規劃」＋「疊圖標示管制內容」，公路局幸福公路App做到了「即時路況視覺化」但不含路線規劃、不開放資料；健行筆記做到「步道軌跡」但不含公路管制。這個組合目前確實是空白，值得做，但也代表沒有現成整合可以直接抄。**

---

## 對架構的直接影響

1. **省道/公路局的施工封閉公告本身100%只有「路線＋方向＋里程樁號＋地名文字」，沒有座標**（A2實測證實）——資料層必須內建一支「里程→座標」轉換模組，不能假設公告資料自帶座標。
2. 里程→座標轉換建議**先用「省道里程坐標(里程牌標誌)」CSV做最近點查表**（A6①），公里級精度對「畫在路線上大概哪一段」的用途已經夠用，比自己寫SHP線型內插（A6②）省事很多。
3. 精度上限要提前告知使用者/自己心裡有數：里程牌查表法可能有到公里等級、甚至（路線剛重編時）到公里以上的誤差，**不要拿來做「精確到路口」的定位承諾**。
4. 若要更準，第二步才上TDX「路段編碼」動態API（A6③），但這需要先完成TDX會員註冊＋人工審核（有前置時間成本），且要組合兩支API呼叫（Mileage查LinkID → Shape查座標），非一次到位，排在MVP之後比較合理。
5. TDX的「省道專屬且保證含座標」的事件端點本次**沒有100%驗證到**（A1）——正式開工前，第一件事應該是實際申請TDX帳號、對已知某條省道的City代碼跑一次`Live/News/City/{City}`，用真實回應決定「事件資料走TDX」還是「事件資料走爬168施工頁+自己套里程轉座標」。這是最高風險、最該優先驗證的假設。
6. 消防署EMIC「交通災情通報表」（A4）意外地是本次查到**唯一自帶座標（且有前/後管制點兩組座標）**的道路管制類資料，但它只涵蓋「災害觸發」的封路（颱風/地震/坍方），不涵蓋常態施工，可以當作「重大災害封路」的補充資料源，但不能取代日常施工資料。
7. 林道（A3）目前沒有即時管制的結構化資料，只有靜態路線圖（KML/SHP，不定期更新，且有已知座標/里程方向不一致的品質問題）；林道管制內容大概率仍要靠人工定期抄各林管處公告頁面，短期內做不到自動化。
8. 國家公園/警政署入山入園（A5）完全沒有開放資料，只有申請表單頁面，這條線如果要做，只能做「連結到官方申請頁」而不是「站內顯示管制內容」。
9. Google Maps Platform 2026年定價制度剛大改，且沒查到封路開放API，兩人自用專案建議直接走**OSM生態系**（OpenFreeMap底圖 + OpenRouteService或自架OSRM路線規劃），成本可以壓到0，且不用擔心林道收錄不全的問題（OSM社群對台灣林道/產業道路的收錄常常比Google更完整，但這點本次未實測驗證，屬於既有經驗推斷，正式選型前建議實際比對兩者在幾條目標林道上的路網完整度）。
10. GitHub Pages + Actions 完全可以撐起「靜態站+每日排程抓資料」架構且免費，但務必記住**「60天無commit會停用排程」**這個坑——兩人自用、可能會有一段時間沒去動repo，建議額外加一個極簡的「保活」機制（例如排程workflow本身順便commit一個時間戳檔案）。

---

## 查無清單（明確查不到，不做推測）

- TDX是否有「單一端點、保證含經緯度」的省道專屬事件/施工API：**查無**，只查到間接證據（TDX Event MCP服務描述），未拿到該分類的完整schema。
- 168.thb.gov.tw網站本身是否有公開JSON/GeoJSON下載：**查無**（網站被Incapsula擋下，無法直接檢視；其資料出口「施工路段查詢」頁證實為純HTML文字表格，無下載/API連結）。
- Google Routes/Roads API是否有官方文件證實的「結構化道路封閉查詢」功能：**查無**官方一手文件佐證，僅第三方網站行銷文字提及，予以存疑不採信。
- OpenRouteService免費方案確切的「每日/每分鐘」配額數字：官方restrictions頁**查無**逐項列出，僅第三方彙整文章估計約2,000~2,500次/日、40次/分鐘，需自行登入官方後台核對。
- 國家公園/警政署入山入園是否有任何形式的結構化開放資料或公開查詢API：**查無**，僅有人工申請表單系統。
- 林道即時管制（例如颱風後封閉）的結構化資料源：**查無**，僅有不定期更新的靜態路線圖資。

---

**報告檔案路徑**：`E:\climbing source\research\2026-09-10-data-sources-survey.md`
