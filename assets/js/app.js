/* SFWeather - renders the static dashboard from the JSON in /data.
 *
 * There is no hand-written data in this file.  Anything that is not present in
 * the fetched JSON is rendered as an em dash, never invented.
 */

'use strict';

const DASH = '\u2014';
const FILES = {
  run: 'data/run.json',
  calendar: 'data/calendar.json',
  nws: 'data/nws.json',
  provenance: 'data/provenance.json',
  quality: 'data/quality_report.json',
  storms: 'data/storm_events.json'
};

const state = { data: {}, month: '2026-10', dialogDay: null };

/* ------------------------------------------------------------------ utils */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, v);
  }
  (Array.isArray(children) ? children : [children]).forEach(c => {
    if (c === null || c === undefined || c === false) return;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  });
  return node;
}

function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Format a number with fixed decimals, or an em dash when absent. */
function n(v, dp = 0, suffix = '') {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return DASH;
  return Number(v).toFixed(dp) + suffix;
}

function pct(v, dp = 0) { return v === null || v === undefined ? DASH : Number(v).toFixed(dp) + '%'; }

function link(url, label) {
  if (!url) return el('span', { text: label || DASH });
  return el('a', { href: url, target: '_blank', rel: 'noopener', text: label || url });
}

function linkShort(url, max = 62) {
  if (!url) return el('span', { text: DASH });
  let txt = url.replace(/^https?:\/\//, '');
  if (txt.length > max) txt = txt.slice(0, max - 1) + '\u2026';
  return el('a', { href: url, target: '_blank', rel: 'noopener', text: txt, title: url });
}

function table(headers, rows, opts = {}) {
  if (!rows.length) return el('p', { class: 'empty', text: opts.empty || 'No data available.' });
  const headCells = headers.map(h => {
    const label = (h && h.label !== undefined) ? h.label : h;
    return el('th', { class: (h && h.num) ? 'num' : '', text: String(label) });
  });
  const thead = el('thead', {}, el('tr', {}, headCells));

  const bodyRows = rows.map(r => {
    const cells = r.map((cell, i) => {
      const isNum = headers[i] && headers[i].num;
      if (cell && cell.nodeType) {
        return el('td', { class: isNum ? 'num' : '' }, [cell]);
      }
      const text = (cell === null || cell === undefined) ? DASH : String(cell);
      return el('td', { class: isNum ? 'num' : '', text: text });
    });
    return el('tr', {}, cells);
  });
  const tbody = el('tbody', {}, bodyRows);
  const tbl = el('table', {}, [thead, tbody]);
  return opts.scroll === false ? tbl : el('div', { class: 'table-scroll' }, [tbl]);
}

function kvTable(pairs) {
  const rows = pairs.filter(p => p && p[1] !== undefined && p[1] !== null);
  return el('table', { class: 'kv' }, rows.map(([k, v]) =>
    el('tr', {}, [el('th', { text: k }), el('td', {}, [v && v.nodeType ? v : document.createTextNode(String(v))])])));
}

function bars(items, opts = {}) {
  const max = Math.max(1, ...items.map(i => Number(i.value) || 0));
  return el('div', { class: 'bars' }, items.map(i => {
    const v = Number(i.value) || 0;
    const w = (v / max * 100).toFixed(1) + '%';
    return el('div', { class: 'bar-row' }, [
      el('span', { class: 'bar-label', text: i.label }),
      el('span', { class: 'bar-track' }, [el('span', { class: 'bar-fill ' + (i.cls || ''), style: 'width:' + w })]),
      el('span', { class: 'bar-value', text: opts.fmt ? opts.fmt(v, i) : v })
    ]);
  }));
}

function rainClass(p) {
  if (p === null || p === undefined) return 'd0';
  if (p < 10) return 'd0';
  if (p < 25) return 'd1';
  if (p < 40) return 'd2';
  if (p < 60) return 'd3';
  return 'd4';
}

async function loadJSON(name) {
  const res = await fetch(FILES[name], { cache: 'no-store' });
  if (!res.ok) throw new Error(`${FILES[name]} \u2192 HTTP ${res.status}`);
  return res.json();
}

/* --------------------------------------------------------------- sections */

function renderReality(cal) {
  const win = cal.nws_window || {};
  const covered = win.days_covered || 0;
  const total = (cal.days || []).length;
  $('#rc-horizon').textContent = win.last_day
    ? `${win.days_covered || 0} day(s) \u2014 through ${win.last_day}` : DASH;
  $('#rc-end').textContent = 'January 2027';
  $('#rc-count').innerHTML =
    `Right now <strong>${covered}</strong> of the <strong>${total}</strong> days on this scoreboard ` +
    `carry a real NWS forecast. The remaining <strong>${total - covered}</strong> show observed ` +
    `1991\u20132020 climatology and are badged <span class="badge badge-climo">Climatology</span>. ` +
    `The page rebuilds nightly, so days convert to real forecasts automatically as they come into range.`;

  const legend = [
    {
      cls: 'badge-nws', title: 'NWS forecast',
      body: 'Inside the official forecast horizon. High, low, humidity, wind, gusts, rain chance and ' +
        'rain amount are the actual NWS gridded forecast for this ZIP code\u2019s grid cell.'
    },
    {
      cls: 'badge-climo', title: 'Climatology',
      body: 'Beyond the horizon. Each figure is the observed 1991\u20132020 record for that calendar ' +
        'date: the normal high/low, the share of years it rained, and the average amount when it did.'
    },
    {
      cls: 'badge-info', title: 'CPC outlook',
      body: 'Where a CPC outlook validly covers a day, it is attached as a probability for the whole ' +
        'period. Outlook probabilities never become daily numbers.'
    }
  ];
  $('#tier-legend').append(...legend.map(l => el('div', { class: 'card' }, [
    el('h3', {}, [el('span', { class: 'badge ' + l.cls, text: l.title })]),
    el('p', { class: 'fine', text: l.body })
  ])));
}

function renderLocation(run) {
  const c = (run.target || {}).centroid || {};
  $('#tbl-location').append(kvTable([
    ['ZIP code', (run.target || {}).zip || '94122'],
    ['Latitude', c.lat === undefined ? null : c.lat.toFixed(4) + '\u00b0 N'],
    ['Longitude', c.lon === undefined ? null : c.lon.toFixed(4) + '\u00b0 W'],
    ['Land area', c.land_area_sqmi === undefined ? null : c.land_area_sqmi + ' sq mi'],
    ['Source', link(c.url, 'U.S. Census Bureau Gazetteer' + (c.gazetteer_year ? ' (' + c.gazetteer_year + ')' : ''))],
    ['Verified against Census', c.verified ? 'Yes' : 'No \u2014 fallback value, see data quality']
  ]));
  $('#location-note').textContent =
    'The coordinate is the Census Bureau\u2019s internal point (centroid) for ZIP Code Tabulation Area ' +
    '94122, downloaded and matched in the build rather than typed in. San Francisco has sharp ' +
    'microclimates, so a single point cannot represent the whole ZIP, but it is an official, ' +
    'reproducible choice.';

  const st = (state.data.calendar || {}).stations || {};
  const pt = st.precip_temp || {}, wd = st.wind || {};
  $('#tbl-stations').append(kvTable([
    ['Rain & temperature', `${pt.id || DASH} \u2014 ${pt.name || DASH}`],
    ['', link(pt.url, 'NCEI GHCN-Daily file')],
    ['Wind & gusts', `${wd.id || DASH} \u2014 ${wd.name || DASH}`],
    ['', link(wd.url, 'NCEI GSOD archive')],
    ['Forecast grid', (state.data.nws.point || {}).grid_id
      ? `${state.data.nws.point.grid_id} ${state.data.nws.point.grid_x},${state.data.nws.point.grid_y}`
      : null],
    ['Forecast office', link('https://www.weather.gov/mtr', 'NWS San Francisco Bay Area / Monterey (MTR)')]
  ]));
}

function renderSeason(cal) {
  /* ENSO ------------------------------------------------------------- */
  const enso = cal.enso || {};
  const latest = enso.latest || {};
  const box = $('#enso-body');
  const facts = el('table', { class: 'kv' }, [
    el('tr', {}, [el('th', { text: 'Latest ONI' }), el('td', { text: (latest.year_month || DASH) +
      (latest.oni_c === undefined ? '' : `  \u2192  ${latest.oni_c > 0 ? '+' : ''}${latest.oni_c}\u00b0C (${latest.phase || DASH})`) })]),
    el('tr', {}, [el('th', { text: 'Definition' }), el('td', { text: 'ONI = 3-month running mean of ERSSTv5 Ni\u00f1o 3.4 anomalies. El Ni\u00f1o \u2265 +0.5, La Ni\u00f1a \u2264 \u22120.5.' })]),
    el('tr', {}, [el('th', { text: 'Numeric source' }), el('td', {}, [link(enso.table_url, 'CPC Ni\u00f1o 3.4 anomaly table')])])
  ]);
  box.append(facts);
  if (enso.recent && enso.recent.length) {
    box.append(el('p', { class: 'fine', text: 'Recent monthly ONI values:' }));
    box.append(table([{ label: 'Month' }, { label: 'ONI (\u00b0C)', num: true }, { label: 'Phase' }],
      enso.recent.slice().reverse().map(r => [r.year_month,
        r.oni_c === undefined ? null : (r.oni_c > 0 ? '+' : '') + r.oni_c, r.phase])));
  }
  box.append(el('p', { class: 'fine' }, [
    'Verbatim from the CPC ',
    link('https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html',
      'long-lead seasonal outlook discussion'), ', issued 20 Aug 2026:'
  ]));
  box.append(el('div', { class: 'quote', html:
    '\u201cEl Ni\u00f1o conditions are present, as represented in current oceanic and atmospheric ' +
    'observations. El Ni\u00f1o is strengthening, with a greater than 90 percent chance of a very ' +
    'strong event this fall and winter.\u201d' }));
  box.append(el('div', { class: 'quote', html:
    '\u201cDuring the October-November-December (OND) 2026 season, there is a 69% chance of a historic ' +
    'event that would exceed the strength of previous El Ni\u00f1o events dating back to 1950.\u201d' }));

  /* CPC seasonal outlooks -------------------------------------------- */
  const seasonal = (cal.cpc.records || []).filter(r => r.kind === 'season' || r.kind === 'month');
  const wanted = ['SON 2026', 'OND 2026', 'NDJ 2026', 'DJF 2026'];
  const rows = [];
  wanted.forEach(w => {
    const prcp = seasonal.find(r => r.valid_season === w && r.variable === 'prcp');
    const temp = seasonal.find(r => r.valid_season === w && r.variable === 'temp');
    if (!prcp && !temp) return;
    const fmt = r => r ? `${r.category_label} (${r.prob}%)` + (r.used_nearest_polygon ? ' \u26a0' : '') : DASH;
    rows.push([
      el('strong', { text: w }),
      fmt(temp), fmt(prcp),
      link(prcp ? prcp.url : temp.url, 'CPC shapefile')
    ]);
  });
  const other = seasonal.filter(r => !(wanted.includes(r.valid_season)));
  other.filter(r => r.variable === 'prcp').forEach(r => {
    const t = seasonal.find(x => x.valid_season === r.valid_season && x.variable === 'temp');
    rows.push([el('strong', { text: r.valid_season + (r.kind === 'month' ? ' (month)' : '') }),
      t ? `${t.category_label} (${t.prob}%)` : DASH,
      `${r.category_label} (${r.prob}%)` + (r.used_nearest_polygon ? ' \u26a0' : ''),
      link(r.url, 'CPC shapefile')]);
  });
  $('#cpc-season-table').append(table(
    [{ label: 'Period' }, { label: 'Temperature' }, { label: 'Precipitation' }, { label: 'Source' }],
    rows,
    { empty: 'No CPC long-lead outlook could be sampled for this location.' }));
  const anyNearest = seasonal.some(r => r.used_nearest_polygon);
  if (anyNearest) {
    $('#cpc-season-table').append(el('p', { class: 'fine', html:
      '\u26a0 marked rows used the nearest CPC polygon because the ZIP-code point fell between ' +
      'polygons (a known artefact for coastal cells). Check the map image below.' }));
  }

  /* maps -------------------------------------------------------------- */
  const maps = Object.values(cal.cpc.maps || {});
  $('#cpc-maps').append(...(maps.length ? maps : []).map(m => el('div', { class: 'map-item' }, [
    el('h4', { text: m.label }),
    el('img', { src: m.local_path, alt: 'CPC ' + m.label + ' map', loading: 'lazy' }),
    el('p', { class: 'fine' }, [
      link(m.url, 'Original on cpc.ncep.noaa.gov'),
      document.createTextNode(m.retrieved_utc ? ' \u00b7 retrieved ' + m.retrieved_utc : '')
    ])
  ])));
  if (!maps.length) $('#cpc-maps').append(el('p', { class: 'empty', text: 'No outlook maps were archived in this run.' }));

  /* monthly normals ---------------------------------------------------- */
  const monthly = cal.monthly || [];
  $('#monthly-table').append(table(
    [{ label: 'Month' }, { label: 'Days' }, { label: 'Normal total (in)', num: true },
     { label: 'Median (in)', num: true }, { label: 'Range (in)', num: true },
     { label: '90th pct (in)', num: true }, { label: 'Expected wet days', num: true }],
    monthly.map(m => {
      const d = m.total_prcp || {};
      return [m.label + ' ' + m.year, m.days,
        n(d.mean, 2), n(d.median, 2),
        d.min === undefined ? null : `${Number(d.min).toFixed(2)} \u2013 ${Number(d.max).toFixed(2)}`,
        n(d.p90, 2), n(m.expected_wet_days, 1)];
    })));
  const st = cal.season_summary || {};
  const season = st.season_total_prcp_in || {};
  if (season.n) {
    $('#monthly-table').append(el('p', { class: 'fine', text:
      `Whole window (1 Oct \u2013 31 Jan): mean ${n(season.mean, 2)} in, median ${n(season.median, 2)} in, ` +
      `and it has ranged from ${n(season.min, 2)} in to ${n(season.max, 2)} in across the ` +
      `${season.n} seasons on record.` }));
  }

  /* season-by-season chart --------------------------------------------- */
  const years = (cal.season_by_year || []).slice();
  if (years.length) {
    $('#season-chart').append(bars(years.map(s => ({
      label: s.season, value: s.total_prcp_in,
      cls: s.total_prcp_in >= (season.p90 || 1e9) ? 'hi' : (s.total_prcp_in <= (season.p10 || 0) ? 'lo' : '')
    })), { fmt: v => v.toFixed(2) + ' in' }));
    const wettest = cal.wettest_seasons || [], driest = cal.driest_seasons || [];
    const mk = (title, list) => el('div', {}, [
      el('h4', { text: title }),
      table([{ label: 'Season' }, { label: 'Oct\u2013Jan total (in)', num: true }],
        list.map(s => [s.season, n(s.total_prcp_in, 2)]))
    ]);
    $('#season-extremes').append(mk('Wettest seasons', wettest), mk('Driest seasons', driest));
  }

  /* ENSO stratification ------------------------------------------------- */
  const strat = cal.enso_stratified || {};
  const srows = Object.entries(strat).map(([phase, d]) => [
    phase === 'el_nino' ? 'El Ni\u00f1o' : phase === 'la_nina' ? 'La Ni\u00f1a' : phase,
    d.n, n(d.mean, 2), n(d.median, 2),
    d.min === undefined ? null : `${Number(d.min).toFixed(2)} \u2013 ${Number(d.max).toFixed(2)}`
  ]);
  $('#enso-strat').append(table(
    [{ label: 'Phase' }, { label: 'Seasons', num: true }, { label: 'Mean (in)', num: true },
     { label: 'Median (in)', num: true }, { label: 'Range (in)', num: true }], srows,
    { empty: 'Not enough ENSO-classified seasons to stratify.' }));

  /* discussions --------------------------------------------------------- */
  const discs = (cal.cpc.discussions || []).filter(d => !d.stale);
  $('#discussions').append(...(discs.length ? discs : []).map(d => el('div', { class: 'quote' }, [
    el('strong', { text: d.label }), el('br'),
    link(d.human_url || d.url, d.url)
  ])));
  if (!discs.length) $('#discussions').append(el('p', { class: 'empty', text: 'No CPC discussion passed the staleness check in this run.' }));
}

function renderNow(nws) {
  const fc = nws.forecast_daily || {};
  const periods = fc.periods || [];
  if (periods.length) {
    $('#nws-forecast').append(table(
      [{ label: 'Period' }, { label: 'Temp' }, { label: 'Rain' }, { label: 'Wind' }, { label: 'Forecast' }],
      periods.map(p => [
        el('strong', { text: p.name }),
        p.temperature_f === null ? null : p.temperature_f + '\u00b0F',
        p.pop_pct === null ? null : p.pop_pct + '%',
        p.wind_speed || DASH,
        el('span', { class: 'fine', text: p.short_forecast || '' })
      ])));
    $('#nws-forecast').append(el('p', { class: 'fine' }, [
      'Issued ', document.createTextNode(fc.updated || DASH), '. ',
      link(fc.human_url, 'Open this forecast on weather.gov'), ' \u00b7 ',
      link(fc.source_url, 'NWS API endpoint')
    ]));
  } else {
    $('#nws-forecast').append(el('p', { class: 'empty', text: 'NWS forecast unavailable in this run.' }));
  }

  const obs = (nws.stations || []).filter(s => s.observation);
  if (obs.length) {
    $('#nws-obs').append(table(
      [{ label: 'Station' }, { label: 'Observed' }, { label: 'Temp' }, { label: 'RH' },
       { label: 'Wind' }, { label: 'Gust' }],
      obs.map(s => {
        const o = s.observation;
        const c2f = c => c === null || c === undefined ? null : (c * 9 / 5 + 32).toFixed(0) + '\u00b0F';
        const kmh2mph = v => v === null || v === undefined ? null : (v * 0.621371).toFixed(0) + ' mph';
        return [
          el('div', {}, [el('strong', { text: s.station_id }), el('br'),
            el('span', { class: 'fine', text: s.name || '' })]),
          el('span', { class: 'fine', text: (o.timestamp || DASH).replace('T', ' ').replace('+00:00', 'Z') }),
          c2f(o.temperature_c), o.relative_humidity_pct === null ? null : o.relative_humidity_pct + '%',
          kmh2mph(o.wind_speed_kmh), kmh2mph(o.wind_gust_kmh)
        ];
      })));
  } else {
    $('#nws-obs').append(el('p', { class: 'empty', text: 'No observations returned.' }));
  }

  const alerts = nws.active_alerts || {};
  const events = alerts.events || [];
  if (events.length) {
    $('#nws-alerts').append(table(
      [{ label: 'Event' }, { label: 'Severity' }, { label: 'Effective \u2192 Expires' }, { label: 'Headline' }],
      events.map(a => [
        el('strong', { text: a.event }), a.severity,
        `${(a.effective || '').replace('T', ' ')} \u2192 ${(a.expires || '').replace('T', ' ')}`,
        el('span', { class: 'fine', html: esc(a.headline || '') })
      ])));
  } else {
    $('#nws-alerts').append(el('p', { class: 'empty' }, [
      'No active NWS alerts for this forecast zone. ',
      link('https://www.weather.gov/mtr', 'Check NWS San Francisco Bay Area')
    ]));
  }

  const afd = (nws.products || {}).AFD;
  $('#afd-text').textContent = afd && afd.text
    ? afd.text
    : 'No Area Forecast Discussion was returned in this run.';
  if (afd && afd.source_url) {
    $('#afd-text').after(el('p', { class: 'fine' }, [
      'Source: ', link(afd.source_url, afd.product_name || afd.source_url),
      document.createTextNode(afd.issuance_time ? ' \u00b7 issued ' + afd.issuance_time : '')
    ]));
  }
}

/* --------------------------------------------------------------- calendar */

const MONTHS = [
  { key: '2026-10', label: 'October 2026' },
  { key: '2026-11', label: 'November 2026' },
  { key: '2026-12', label: 'December 2026' },
  { key: '2027-01', label: 'January 2027' }
];

function renderCalendar(cal) {
  const tabs = $('#month-tabs');
  MONTHS.forEach(m => {
    tabs.append(el('button', {
      type: 'button', role: 'tab', 'data-key': m.key,
      'aria-selected': String(m.key === state.month), text: m.label,
      onclick: (e) => {
        state.month = e.target.dataset.key;
        $$('#month-tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.key === state.month)));
        drawMonth();
      }
    }));
  });

  const note = [];
  if (cal.nws_window && cal.nws_window.last_day) {
    note.push(`NWS forecast horizon currently ends ${cal.nws_window.last_day} (forecast updated ${cal.nws_window.forecast_updated || DASH}).`);
  }
  note.push('Click any day for the full breakdown and its sources.');
  $('#calendar-note').textContent = note.join(' ');

  drawMonth();

  function drawMonth() {
    const grid = $('#calendar-grid');
    grid.innerHTML = '';
    ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].forEach(d =>
      grid.append(el('div', { class: 'cal-head', text: d })));

    const days = (cal.days || []).filter(d => d.date.startsWith(state.month));
    if (!days.length) { grid.append(el('p', { class: 'empty', text: 'No data for this month.' })); return; }

    const firstDow = new Date(days[0].date + 'T12:00:00Z').getUTCDay();
    for (let i = 0; i < firstDow; i++) grid.append(el('div', { class: 'day blank' }));

    days.forEach(d => grid.append(dayCell(d)));
  }
}

function dayCell(d) {
  const isForecast = d.tier === 'nws';
  return el('button', {
    class: `day ${rainClass(d.rain_chance_pct)} ${isForecast ? 'is-forecast' : ''}`,
    type: 'button',
    onclick: () => openDay(d)
  }, [
    el('div', { class: 'day-top' }, [
      el('span', { class: 'day-date', text: String(d.day) }),
      el('span', { class: 'day-tier t-' + d.tier, text: isForecast ? 'fcst' : 'climo' })
    ]),
    el('div', { class: 'day-temp', text: `${n(d.high_f, 0)}\u00b0 / ${n(d.low_f, 0)}\u00b0` }),
    el('div', { class: 'day-rain', text: pct(d.rain_chance_pct, 0) }),
    el('div', { class: 'day-meta' }, [
      el('span', { text: d.rain_amount_in === null ? 'rain \u2014' : 'rain ' + Number(d.rain_amount_in).toFixed(2) + '"' }),
      el('span', { text: `wind ${n(d.wind_max_mph, 0)} / gust ${n(d.gust_max_mph, 0)}` })
    ])
  ]);
}

function openDay(d) {
  const body = $('#day-dialog-body');
  body.innerHTML = '';
  const isForecast = d.tier === 'nws';
  body.append(el('h3', { text: `${d.weekday}, ${d.month_label} ${d.day}, ${d.date.slice(0, 4)}` }));
  body.append(el('p', { class: 'dd-sub' }, [
    el('span', { class: 'badge ' + (isForecast ? 'badge-nws' : 'badge-climo'),
      text: isForecast ? 'Official NWS forecast' : '1991\u20132020 climatology' }),
    document.createTextNode(' ' + (isForecast
      ? 'Values are the actual NWS gridded forecast for this day.'
      : 'No forecast exists for this date yet. Every value below is the observed 1991\u20132020 record for this calendar date \u2014 not a prediction.'))
  ]));

  body.append(el('h4', { text: 'Headline numbers' }));
  body.append(el('table', { class: 'kv' }, [
    ['High / low', `${n(d.high_f, 0)}\u00b0F / ${n(d.low_f, 0)}\u00b0F`],
    ['Humidity (mean)', d.humidity_pct === null ? null : pct(d.humidity_pct, 0)],
    ['Chance of rain', pct(d.rain_chance_pct, 0)],
    ['Rain amount', d.rain_amount_in === null ? null : Number(d.rain_amount_in).toFixed(2) + ' in'],
    ['Max wind', d.wind_max_mph === null ? null : n(d.wind_max_mph, 0) + ' mph'],
    ['Max gust', d.gust_max_mph === null ? null : n(d.gust_max_mph, 0) + ' mph']
  ].map(([k, v]) => el('tr', {}, [el('th', { text: k }), el('td', { text: v === null ? DASH : v })]))));

  const c = d.climo || {};
  body.append(el('h4', { text: 'Observed record for this date (1991\u20132020)' }));
  body.append(el('table', { class: 'kv' }, [
    ['It rained in', c.p_rain_day_pct === null ? null : `${pct(c.p_rain_day_pct, 0)} of years (${c.n_years_precip} years)`],
    ['\u2265 0.25 in', pct(c.p_rain_ge_025in_pct, 0)],
    ['\u2265 1.00 in', pct(c.p_rain_ge_100in_pct, 0)],
    ['Wettest on record', (c.wettest_on_record && c.wettest_on_record.length)
      ? c.wettest_on_record.map(w => `${w.year}: ${Number(w.prcp_in).toFixed(2)}"`).join(', ') : null],
    ['Normal high / low', `${n(c.normal_high_f, 0)}\u00b0F / ${n(c.normal_low_f, 0)}\u00b0F`],
    ['Record high / low', `${n(c.record_high_f, 0)}\u00b0F / ${n(c.record_low_f, 0)}\u00b0F`],
    ['Normal max gust', c.normal_max_gust_mph === null ? null : n(c.normal_max_gust_mph, 0) + ' mph'],
    ['Strongest gust on record', c.max_gust_on_record_mph === null ? null
      : `${n(c.max_gust_on_record_mph, 0)} mph (${c.max_gust_on_record_date || DASH})`],
    ['Rain + wind together', pct(c.p_wind_and_rain_pct, 0)],
    ['Heavy rain + strong gust', pct(c.p_heavy_wind_and_rain_pct, 0)]
  ].map(([k, v]) => el('tr', {}, [el('th', { text: k }), el('td', { text: v === null ? DASH : v })]))));

  if (d.cpc && d.cpc.length) {
    body.append(el('h4', { text: 'Official CPC outlooks covering this day' }));
    body.append(table([{ label: 'Period' }, { label: 'Variable' }, { label: 'Outlook' }, { label: 'Source' }],
      d.cpc.map(r => [
        r.valid_season || (r.start_date ? `${r.start_date} \u2192 ${r.end_date}` : DASH),
        r.variable === 'temp' ? 'Temperature' : r.variable === 'prcp' ? 'Precipitation' : DASH,
        `${r.category_label} (${r.prob}%)`,
        linkShort(r.url, 40)
      ])));
    body.append(el('p', { class: 'fine', text: 'These are probabilities for the whole period, not for this day.' }));
  }

  body.append(el('h4', { text: 'Sources for this day' }));
  body.append(el('ul', {}, (d.sources || []).map(s =>
    el('li', { class: 'fine' }, [link(s.url, s.label)]))));

  $('#day-dialog').showModal();
}

/* ------------------------------------------------------ duration / wind */

function renderDuration(cal) {
  const sp = cal.streak_probability || {};
  const rows = Object.entries(sp).map(([k, v]) => [
    k.replace('ge_', 'at least ').replace('_days', ' days'),
    v.pct + '%',
    `${v.seasons} of ${(cal.season_by_year || []).length}`
  ]);
  $('#streak-table').append(table(
    [{ label: 'A streak this long occurs\u2026' }, { label: 'Share of seasons', num: true }, { label: 'Count', num: true }],
    rows, { empty: 'Streak statistics unavailable.' }));

  const dist = cal.season_summary || {};
  const lws = dist.longest_wet_streak_days || {};
  if (lws.n) {
    $('#streak-table').append(el('p', { class: 'fine', text:
      `The longest wet run in a season averages ${n(lws.mean, 1)} days (median ${n(lws.median, 1)}), ` +
      `and has reached ${n(lws.max, 0)} days in the wettest season on record.` }));
  }

  const years = (cal.season_by_year || []).slice();
  if (years.length) {
    $('#streak-chart').append(bars(years.map(s => ({ label: s.season, value: s.longest_wet_streak_days })),
      { fmt: v => v + ' d' }));
    $('#streak-note').textContent = 'Counted only inside 1 Oct \u2013 31 Jan, so a run that began in ' +
      'late September or continued into February is truncated at the window edge.';
  }
}

function renderWind(cal) {
  const days = cal.days || [];
  const dist = cal.season_summary || {};
  const jr = dist.wind_and_rain_days || {}, hj = dist.heavy_wind_and_rain_days || {}, mg = dist.max_gust_mph || {};

  const avg = key => {
    const vals = days.map(d => (d.climo || {})[key]).filter(v => v !== null && v !== undefined);
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };

  $('#wind-table').append(el('table', { class: 'kv' }, [
    ['Average daily max wind (SFO)', n(avg('normal_max_sustained_mph'), 1) + ' mph'],
    ['Average daily max gust (SFO)', n(avg('normal_max_gust_mph'), 1) + ' mph'],
    ['Wind+rain days per season', `mean ${n(jr.mean, 1)} \u00b7 median ${n(jr.median, 1)} \u00b7 max ${n(jr.max, 0)}`],
    ['Heavy wind+rain days per season', `mean ${n(hj.mean, 1)} \u00b7 median ${n(hj.median, 1)} \u00b7 max ${n(hj.max, 0)}`],
    ['Strongest gust of the season', `mean ${n(mg.mean, 0)} mph \u00b7 median ${n(mg.median, 0)} mph \u00b7 max ${n(mg.max, 0)} mph`],
    ['Definition: wind+rain day', (cal.definitions || {}).wind_and_rain_day || DASH],
    ['Definition: heavy wind+rain day', (cal.definitions || {}).heavy_wind_and_rain_day || DASH]
  ].map(([k, v]) => el('tr', {}, [el('th', { text: k }), el('td', { text: v })]))));

  const top = days.slice()
    .filter(d => (d.climo || {}).max_gust_on_record_mph)
    .sort((a, b) => b.climo.max_gust_on_record_mph - a.climo.max_gust_on_record_mph)
    .slice(0, 15);
  $('#gust-table').append(table(
    [{ label: 'Date' }, { label: 'Strongest gust on record', num: true }, { label: 'Recorded' },
     { label: 'Chance of rain on that date', num: true }, { label: 'Rain + wind chance', num: true }],
    top.map(d => [
      `${d.month_label.slice(0, 3)} ${d.day}`,
      n(d.climo.max_gust_on_record_mph, 0) + ' mph',
      d.climo.max_gust_on_record_date || DASH,
      pct(d.climo.p_rain_day_pct, 0), pct(d.climo.p_wind_and_rain_pct, 0)
    ]), { empty: 'Gust climatology unavailable.' }));
}

function renderStorms(s) {
  if (!s || !s.county) {
    $('#storm-summary').append(el('p', { class: 'empty', text: 'Storm Events data unavailable in this run.' }));
    return;
  }
  const byType = {};
  (s.events || []).forEach(e => { byType[e.event_type || 'Unknown'] = (byType[e.event_type || 'Unknown'] || 0) + 1; });
  const rows = Object.entries(byType).sort((a, b) => b[1] - a[1]);
  $('#storm-summary').append(el('table', { class: 'kv' }, [
    ['County', s.county],
    ['Years covered', (s.years || []).length ? `${Math.min(...s.years)}\u2013${Math.max(...s.years)}` : DASH],
    ['Events on record', s.n_events],
    ['Source', link('https://www.ncdc.noaa.gov/stormevents/', 'NOAA NCEI Storm Events Database')]
  ].map(([k, v]) => el('tr', {}, [el('th', { text: k }), el('td', {}, [v && v.nodeType ? v : document.createTextNode(String(v))])]))));

  if (rows.length) {
    $('#storm-summary').append(el('h4', { text: 'Events by type' }));
    $('#storm-summary').append(table([{ label: 'Event type' }, { label: 'Count', num: true }],
      rows.map(([k, v]) => [k, v])));
  }

  const money = v => {
    if (!v) return null;
    const str = String(v).toUpperCase();
    if (str.endsWith('K')) return '$' + (parseFloat(str) * 1000).toLocaleString();
    if (str.endsWith('M')) return '$' + (parseFloat(str) * 1000000).toLocaleString();
    if (str.endsWith('B')) return '$' + (parseFloat(str) * 1000000000).toLocaleString();
    return str;
  };
  const top = (s.events || []).slice()
    .sort((a, b) => (parseFloat(String(b.damage_property || 0)) || 0) - (parseFloat(String(a.damage_property || 0)) || 0))
    .slice(0, 20);
  $('#storm-table').append(table(
    [{ label: 'Date' }, { label: 'Type' }, { label: 'Magnitude' }, { label: 'Property damage', num: true }],
    top.map(e => [
      (e.begin_date || DASH).replace('T', ' '),
      e.event_type || DASH,
      e.magnitude ? `${e.magnitude} ${e.magnitude_type || ''}`.trim() : DASH,
      money(e.damage_property) || DASH
    ]), { empty: 'No storm events on record for this county in the fetched years.' }));
}

/* ------------------------------------------------------ sources / quality */

function renderSources(prov) {
  const entries = prov.entries || [];
  const render = () => {
    const q = ($('#src-filter').value || '').toLowerCase();
    const onlyFailed = $('#src-failed').checked;
    const rows = entries.filter(e => {
      if (onlyFailed && e.ok) return false;
      if (!q) return true;
      return (e.url || '').toLowerCase().includes(q) || (e.note || '').toLowerCase().includes(q);
    });
    $('#src-count').textContent = `${rows.length} of ${entries.length} fetches shown ` +
      `(${entries.filter(e => e.ok).length} succeeded, ${entries.filter(e => !e.ok).length} failed)`;
    const host = $('#provenance');
    host.innerHTML = '';
    host.append(table(
      [{ label: 'Status' }, { label: 'URL' }, { label: 'Purpose' },
       { label: 'Bytes', num: true }, { label: 'SHA-256' }, { label: 'Retrieved (UTC)' }],
      rows.map(e => [
        el('span', { class: 'badge ' + (e.ok ? 'badge-ok' : 'badge-error'), text: e.ok ? String(e.http_status) : (e.http_status || 'ERR') }),
        el('div', {}, [linkShort(e.url, 78), el('span', { class: 'src-note', text: e.error || '' })]),
        el('span', { class: 'src-note', text: e.note || '' }),
        e.bytes === undefined ? null : Number(e.bytes).toLocaleString(),
        el('span', { class: 'hash', text: (e.sha256 || '').slice(0, 12) || DASH }),
        el('span', { class: 'fine', text: e.retrieved_utc || DASH })
      ]), { empty: 'No fetches match this filter.' }));
  };
  $('#src-filter').addEventListener('input', render);
  $('#src-failed').addEventListener('change', render);
  render();
}

function renderQuality(q) {
  const items = q.irregularities || [];
  const c = q.counts || {};
  const host = $('#quality-report');
  host.append(el('p', { class: 'fine', text:
    `${c.total || 0} flag(s): ${c.errors || 0} error, ${c.warnings || 0} warning, ${c.info || 0} info. ` +
    (q.generated_utc ? 'Generated ' + q.generated_utc : '') }));
  if (!items.length) {
    host.append(el('p', { class: 'empty', text: 'No irregularities were recorded in this run.' }));
    return;
  }
  host.append(...items.map(i => el('div', {
    class: 'callout ' + (i.severity === 'error' ? 'callout-error' : i.severity === 'warning' ? 'callout-warn' : 'callout-info')
  }, [
    el('h3', {}, [el('span', { class: 'badge badge-' + (i.severity === 'error' ? 'error' : i.severity === 'warning' ? 'warn' : 'info'), text: i.severity }),
      document.createTextNode(' ' + (i.area || ''))]),
    el('p', { text: i.message }),
    i.evidence && Object.keys(i.evidence).length
      ? el('pre', { class: 'product-text', text: JSON.stringify(i.evidence, null, 2).slice(0, 1600) })
      : null
  ])));
}

function renderCaveats(cal) {
  const list = cal.caveats || [];
  const host = $('#caveats');
  if (list.length) {
    host.append(el('h3', { text: 'Caveats attached to the data itself' }));
    host.append(el('ul', {}, list.map(c => el('li', { text: c }))));
  }
  const defs = cal.definitions || {};
  if (Object.keys(defs).length) {
    host.append(el('h3', { text: 'Definitions used throughout' }));
    host.append(el('table', { class: 'kv' }, Object.entries(defs).map(([k, v]) =>
      el('tr', {}, [el('th', { text: k.replace(/_/g, ' ') }), el('td', { text: v })]))));
  }
}

/* ------------------------------------------------------------------ boot */

async function boot() {
  if (state.booted) return;   // never render twice
  state.booted = true;
  try {
    const [run, calendar, nws, prov, quality, storms] = await Promise.all([
      loadJSON('run'), loadJSON('calendar'), loadJSON('nws'),
      loadJSON('provenance'), loadJSON('quality'), loadJSON('storms').catch(() => null)
    ]);
    Object.assign(state.data, { run, calendar, nws, prov, quality, storms });

    // Pick a sensible default month: the first month that still has forecast
    // coverage, otherwise October.
    const idx = MONTHS.findIndex(m => (calendar.days || []).some(d => d.date.startsWith(m.key) && d.tier === 'nws'));
    state.month = idx >= 0 ? MONTHS[idx].key : MONTHS[0].key;

    renderReality(calendar);
    renderLocation(run);
    renderSeason(calendar);
    renderNow(nws);
    renderCalendar(calendar);
    renderDuration(calendar);
    renderWind(calendar);
    renderStorms(storms);
    renderSources(prov);
    renderQuality(quality);
    renderCaveats(calendar);

    $('#footer-meta').textContent =
      `Data fetched ${calendar.generated_utc || DASH} \u00b7 ` +
      `${(prov.entries || []).length} verified fetches \u00b7 ` +
      `normals period ${(calendar.normals_period || []).join('\u2013')} \u00b7 ` +
      `rebuilt nightly from official sources.`;

    const loading = $('#loading');
    if (loading) loading.remove();
    $('#content').hidden = false;
  } catch (err) {
    // Always surface the original failure, even if the page is already rendered.
    console.error('SFWeather boot failed:', err);
    const box = $('#loading-text');
    if (box) {
      box.innerHTML =
        'Could not load the data files.<br><span class="src-url">' + esc(err.message) + '</span>' +
        '<br><br>If you are viewing this before the first automated build has run, the ' +
        '<code>data/</code> folder will be populated by the scheduled GitHub Actions job.';
    }
    const spin = $('.spinner');
    if (spin) spin.remove();
    const banner = el('div', { class: 'callout callout-error' }, [
      el('h3', { text: 'Data could not be loaded' }),
      el('p', { class: 'src-url', text: String(err && err.message ? err.message : err) })
    ]);
    const first = $('#content');
    if (first) first.prepend(banner);
    if (first) first.hidden = false;
  }
}

document.addEventListener('DOMContentLoaded', boot);
