// 山路管制查詢站 — 集中設定（所有可調值只改這裡）
// 依據 SPEC.md §1 技術選型、§4 比對規則、§7a 時間、§7b-決議 拼接路線、§7d 區段畫法。
window.APP_CONFIG = {
  // 底圖：OpenFreeMap 深色向量 style（2026-09-10 實測 https://tiles.openfreemap.org/styles/dark 回 200，
  // background-color rgb(12,12,12)）。若該服務掛掉會自動退回下面的 CARTO dark_all raster。
  basemapStyleUrl: 'https://tiles.openfreemap.org/styles/dark',
  basemapRasterFallback: 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  basemapRasterAttribution: '&copy; OpenStreetMap contributors &copy; CARTO',

  // 路線規劃：OSRM 公開 demo（driving profile；請控制在每秒 1 次以內）
  osrmBaseUrl: 'https://router.project-osrm.org',
  // 地理編碼：Nominatim
  nominatimUrl: 'https://nominatim.openstreetmap.org/search',
  // 地理編碼偏好範圍（台18／台21 一帶），先在框內找，找不到再放寬到全台
  geocodeViewbox: '120.3,23.2,121.2,24.1',

  // 比對距離（公尺）：事件到路線的距離 <= 此值視為「在路線上」（SPEC §4、§7d）
  matchDistanceMeters: 600,

  // 預設起終點（頁面載入自動跑一次）
  defaultOrigin: '水里',
  defaultDestination: '塔塔加遊客中心',

  // 資料檔（前端唯一資料來源，合約見 SPEC §3）
  // 可用網址參數覆寫測試用資料：?data=sample-events-v2.geojson
  dataUrl: 'data/events.geojson',

  // 政府行政機關辦公日曆表（SPEC §9d）：例假日／補行上班日判定用，由 scripts/build_holidays.py 產生。
  // 載入失敗時前端退回「只算週六日」並在 ⓘ 面板標示。可用 ?holidays=sample-holidays.json 覆寫。
  holidaysUrl: 'data/holidays.json',

  // 省道里程折線（SPEC §7d）：事件里程內插與台21 拼接路線都讀這兩份
  roadLines: {
    tw18: 'data/roads/tw18.geojson',
    tw21: 'data/roads/tw21.geojson'
  },

  // 「路線偏好：台21」拼接路線（SPEC §7b-決議）
  // OSM 把台21 望高隧道附近標成不可通行，OSRM 一定繞台18；改成三段拼接：
  // ①OSRM 起點→fromM 內插點 ②tw21 折線 fromM→toM 子段（toM: null = 折線末端）③OSRM 末端→終點
  splice: { road: 'tw21', fromM: 110900, toM: null, speedKmh: 30 },

  // 改動出發／抵達時間時即時重算 ETA 與管制判定（SPEC §7a）
  etaRefreshOnTimeChange: true,

  // 地圖初始視野
  mapCenter: [120.85, 23.6],
  mapZoom: 9
};
