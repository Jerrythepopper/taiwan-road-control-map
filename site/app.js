/* 山路管制查詢站 — 前端邏輯（第二階段：區段、出發／抵達時間、台21 拼接路線）
   規格：SPEC.md §2 UI、§3 資料合約、§4 比對、§7a 時間、§7b-決議 拼接、§7d 區段。
   所有可調值在 config.js。 */
(function () {
  'use strict';

  var CFG = window.APP_CONFIG;

  var TYPE = {
    closure:      { label: '封閉',     symbol: '✕', cls: 'closure',      color: '#ff5c5c' },
    timed:        { label: '時段管制', symbol: '◷', cls: 'timed',        color: '#ffb547' },
    construction: { label: '施工',     symbol: '⚠', cls: 'construction', color: '#6fa8ff' }
  };
  var STATUS = { active: '進行中', scheduled: '預告', ended: '已解除' };
  // ETA 落點的管制判定（SPEC §7a）
  var VERDICT = {
    closed:  { label: '封閉中',       cls: 'closure' },
    release: { label: '時段放行',     cls: 'timed' },
    lane:    { label: '車道管制中',   cls: 'construction' }, // SPEC §9a：可通行但車道縮減 → --blue
    open:    { label: '不在管制時段', cls: 'accent' },
    unknown: { label: '時段未結構化', cls: 'muted' }
  };
  // 摘要「會遇到 N 筆管制」只算這些（SPEC §9a：不計 lane；§9b：不計 ended）
  var COUNTED_VERDICTS = ['closed', 'release'];
  var DOW = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];

  var state = {
    events: [],
    holidays: null,       // { holidays:{isoDate:1}, workdays:{isoDate:1}, years:[] }；null = 沒載到（SPEC §9d 退路）
    route: null,          // Feature<LineString>
    routeSecs: null,      // 與 route 幾何頂點對齊的累積秒數（SPEC §7a）
    routeDistance: 0,
    routeDuration: 0,
    originCoord: null,
    destCoord: null,
    selectedId: null,
    filterActiveOnly: false,
    filterRoad: 'all',
    preferRoute: 'auto',  // 'auto' | 'tw21'（SPEC §7b-決議）
    timeMode: 'depart',   // 'depart' | 'arrive'
    timeValue: null,      // Date
    departAt: null,       // Date（抵達模式回推得到）
    pickMode: null,
    markers: [],
    endpointMarkers: [],
    roadCache: {},
    popup: null,
    planning: false,
    fitted: false
  };

  var map = null;
  var el = {};

  /* ---------------- 小工具 ---------------- */

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function showError(msg) {
    el.errorBar.textContent = '⚠ ' + msg;
    el.errorBar.hidden = false;
  }
  function clearError() {
    el.errorBar.hidden = true;
    el.errorBar.textContent = '';
  }

  function setStatus(msg, isError) {
    el.routeStatus.textContent = msg;
    el.routeStatus.classList.toggle('is-error', !!isError);
  }

  function getJSON(url) {
    return fetch(url, { headers: { 'Accept': 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error((url.indexOf('//') > 0 ? url.split('/')[2] : url) + ' 回應 HTTP ' + r.status);
      return r.json();
    });
  }

  function pad2(n) { return String(n).padStart(2, '0'); }

  function fmtMD(iso) {
    if (!iso) return '';
    var p = iso.slice(0, 10).split('-');
    return p.length === 3 ? p[1] + '/' + p[2] : iso;
  }
  function fmtDateTime(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.getFullYear() + '/' + pad2(d.getMonth() + 1) + '/' + pad2(d.getDate()) +
      ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }
  function fmtHM(d) { return d ? pad2(d.getHours()) + ':' + pad2(d.getMinutes()) : ''; }
  function fmtDur(sec) {
    var mins = Math.round(sec / 60);
    return mins >= 60 ? Math.floor(mins / 60) + ' 小時 ' + (mins % 60) + ' 分' : mins + ' 分';
  }
  function kmRange(p) {
    if (!p.from_km) return '（未載明里程）';
    return (p.to_km && p.to_km !== p.from_km) ? p.from_km + ' – ' + p.to_km : p.from_km;
  }

  // <input type="datetime-local"> 需要本地時間字串（不是 ISO/UTC）
  function toInputValue(d) {
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
      'T' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }
  function fromInputValue(v) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(v || ''));
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], 0, 0);
  }

  function sameCoord(a, b) { return a && b && a[0] === b[0] && a[1] === b[1]; }

  /* ---------------- 時段規則判定（SPEC §7a） ---------------- */

  function hhmmToMin(s) {
    var m = /^(\d{1,2})[:：](\d{2})$/.exec(String(s || '').trim());
    if (!m) return null;
    var h = +m[1], mi = +m[2];
    if (h > 24 || mi > 59) return null;
    return h * 60 + mi;
  }

  function dateKey(d) {
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  // SPEC §9d：在 workdays（補行上班日）→ false；在 holidays → true；否則週六日 → true。
  // holidays.json 沒載到時只剩週六日判定（ⓘ 面板會標示）。
  function isHoliday(d) {
    var day = (typeof d === 'string') ? new Date(d) : d;
    if (!day || isNaN(day)) return false;
    var h = state.holidays;
    if (h) {
      var k = dateKey(day);
      if (h.workdays[k]) return false;
      if (h.holidays[k]) return true;
    }
    var w = day.getDay();
    return w === 0 || w === 6;
  }
  window.isHoliday = isHoliday; // 驗收用

  // days 可為 'daily' / ['mon','fri'] / ['holiday']（SPEC §9d）；d 是該規則「所屬那一天」的 Date
  function dayMatches(days, d) {
    if (!days || days === 'daily' || days === 'all') return true;
    var list = Array.isArray(days) ? days : String(days).split(/[,\s]+/);
    var dow = d.getDay();
    for (var i = 0; i < list.length; i++) {
      var tok = String(list[i]).toLowerCase().trim();
      if (tok === 'daily' || tok === 'all') return true;
      if (tok === 'holiday' || tok === 'holidays' || tok === '例假日') {
        if (isHoliday(d)) return true;
        continue;
      }
      if (tok === 'weekday' || tok === 'weekdays' || tok === '平日') {
        if (!isHoliday(d)) return true;
        continue;
      }
      if (tok.slice(0, 3) === DOW[dow]) return true;
    }
    return false;
  }

  var EFFECTS = ['exempt', 'closed', 'release', 'lane'];
  function ruleEffect(r) {
    var e = String(r && r.effect || '').toLowerCase();
    return EFFECTS.indexOf(e) >= 0 ? e : 'release'; // 舊資料沒寫 effect 時比照 release（維持原行為）
  }

  // 單條規則是否命中 when；跨午夜（to < from）對所有 effect 一致處理，to:'24:00' 視為整日。
  // 命中時回傳該規則「所屬那一天」的 Date（跨午夜的凌晨段算前一天），沒命中回 null。
  function ruleHitDay(r, when) {
    var f = hhmmToMin(r.from), t = hhmmToMin(r.to);
    if (f === null || t === null) return null;
    var mins = when.getHours() * 60 + when.getMinutes();
    var inRange = false, shiftBack = false;
    if (t > f) {
      inRange = mins >= f && mins < t;   // to='24:00' → t=1440，整日成立
    } else if (t < f) {
      if (mins >= f) inRange = true;                        // from~24:00 屬當天
      else if (mins < t) { inRange = true; shiftBack = true; } // 00:00~to 屬前一天那條規則
    } else {
      inRange = true;                     // from === to 視為全天
    }
    if (!inRange) return null;
    var day = shiftBack ? new Date(when.getTime() - 86400000) : when;
    return dayMatches(r.days, day) ? day : null;
  }

  function isAllDay(r) {
    var f = hhmmToMin(r.from), t = hhmmToMin(r.to);
    return f === t || (f === 0 && t === 1440);
  }

  // exempt 命中時給人看的說明（SPEC §9d：「例假日不管制」「12:00–13:00 不管制」）
  function exemptNote(r) {
    var days = Array.isArray(r.days) ? r.days.join(',').toLowerCase() : String(r.days || '').toLowerCase();
    var isHolidayRule = days.indexOf('holiday') >= 0 || days.indexOf('例假日') >= 0;
    var head = isHolidayRule ? '例假日' : '';
    var span = isAllDay(r) ? '' : (r.from + '–' + r.to + ' ');
    if (!head && !span) return '不管制';
    return head + (head && span ? ' ' : '') + span + '不管制';
  }

  // rules: [{days, from:'HH:MM', to:'HH:MM', effect:'exempt'|'closed'|'release'|'lane', note}]
  // 判定順序（SPEC §9d）：exempt → closed → release → lane → 都沒命中 open；完全沒規則 unknown。
  // 回傳 { state:'closed'|'release'|'lane'|'open'|'unknown', rule, note }
  function evaluateRules(rules, when) {
    if (!rules || !rules.length || !when || isNaN(when)) return { state: 'unknown', rule: null, note: '' };
    var hits = { exempt: null, closed: null, release: null, lane: null };
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i] || {};
      var eff = ruleEffect(r);
      if (hits[eff]) continue;
      if (ruleHitDay(r, when)) hits[eff] = r;
    }
    if (hits.exempt) return { state: 'open', rule: hits.exempt, note: exemptNote(hits.exempt) };
    if (hits.closed) return { state: 'closed', rule: hits.closed, note: '' };
    if (hits.release) return { state: 'release', rule: hits.release, note: '' };
    if (hits.lane) return { state: 'lane', rule: hits.lane, note: '' };
    return { state: 'open', rule: null, note: '' };
  }
  window.evaluateRules = evaluateRules; // 驗收用：console 可直接跑案例

  /* ---------------- 地圖 ---------------- */

  function rasterStyle() {
    return {
      version: 8,
      sources: {
        carto: {
          type: 'raster',
          tiles: [CFG.basemapRasterFallback.replace('{r}', '')],
          tileSize: 256,
          attribution: CFG.basemapRasterAttribution
        }
      },
      layers: [
        { id: 'bg', type: 'background', paint: { 'background-color': '#0c0c0c' } },
        { id: 'carto', type: 'raster', source: 'carto' }
      ]
    };
  }

  function initMap() {
    return fetch(CFG.basemapStyleUrl)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        showError('深色向量底圖載入失敗（' + e.message + '），已改用 CARTO dark raster 底圖。');
        return rasterStyle();
      })
      .then(function (style) {
        map = new maplibregl.Map({
          container: 'map',
          style: style,
          center: CFG.mapCenter,
          zoom: CFG.mapZoom,
          attributionControl: { compact: true }
        });
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
        window.__map = map; // debug hook（截圖／驗收時可在 console 直接操作地圖）
        window.__state = state;
        map.on('error', function (e) {
          var msg = (e && e.error && e.error.message) ? e.error.message : '未知錯誤';
          showError('地圖資源載入問題：' + msg);
        });
        map.on('click', onMapClick);
        // 注意：不要等 map 的 'load'——它要等所有 tile 都載完，網路慢或被擋時永遠不會觸發，
        // 整個 App 會卡住。改等 'style.load'（style 就緒即可加圖層），並留一道逾時保險。
        return new Promise(function (res) {
          var done = false;
          function finish() { if (!done) { done = true; res(); } }
          if (map.isStyleLoaded()) return finish();
          map.once('style.load', finish);
          map.on('styledata', function () { if (map.isStyleLoaded()) finish(); });
          setTimeout(finish, 8000);
        });
      })
      .then(function () {
        ensureRouteLayers();
        map.on('styledata', ensureRouteLayers);
        watchMapSize();
      });
  }

  function ensureRouteLayers() {
    if (!map || map.getSource('route')) return true;
    try {
      map.addSource('route', { type: 'geojson', data: state.route || emptyFC() });
      map.addLayer({
        id: 'route-glow', type: 'line', source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#5ce0b8', 'line-width': 10, 'line-opacity': 0.25, 'line-blur': 2 }
      });
      map.addLayer({
        id: 'route-line', type: 'line', source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#5ce0b8', 'line-width': 4 }
      });
      // 管制區段疊在路線之上（SPEC §7d）：底層寬 8 半透明、頂層寬 3 實線
      map.addSource('segments', { type: 'geojson', data: emptyFC() });
      map.addLayer({
        id: 'seg-base', type: 'line', source: 'segments',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'color'], 'line-width': 8,
          'line-opacity': ['case', ['get', 'dim'], 0.14, 0.35]
        }
      });
      map.addLayer({
        id: 'seg-line', type: 'line', source: 'segments',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'color'], 'line-width': 3,
          'line-opacity': ['case', ['get', 'dim'], 0.35, 1]
        }
      });
      map.on('click', 'seg-base', function (e) {
        var f = e.features && e.features[0];
        if (f) selectEvent(f.properties.id, false);
      });
      map.on('mouseenter', 'seg-base', function () { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'seg-base', function () { map.getCanvas().style.cursor = ''; });
      return true;
    } catch (e) {
      return false;
    }
  }

  function emptyFC() { return { type: 'FeatureCollection', features: [] }; }

  // 把整條路線框進畫面。地圖容器在視窗隱藏／尚未布局時寬高會是 0，此時 fitBounds 沒有意義，
  // 因此只在容器有實際尺寸時才做，並靠 ResizeObserver 在容器拿到尺寸後補一次。
  function fitRoute(duration) {
    if (!state.route || !map) return;
    var box = document.getElementById('map').getBoundingClientRect();
    if (box.width < 40 || box.height < 40) return;
    var bb = turf.bbox(state.route);
    map.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 50, duration: duration || 0 });
    state.fitted = true;
  }

  function watchMapSize() {
    if (typeof ResizeObserver !== 'function') return;
    new ResizeObserver(function () {
      if (!state.fitted) fitRoute(0);
    }).observe(document.getElementById('map'));
  }

  /* ---------------- 資料 ---------------- */

  // 網址參數覆寫資料檔：只取 basename 掛在 data/ 底下，含協定（http: 等）或空值一律用預設，
  // 避免被塞外部網址或跳出 data/（?data=sample-events-v2.geojson、?holidays=sample-holidays.json）
  function resolveDataParam(name, fallback) {
    var q = new URLSearchParams(window.location.search).get(name);
    if (!q || /^[a-z][a-z0-9+.-]*:/i.test(q) || q.indexOf('//') === 0) return fallback;
    var base = String(q).replace(/^.*[\\/]/, '').trim();
    return base ? 'data/' + base : fallback;
  }

  function resolveDataUrl() { return resolveDataParam('data', CFG.dataUrl); }
  function resolveHolidaysUrl() { return resolveDataParam('holidays', CFG.holidaysUrl || 'data/holidays.json'); }

  // 假日表（SPEC §9d）。載入失敗不是致命錯誤：state.holidays = null → isHoliday 退回只算週六日。
  function loadHolidays() {
    var url = resolveHolidaysUrl();
    return getJSON(url).then(function (j) {
      var toSet = function (arr) {
        var o = {};
        (Array.isArray(arr) ? arr : []).forEach(function (s) { o[String(s).trim()] = 1; });
        return o;
      };
      state.holidays = {
        holidays: toSet(j.holidays),
        workdays: toSet(j.workdays),
        years: j.years || [],
        source: j.source || '',
        built_at: j.built_at || ''
      };
    }).catch(function () {
      state.holidays = null;
    }).then(function () {
      renderHolidayNote(url);
    });
  }

  function renderHolidayNote(url) {
    var node = el.infoHolidays;
    if (!node) return;
    if (!state.holidays) {
      node.textContent = '假日資料未載入，例假日僅以週六日判定（' + url + '）。';
      node.className = 'modal-note c-timed';
    } else {
      var h = state.holidays, nh = Object.keys(h.holidays).length, nw = Object.keys(h.workdays).length;
      node.textContent = '假日資料：' + (h.years.length ? h.years.join('、') + ' 年，' : '') +
        nh + ' 天假日、' + nw + ' 天補行上班日。';
      node.className = 'modal-note';
    }
    node.hidden = false;
  }

  function loadEvents() {
    var url = resolveDataUrl();
    return getJSON(url).then(function (fc) {
      state.events = (fc.features || []).map(function (f) {
        var g = f.geometry || null;
        var ev = {
          id: f.properties.id,
          p: f.properties,
          geomType: g ? g.type : null,
          coords: null,   // LineString 的座標串
          line: null,     // turf Feature<LineString>
          coord: null,    // 徽章錨點（區段中點／點事件座標）
          ends: [],       // 比對用的參考點（中點＋兩端）
          onRoute: false, along: null, dist: null,
          etaSec: null, eta: null, verdict: null
        };
        if (ev.geomType === 'LineString' && g.coordinates.length >= 2) {
          ev.coords = g.coordinates;
          ev.line = turf.lineString(ev.coords);
          var len = turf.length(ev.line, { units: 'kilometers' });
          ev.coord = turf.along(ev.line, len / 2, { units: 'kilometers' }).geometry.coordinates;
          ev.ends = [ev.coord, ev.coords[0], ev.coords[ev.coords.length - 1]];
        } else if (ev.geomType === 'Point') {
          ev.coord = g.coordinates;
          ev.ends = [ev.coord];
        } else {
          ev.geomType = null; // geometry: null → 不畫，只進「其他公告」
        }
        return ev;
      });
      // ⓘ 資料更新時間：優先讀頂層 meta.generated_at（SPEC §8b-5），沒有才退回最大 fetched_at
      var stamp = (fc.meta && fc.meta.generated_at) || fc.generated_at || '';
      if (!stamp) {
        stamp = state.events.reduce(function (a, e) {
          return (!a || (e.p.fetched_at || '') > a) ? (e.p.fetched_at || '') : a;
        }, '');
      }
      el.infoUpdated.textContent = fmtDateTime(stamp);
    }).catch(function (e) {
      showError('管制資料載入失敗：' + e.message + '（檔案 ' + url + '）');
      throw e;
    });
  }

  // 里程折線（tw18 / tw21），拼接路線用（SPEC §7b-決議）
  function loadRoadLine(key) {
    if (state.roadCache[key]) return Promise.resolve(state.roadCache[key]);
    var url = (CFG.roadLines || {})[key];
    if (!url) return Promise.reject(new Error('config.roadLines 沒有 ' + key));
    return getJSON(url).then(function (fc) {
      var f = (fc.type === 'FeatureCollection') ? fc.features[0] : fc;
      var o = { coords: f.geometry.coordinates, mil: f.properties.mileage_m };
      if (!o.mil || o.mil.length !== o.coords.length) throw new Error(key + ' 折線缺少 mileage_m');
      state.roadCache[key] = o;
      return o;
    });
  }

  function interpOnRoad(road, m) {
    var c = road.coords, mil = road.mil;
    if (m <= mil[0]) return c[0].slice();
    if (m >= mil[mil.length - 1]) return c[c.length - 1].slice();
    for (var i = 1; i < mil.length; i++) {
      if (mil[i] >= m) {
        var t = (m - mil[i - 1]) / (mil[i] - mil[i - 1]);
        return [c[i - 1][0] + (c[i][0] - c[i - 1][0]) * t, c[i - 1][1] + (c[i][1] - c[i - 1][1]) * t];
      }
    }
    return c[c.length - 1].slice();
  }

  function subOnRoad(road, m0, m1) {
    var out = [interpOnRoad(road, m0)];
    for (var i = 0; i < road.mil.length; i++) {
      if (road.mil[i] > m0 && road.mil[i] < m1) out.push(road.coords[i].slice());
    }
    out.push(interpOnRoad(road, m1));
    var ded = [out[0]];
    for (var j = 1; j < out.length; j++) if (!sameCoord(out[j], ded[ded.length - 1])) ded.push(out[j]);
    return ded;
  }

  /* ---------------- 路線比對（SPEC §4、§7d） ---------------- */

  function computeMatching() {
    state.events.forEach(function (ev) {
      ev.onRoute = false; ev.along = null; ev.dist = null;
      ev.etaSec = null; ev.eta = null; ev.verdict = null;
      if (!state.route || !ev.geomType) return;
      // LineString：中點與兩端三個點取最小距離
      var best = Infinity;
      ev.ends.forEach(function (c) {
        var d = turf.pointToLineDistance(turf.point(c), state.route, { units: 'meters' });
        if (d < best) best = d;
      });
      ev.dist = best;
      ev.onRoute = best <= CFG.matchDistanceMeters;
      if (!ev.onRoute) return;
      var snap = turf.nearestPointOnLine(state.route, turf.point(ev.coord), { units: 'kilometers' });
      ev.along = snap.properties.location; // 沿路線位置（排序用，取中點）
      if (state.routeSecs && state.routeSecs.length) {
        var idx = Math.min(Math.max(snap.properties.index || 0, 0), state.routeSecs.length - 1);
        ev.etaSec = state.routeSecs[idx];
      }
    });
    computeEta();
  }

  // 出發／抵達時間 → 每筆事件 ETA 與判定（SPEC §7a）
  function computeEta() {
    var base = state.timeValue;
    state.departAt = null;
    if (base && !isNaN(base)) {
      state.departAt = (state.timeMode === 'arrive' && state.routeDuration)
        ? new Date(base.getTime() - state.routeDuration * 1000)
        : new Date(base.getTime());
    }
    state.events.forEach(function (ev) {
      ev.eta = null; ev.verdict = null;
      if (!state.departAt || ev.etaSec == null) return;
      ev.eta = new Date(state.departAt.getTime() + ev.etaSec * 1000);
      ev.verdict = evaluateRules(ev.p.rules, ev.eta);
    });
  }

  function passesFilter(ev) {
    if (state.filterActiveOnly && ev.p.status !== 'active') return false;
    if (state.filterRoad !== 'all' && ev.p.road !== state.filterRoad) return false;
    return true;
  }

  function sortedGroups() {
    var shown = state.events.filter(passesFilter);
    var on = shown.filter(function (e) { return e.onRoute; })
      .sort(function (a, b) { return a.along - b.along; });
    var off = shown.filter(function (e) { return !e.onRoute; })
      .sort(function (a, b) {
        if (a.p.road !== b.p.road) return a.p.road < b.p.road ? -1 : 1;
        return (a.p.from_km || '') < (b.p.from_km || '') ? -1 : 1;
      });
    return { on: on, off: off };
  }

  /* ---------------- 清單 ---------------- */

  function etaText(ev) {
    if (!ev.eta || !ev.verdict) return '';
    if (ev.p.status === 'ended') return '';  // SPEC §9b：已解除事件不顯示 ETA 行
    var v = VERDICT[ev.verdict.state] || VERDICT.unknown;
    var r = ev.verdict.rule;
    // exempt 命中時括號放說明（例假日不管制），其餘放規則時段
    var detail = ev.verdict.note || (r ? r.from + '–' + r.to : '');
    return '預計 ' + fmtHM(ev.eta) + ' 經過 → ' + v.label + (detail ? '（' + detail + '）' : '');
  }

  function cardSub(ev) {
    var p = ev.p;
    var t = TYPE[p.type] || TYPE.construction;
    var bits = ['<span class="state c-' + t.cls + '">' + esc(t.label) + '</span>'];
    if (!ev.geomType) bits.push('（無法定位）');
    if (p.status === 'ended') bits.push('已解除（' + esc(fmtMD(p.end_date)) + '）');
    else if (p.schedule) bits.push(esc(p.schedule));
    else if (p.end_date) bits.push('至 ' + esc(fmtMD(p.end_date)));
    else if (p.start_date) bits.push(esc(fmtMD(p.start_date)) + ' 起');
    if (p.status === 'scheduled') bits.push('預告');
    return bits.join(' • ');
  }

  function cardHtml(ev, dim) {
    var t = TYPE[ev.p.type] || TYPE.construction;
    var eta = etaText(ev);
    var v = ev.verdict ? (VERDICT[ev.verdict.state] || VERDICT.unknown) : null;
    return '<button class="card' + (dim ? ' is-dim' : '') +
      (state.selectedId === ev.id ? ' is-selected' : '') + '" type="button" data-id="' + esc(ev.id) + '">' +
      '<span class="card-icon t-' + t.cls + '">' + t.symbol + '</span>' +
      '<span class="card-body">' +
      '<span class="card-title">' + esc(ev.p.road + ' ' + kmRange(ev.p)) + '</span>' +
      '<span class="card-sub">' + cardSub(ev) + '</span>' +
      (eta ? '<span class="card-eta c-' + v.cls + '">' + esc(eta) + '</span>' : '') +
      '</span></button>';
  }

  function summaryHtml(onList) {
    if (!state.route || !state.departAt) return '';
    // SPEC §9a／§9b：lane（車道縮減）不計、已解除不計
    var hits = onList.filter(function (e) {
      return e.verdict && e.p.status !== 'ended' && COUNTED_VERDICTS.indexOf(e.verdict.state) >= 0;
    }).length;
    var word = state.timeMode === 'arrive' ? '本次抵達' : '本次出發';
    return '<div class="list-summary' + (hits ? ' is-hit' : '') + '">' +
      word + '會遇到 <span class="n c-' + (hits ? 'closure' : 'accent') + '">' + hits + '</span> 筆管制' +
      '<span class="when">・' + esc(fmtHM(state.departAt) + ' 出發') + '</span></div>';
  }

  function renderList() {
    var g = sortedGroups();
    var html = '';
    if (state.route) {
      html += summaryHtml(g.on);
      html += '<div class="section-head">路線上（' + g.on.length + '）</div>';
      html += g.on.length
        ? '<div class="cards">' + g.on.map(function (e) { return cardHtml(e, false); }).join('') + '</div>'
        : '<p class="empty">這條路線上目前沒有符合條件的管制。</p>';
      if (g.off.length) {
        html += '<div class="section-head">其他公告（' + g.off.length + '）</div>' +
          '<div class="cards">' + g.off.map(function (e) { return cardHtml(e, true); }).join('') + '</div>';
      }
    } else {
      html += '<div class="section-head">全部公告（' + (g.on.length + g.off.length) + '）</div>';
      var all = g.on.concat(g.off);
      html += all.length
        ? '<div class="cards">' + all.map(function (e) { return cardHtml(e, false); }).join('') + '</div>'
        : '<p class="empty">沒有符合條件的公告。</p>';
    }
    el.list.innerHTML = html;
    Array.prototype.forEach.call(el.list.querySelectorAll('.card'), function (btn) {
      btn.addEventListener('click', function () { selectEvent(btn.getAttribute('data-id'), true); });
    });
  }

  /* ---------------- 標記與區段（SPEC §7d） ---------------- */

  function renderSegments() {
    if (!map || !map.getSource('segments')) return;
    var feats = [];
    state.events.filter(passesFilter).forEach(function (ev) {
      if (ev.geomType !== 'LineString') return;
      var t = TYPE[ev.p.type] || TYPE.construction;
      feats.push({
        type: 'Feature',
        properties: { id: ev.id, color: t.color, dim: !!(state.route && !ev.onRoute) },
        geometry: { type: 'LineString', coordinates: ev.coords }
      });
    });
    map.getSource('segments').setData({ type: 'FeatureCollection', features: feats });
  }

  function renderMarkers() {
    state.markers.forEach(function (m) { m.remove(); });
    state.markers = [];
    state.events.filter(passesFilter).forEach(function (ev) {
      if (!ev.geomType || !ev.coord) return; // geometry: null 不畫 marker
      var t = TYPE[ev.p.type] || TYPE.construction;
      var wrap = document.createElement('div');
      wrap.className = 'ev-marker' +
        (state.route && !ev.onRoute ? ' is-off' : '') +
        (state.selectedId === ev.id ? ' is-selected' : '');
      wrap.innerHTML = '<div class="ev-badge t-' + t.cls + '">' + t.symbol + '</div>' +
        '<div class="ev-pill">' + esc(kmRange(ev.p)) + '</div>';
      wrap.addEventListener('click', function (e) {
        e.stopPropagation();
        selectEvent(ev.id, true);
      });
      state.markers.push(new maplibregl.Marker({ element: wrap, anchor: 'top' })
        .setLngLat(ev.coord).addTo(map));
    });
    renderSegments();
  }

  function setEndpointMarker(coord, kind) {
    var d = document.createElement('div');
    d.className = 'pt-marker ' + (kind === 'origin' ? 'pt-origin' : 'pt-dest');
    state.endpointMarkers.push(new maplibregl.Marker({ element: d }).setLngLat(coord).addTo(map));
  }
  function clearEndpointMarkers() {
    state.endpointMarkers.forEach(function (m) { m.remove(); });
    state.endpointMarkers = [];
  }

  /* ---------------- Popup（SPEC §2、§7a） ---------------- */

  function popupHtml(ev) {
    var p = ev.p, t = TYPE[p.type] || TYPE.construction;
    var desc = String(p.description || '').split('\n').filter(Boolean)
      .map(function (line) { return '<li>' + esc(line) + '</li>'; }).join('');
    var period = p.schedule || (p.start_date ? fmtMD(p.start_date) + ' – ' + (p.end_date ? fmtMD(p.end_date) : '未定') : '—');
    var eta = etaText(ev);
    var v = ev.verdict ? (VERDICT[ev.verdict.state] || VERDICT.unknown) : null;
    return '<div class="pop-head">' +
        '<span class="card-icon t-' + t.cls + '">' + t.symbol + '</span>' +
        '<span><p class="pop-title">' + esc(p.road + ' ' + kmRange(p)) + '</p>' +
        '<p class="pop-sub">' + esc(t.label + ' • ' + (p.direction || '方向未載明')) +
          (ev.geomType ? '' : '（無法定位）') + '</p></span>' +
      '</div>' +
      '<dl class="pop-meta">' +
        '<div><dt>狀態</dt><dd class="c-' + (p.status === 'active' ? t.cls : 'accent') + '">' + esc(STATUS[p.status] || p.status) + '</dd></div>' +
        '<div><dt>時段</dt><dd>' + esc(period) + '</dd></div>' +
        '<div><dt>更新</dt><dd>' + esc(fmtDateTime(p.fetched_at)) + '</dd></div>' +
      '</dl>' +
      (eta ? '<p class="pop-eta c-' + v.cls + '">' + esc(eta) + '</p>' : '') +
      '<p class="pop-summary">' + esc(p.summary) + '</p>' +
      (desc ? '<ul class="pop-desc">' + desc + '</ul>' : '') +
      '<a class="pop-btn" href="' + esc(p.source_url) + '" target="_blank" rel="noopener">查看官方公告</a>';
  }

  function closePopup() {
    if (state.popup) { var p = state.popup; state.popup = null; p.remove(); }
  }

  function openPopup(ev) {
    closePopup();
    if (!ev.coord) return; // 無法定位的公告不開 popup
    var popup = new maplibregl.Popup({
      closeButton: true, closeOnClick: false, offset: [0, -8],
      className: 'ctrl-popup', maxWidth: 'none', anchor: 'bottom'
    }).setLngLat(ev.coord).setHTML(popupHtml(ev)).addTo(map);
    popup.on('close', function () {
      if (state.popup === popup) { state.popup = null; selectEvent(null, false); }
    });
    state.popup = popup;
  }

  /* ---------------- 選取 ---------------- */

  function selectEvent(id, fly) {
    state.selectedId = id;
    renderList();
    renderMarkers();
    if (!id) { closePopup(); return; }
    var ev = state.events.filter(function (e) { return e.id === id; })[0];
    if (!ev || !ev.coord) { closePopup(); return; }
    if (fly) {
      state.fitted = true; // 使用者已自行選點，之後不要再自動 fitBounds 蓋掉
      var len = ev.line ? turf.length(ev.line, { units: 'kilometers' }) : 0;
      if (len > 2) {
        var bb = turf.bbox(ev.line);
        map.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 90, duration: 700 });
      } else {
        map.flyTo({ center: ev.coord, zoom: Math.max(map.getZoom(), 12.5), speed: 1.2 });
      }
    }
    openPopup(ev);
  }

  /* ---------------- 地理編碼 / 路線 ---------------- */

  function parseLatLon(text) {
    var m = String(text).trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
    if (!m) return null;
    var lat = parseFloat(m[1]), lon = parseFloat(m[2]);
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return [lon, lat];
  }

  function geocode(q) {
    var direct = parseLatLon(q);
    if (direct) return Promise.resolve(direct);
    var base = CFG.nominatimUrl + '?format=json&limit=1&countrycodes=tw&q=' + encodeURIComponent(q);
    return getJSON(base + '&bounded=1&viewbox=' + CFG.geocodeViewbox)
      .then(function (arr) {
        if (arr && arr.length) return arr;
        return sleep(1100).then(function () { return getJSON(base); });
      })
      .then(function (arr) {
        if (!arr || !arr.length) throw new Error('找不到地點「' + q + '」，可改用「緯度, 經度」或點地圖設定');
        return [parseFloat(arr[0].lon), parseFloat(arr[0].lat)];
      });
  }

  function osrmRoute(a, b) {
    var url = CFG.osrmBaseUrl + '/route/v1/driving/' +
      a[0] + ',' + a[1] + ';' + b[0] + ',' + b[1] +
      '?overview=full&geometries=geojson&annotations=duration';
    return getJSON(url).then(function (d) {
      if (d.code !== 'Ok' || !d.routes || !d.routes.length) {
        throw new Error('OSRM 無法規劃這段路線（' + (d.code || 'no route') + '）');
      }
      return d.routes[0];
    });
  }

  // OSRM route → { coords, secs（每頂點累積秒）, distance, duration }（SPEC §7a）
  function osrmPart(route) {
    var coords = route.geometry.coordinates;
    var durs = [];
    (route.legs || []).forEach(function (l) {
      if (l.annotation && l.annotation.duration) durs = durs.concat(l.annotation.duration);
    });
    var secs = [0], i;
    if (durs.length === coords.length - 1) {
      for (i = 1; i < coords.length; i++) secs.push(secs[i - 1] + durs[i - 1]);
    } else {
      // annotation 與幾何頂點對不上時，退回依距離比例分配總時長
      var total = 0, seg = [];
      for (i = 1; i < coords.length; i++) {
        var d = turf.distance(coords[i - 1], coords[i], { units: 'kilometers' });
        seg.push(d); total += d;
      }
      var acc = 0;
      for (i = 0; i < seg.length; i++) {
        acc += seg[i];
        secs.push(total > 0 ? route.duration * acc / total : 0);
      }
    }
    return { coords: coords, secs: secs, distance: route.distance, duration: route.duration };
  }

  // 折線子段 → part，時速固定（config.splice.speedKmh）
  function roadPart(coords, kmh) {
    var secs = [0], distM = 0;
    for (var i = 1; i < coords.length; i++) {
      distM += turf.distance(coords[i - 1], coords[i], { units: 'kilometers' }) * 1000;
      secs.push(distM / 1000 / kmh * 3600);
    }
    return { coords: coords, secs: secs, distance: distM, duration: secs[secs.length - 1] || 0 };
  }

  function concatParts(parts) {
    var coords = [], secs = [], off = 0, dist = 0;
    parts.forEach(function (p) {
      for (var i = 0; i < p.coords.length; i++) {
        if (coords.length && sameCoord(coords[coords.length - 1], p.coords[i])) continue;
        coords.push(p.coords[i]);
        secs.push(off + p.secs[i]);
      }
      off += p.duration;
      dist += p.distance;
    });
    return { coords: coords, secs: secs, distance: dist, duration: off };
  }

  // 「路線偏好：台21」＝三段拼接（SPEC §7b-決議）
  function spliceRoute(a, b) {
    var sp = CFG.splice;
    return loadRoadLine(sp.road).then(function (road) {
      var endM = road.mil[road.mil.length - 1];
      var toM = (sp.toM == null) ? endM : sp.toM;
      var A = interpOnRoad(road, sp.fromM);   // 拼接點（和社側）
      var B = interpOnRoad(road, toM);        // 塔塔加側
      var mid = subOnRoad(road, sp.fromM, toM);
      // 起點比終點更靠近塔塔加 → 下山，三段順序反轉
      var down = turf.distance(a, B, { units: 'kilometers' }) < turf.distance(b, B, { units: 'kilometers' });
      var first = down ? B : A, last = down ? A : B;
      var midCoords = down ? mid.slice().reverse() : mid;
      var p1;
      return osrmRoute(a, first)
        .then(function (r) { p1 = osrmPart(r); return sleep(1100); })
        .then(function () { return osrmRoute(last, b); })
        .then(function (r3) {
          var out = concatParts([p1, roadPart(midCoords, sp.speedKmh || 30), osrmPart(r3)]);
          out.spliced = true;
          return out;
        });
    });
  }

  function buildRoute(a, b) {
    if (state.preferRoute !== 'tw21') return osrmRoute(a, b).then(osrmPart);
    return spliceRoute(a, b).catch(function (e) {
      showError('台21 拼接路線失敗：' + e.message + '，已退回「自動」路線偏好。');
      setPrefer('auto');
      return osrmRoute(a, b).then(osrmPart).then(function (part) {
        part.fallback = true; // 保留紅色錯誤條，不要被下面的 clearError 抹掉
        return part;
      });
    });
  }

  function planRoute() {
    if (state.planning) return Promise.resolve();
    var oText = el.origin.value.trim();
    var dText = el.dest.value.trim();
    if (!state.originCoord && !oText) { setStatus('請先填起點', true); return Promise.resolve(); }
    if (!state.destCoord && !dText) { setStatus('請先填終點', true); return Promise.resolve(); }

    state.planning = true;
    el.plan.disabled = true;
    setStatus('規劃路線中…');

    var a, b;
    return Promise.resolve()
      .then(function () { return state.originCoord || geocode(oText); })
      .then(function (c) { a = c; state.originCoord = c; return state.destCoord ? null : sleep(1100); })
      .then(function () { return state.destCoord || geocode(dText); })
      .then(function (c) { b = c; state.destCoord = c; return buildRoute(a, b); })
      .then(function (part) {
        state.route = { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: part.coords } };
        state.routeSecs = part.secs;
        state.routeDistance = part.distance;
        state.routeDuration = part.duration;
        window.__route = state.route; // 驗收用：console 可讀回路線座標
        if (ensureRouteLayers()) map.getSource('route').setData(state.route);
        clearEndpointMarkers();
        setEndpointMarker(a, 'origin');
        setEndpointMarker(b, 'dest');
        state.fitted = false;
        fitRoute(700);
        computeMatching();
        closePopup();
        state.selectedId = null;
        renderList();
        renderMarkers();
        var onCount = state.events.filter(function (e) { return e.onRoute; }).length;
        setStatus((part.spliced ? '台21 拼接路線 ' : '路線 ') +
          (part.distance / 1000).toFixed(1) + ' 公里・約 ' + fmtDur(part.duration) +
          '・路線上 ' + onCount + ' 筆管制');
        if (!part.fallback) clearError();
      })
      .catch(function (e) {
        setStatus('規劃失敗：' + e.message, true);
        showError('路線規劃失敗：' + e.message);
      })
      .then(function () {
        state.planning = false;
        el.plan.disabled = false;
      });
  }

  /* ---------------- 互動 ---------------- */

  function setPickMode(mode) {
    state.pickMode = state.pickMode === mode ? null : mode;
    el.pickOrigin.classList.toggle('is-on', state.pickMode === 'origin');
    el.pickDest.classList.toggle('is-on', state.pickMode === 'dest');
    if (state.pickMode) setStatus('請在地圖上點一下，設為' + (state.pickMode === 'origin' ? '起點' : '終點'));
  }

  function onMapClick(e) {
    if (!state.pickMode) return;
    var coord = [Number(e.lngLat.lng.toFixed(5)), Number(e.lngLat.lat.toFixed(5))];
    var text = coord[1] + ', ' + coord[0];
    if (state.pickMode === 'origin') { state.originCoord = coord; el.origin.value = text; }
    else { state.destCoord = coord; el.dest.value = text; }
    setPickMode(null);
    planRoute();
  }

  function setPrefer(v) {
    state.preferRoute = v;
    Array.prototype.forEach.call($('chip-prefer').querySelectorAll('.chip'), function (c) {
      c.classList.toggle('is-on', c.getAttribute('data-prefer') === v);
    });
  }

  function setTimeMode(v) {
    state.timeMode = v;
    Array.prototype.forEach.call($('chip-timemode').querySelectorAll('.chip'), function (c) {
      c.classList.toggle('is-on', c.getAttribute('data-mode') === v);
    });
  }

  function onTimeChanged() {
    state.timeValue = fromInputValue(el.time.value);
    if (CFG.etaRefreshOnTimeChange !== false) {
      computeEta();
      refreshViews();
    }
  }

  function bindUI() {
    el.errorBar = $('error-bar');
    el.origin = $('input-origin');
    el.dest = $('input-dest');
    el.time = $('input-time');
    el.plan = $('btn-plan');
    el.routeStatus = $('route-status');
    el.list = $('list');
    el.pickOrigin = $('btn-pick-origin');
    el.pickDest = $('btn-pick-dest');
    el.infoUpdated = $('info-updated');
    el.infoHolidays = $('info-holidays');

    el.origin.value = CFG.defaultOrigin;
    el.dest.value = CFG.defaultDestination;

    var now = new Date();
    now.setSeconds(0, 0); // 預設現在，分鐘取整
    state.timeValue = now;
    el.time.value = toInputValue(now);

    el.origin.addEventListener('input', function () { state.originCoord = null; });
    el.dest.addEventListener('input', function () { state.destCoord = null; });
    [el.origin, el.dest].forEach(function (input) {
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') planRoute(); });
    });
    el.time.addEventListener('change', onTimeChanged);
    el.time.addEventListener('input', onTimeChanged);

    el.plan.addEventListener('click', planRoute);
    $('btn-swap').addEventListener('click', function () {
      var v = el.origin.value; el.origin.value = el.dest.value; el.dest.value = v;
      var c = state.originCoord; state.originCoord = state.destCoord; state.destCoord = c;
      planRoute();
    });
    el.pickOrigin.addEventListener('click', function () { setPickMode('origin'); });
    el.pickDest.addEventListener('click', function () { setPickMode('dest'); });

    Array.prototype.forEach.call($('chip-timemode').querySelectorAll('.chip'), function (chip) {
      chip.addEventListener('click', function () {
        setTimeMode(chip.getAttribute('data-mode'));
        computeEta();
        refreshViews();
      });
    });

    $('chip-active').addEventListener('click', function () {
      state.filterActiveOnly = !state.filterActiveOnly;
      this.classList.toggle('is-on', state.filterActiveOnly);
      refreshViews();
    });
    Array.prototype.forEach.call($('chip-roads').querySelectorAll('.chip'), function (chip) {
      chip.addEventListener('click', function () {
        state.filterRoad = chip.getAttribute('data-road');
        Array.prototype.forEach.call($('chip-roads').querySelectorAll('.chip'), function (c) {
          c.classList.toggle('is-on', c === chip);
        });
        refreshViews();
      });
    });
    Array.prototype.forEach.call($('chip-prefer').querySelectorAll('.chip'), function (chip) {
      chip.addEventListener('click', function () {
        var v = chip.getAttribute('data-prefer');
        if (v === state.preferRoute) return;
        setPrefer(v);
        planRoute();
      });
    });

    $('btn-info').addEventListener('click', function () { $('info-modal').hidden = false; });
    $('btn-info-close').addEventListener('click', function () { $('info-modal').hidden = true; });
    $('info-modal').addEventListener('click', function (e) {
      if (e.target === this) this.hidden = true;
    });
  }

  function refreshViews() {
    var sel = state.selectedId;
    if (sel && !state.events.filter(function (e) { return e.id === sel && passesFilter(e); }).length) {
      state.selectedId = null;
      closePopup();
    }
    renderList();
    renderMarkers();
  }

  /* ---------------- 啟動 ---------------- */

  bindUI();
  initMap()
    .then(function () { return Promise.all([loadEvents(), loadHolidays()]); })
    .then(function () {
      computeMatching();
      renderList();
      renderMarkers();
      return planRoute();
    })
    .catch(function (e) {
      showError('初始化失敗：' + e.message);
      setStatus('初始化失敗', true);
    });
})();
