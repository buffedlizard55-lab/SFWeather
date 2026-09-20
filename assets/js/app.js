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
  storms: 'data/storm_events.json',
  landlord: 'data/landlord.json',
  verify: 'data/verify.json',
  digest: 'data/digest.json'
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

/** A value the pipeline already rounded, printed as published (never re-rounded
 *  here, so the page cannot show a different digit from the dataset), or an em
 *  dash when it is absent. */
function fmtOrDash(v) {
  return (v === null || v === undefined || v === '') ? DASH : String(v);
}

/** Reader-facing ENSO phase label. "el_nino" is a data key, not a phrase -
 *  the executive summary used to print it raw. */
function phaseLabel(p) {
  const m = { el_nino: 'El Ni\u00f1o', la_nina: 'La Ni\u00f1a', neutral: 'Neutral' };
  if (p === null || p === undefined || p === '') return DASH;
  return m[p] || String(p).replace(/_/g, ' ');
}

/** Render CPC outlooks for a month, precipitation first and clearly labelled.
 *
 * A CPC outlook is a probability for a whole period and says nothing about a
 * single day, so each line names the variable (Rain / Temp) and the period it
 * is valid for.  Rain lines come first because this dashboard is about rain.
 * If no outlook was sampled for the month this returns an em dash - never
 * "EC", which is a real CPC category (Equal chances) and would assert a
 * forecast that was never fetched.
 */
function cpcOutlookCell(outlooks) {
  const list = (outlooks || []).filter(o => o && o.category_label);
  if (!list.length) return document.createTextNode(DASH);
  const order = { prcp: 0, temp: 1 };
  const sorted = list.slice().sort((a, b) =>
    (order[a.variable] ?? 9) - (order[b.variable] ?? 9));
  const box = el('div', { class: 'cpc-cell' });
  sorted.forEach((o, i) => {
    const label = o.variable === 'prcp' ? 'Rain' : o.variable === 'temp' ? 'Temp' : 'Other';
    box.append(el('div', { class: 'cpc-line' + (i ? '' : ' first') }, [
      el('span', { class: 'cpc-var cpc-var-' + (o.variable || 'other'), text: label }),
      document.createTextNode(` ${o.valid_season || ''}: ${o.category_label} ${pct(o.prob, 0)}`)
    ]));
  });
  return box;
}

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

/** Find a source entry by matching its URL, so callers never depend on order. */
function srcByMatch(sources, re) {
  const hit = (sources || []).find(s => s && s.url && re.test(s.url));
  return hit ? hit.url : null;
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

/** A table cell that accepts a string, a number or an existing DOM node. */
function kvCell(v) {
  if (v === null || v === undefined) return el('td', { text: DASH });
  if (v.nodeType) return el('td', {}, [v]);
  return el('td', { text: String(v) });
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

/** The inch threshold a published DLY-PRCP-PCTALL-GE###HI column means.
 *
 * The digits are HUNDREDTHS of an inch (GE001HI = ">= 0.01 in"), which the
 * pipeline established from the file itself and publishes as
 * layout.thresholds_in - so the label is read from the data rather than typed
 * here, and a mislabelled column is impossible by construction.
 */
function publishedThresholds(key) {
  const cal = state.data.calendar || {};
  const thr = (((cal.daily_normals_official || {}).layout || {}).thresholds_in) || {};
  const v = thr[key];
  return (typeof v === 'number') ? v : null;
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

/* --------------------------------------------------------------- freshness */

function renderDataStatus(cal, quality, prov, verify) {
  const box = $('#data-status');
  if (!box) return;
  const generated = Date.parse((cal || {}).generated_utc || '');
  const now = Date.now();
  const ageHours = Number.isFinite(generated) ? (now - generated) / 3600000 : null;
  const maxAgeHours = 36;
  const fetches = (prov && prov.entries) || [];
  // A fetch that failed is a fetch that was supposed to work.  An expected
  // absence -- the current year's annual NCEI file before the provider publishes
  // it, a station with no observations endpoint -- is reported on its own line,
  // because folding it into the failure count hides a real outage.
  const failed = fetches.filter(e => e && e.ok === false && !e.expected_absent).length;
  const absent = fetches.filter(e => e && e.ok === false && e.expected_absent).length;
  const irregularities = (quality && quality.irregularities) || [];
  const qualityErrors = Number((quality && quality.counts && quality.counts.errors) || 0);
  const verifyFailed = Number((verify && verify.summary && verify.summary.failed) || 0);
  const timestamp = (cal || {}).generated_utc || DASH;
  const dataIsFlagged = qualityErrors > 0 || verifyFailed > 0;
  const fresh = Number.isFinite(ageHours) && ageHours >= 0 && ageHours <= maxAgeHours;
  const classes = dataIsFlagged ? 'callout callout-error'
    : fresh ? 'callout callout-ok' : 'callout callout-warn';
  let headline;
  let detail;
  if (dataIsFlagged) {
    headline = 'Verification flags require review';
    detail = `${qualityErrors} pipeline error${qualityErrors === 1 ? '' : 's'} and ${verifyFailed} failed claim check${verifyFailed === 1 ? '' : 's'} were recorded. This page keeps the last committed snapshot; use the official NWS links below before acting.`;
  } else if (!Number.isFinite(ageHours)) {
    headline = 'Freshness could not be verified';
    detail = 'The dataset has no valid UTC generation timestamp. Use the official NWS links below for the current forecast.';
  } else if (ageHours < 0) {
    headline = 'Freshness could not be verified';
    detail = `The dataset timestamp (${timestamp}) is in the future relative to this browser clock. Use weather.gov directly until the timestamps agree.`;
  } else if (ageHours > maxAgeHours) {
    headline = `Data snapshot is ${ageHours.toFixed(1)} hours old`;
    detail = `This page cannot call NOAA from your browser. The last committed dataset was generated ${timestamp}; the forecast may be stale. Use weather.gov directly for current warnings and forecasts.`;
  } else {
    headline = `Official data snapshot is ${ageHours.toFixed(1)} hours old`;
    detail = `Fetched/build timestamp: ${timestamp} UTC. The nightly job is expected to refresh this page; for life-safety decisions use weather.gov directly.`;
  }
  let summary = `${fetches.length} recorded source fetches · ${failed} failed fetch${failed === 1 ? '' : 'es'}`
    + (absent ? ` · ${absent} absent by design (not-yet-published annual file or station without an observations endpoint)` : '')
    + ` · ${irregularities.length} flagged irregularit${irregularities.length === 1 ? 'y' : 'ies'} · ${verifyFailed} failed claim check${verifyFailed === 1 ? '' : 's'}`;
  if (failed > 0) {
    const which = fetches.filter(e => e && e.ok === false && !e.expected_absent)
      .map(e => String(e.url || '').replace(/^https?:\/\//, '')).slice(0, 3);
    summary += ` — review: ${which.join(', ')}`;
  }
  box.append(el('div', { class: classes }, [
    el('strong', { text: headline }),
    el('span', { class: 'data-status-detail', text: detail }),
    el('span', { class: 'data-status-meta', text: summary })
  ]));
}

/* --------------------------------------------------------------- landlord */

/** The bottom line: the landlord's six questions, answered in the order asked.
 *
 *  Each answer is a block with the question as its heading, the answer as a
 *  sentence, the numbers behind it, the basis those numbers rest on, and the
 *  official file to check them in.  An answer with no source link is refused
 *  rather than rendered - the same rule the cost drivers follow.
 */
function renderBottomLine(ll) {
  const host = $('#landlord-bottom-line');
  if (!host) return;
  const exec = (ll && ll.executive_summary) || {};
  const note = $('#landlord-bottom-line-note');
  if (note) {
    note.textContent = exec.bottom_line_note ||
      'Each answer states the basis it rests on. Nothing here is a forecast for a named day.';
  }
  const rows = exec.bottom_line || [];
  if (!rows.length) {
    host.append(el('p', { class: 'empty', text: 'Executive summary unavailable in this run.' }));
    return;
  }
  host.append(...rows.map(r => {
    // Rows are kept even when a value is missing and rendered as an em dash.
    // Dropping the row instead would hide the hole: a blanked-out figure would
    // simply vanish and the answer would still look complete.
    const numbers = (r.numbers || []).filter(x => x && x.label);
    const srcs = (r.sources || []).filter(s => s && s.url);
    const body = [
      el('p', { class: 'bl-answer', text: r.answer || '' }),
      numbers.length
        ? el('table', { class: 'kv bl-numbers' }, numbers.map(x =>
            el('tr', {}, [el('th', { text: x.label }),
                          el('td', { text: (x.value === null || x.value === undefined)
                            ? DASH : String(x.value) })])))
        : null,
      el('p', { class: 'fine bl-basis' }, [
        el('strong', { text: 'Basis: ' }), document.createTextNode(r.basis || DASH),
        r.confidence ? el('span', { class: 'bl-conf', text: ' \u00b7 ' + r.confidence }) : null
      ])
    ];
    if (!srcs.length) {
      body.push(el('p', { class: 'fine bl-warn',
        text: 'No official source link is attached to this answer, so it is withheld.' }));
      return el('div', { class: 'bl-item bl-item-unsourced' }, [
        el('h4', { text: `${r.n}. ${r.question || ''}` }), ...body
      ]);
    }
    body.push(el('p', { class: 'fine bl-source' }, [
      el('strong', { text: 'Check it: ' }),
      ...srcs.flatMap((s, i) => [
        i ? document.createTextNode(' \u00b7 ') : null,
        link(s.url, s.label || s.url)
      ])
    ]));
    return el('div', { class: 'bl-item' }, [
      el('h4', {}, [
        el('span', { class: 'bl-n', text: String(r.n || '') + '. ' }),
        document.createTextNode(r.question || '')
      ]),
      ...body
    ]);
  }));

  // The official seasonal outlook, kept visibly separate from the observed
  // record above: an outlook is a probability for a whole period.
  const outlook = exec.official_outlook || {};
  const strip = $('#landlord-official');
  if (!strip) return;
  const cells = [];
  const enso = outlook.enso || {};
  if (enso.state) {
    cells.push(el('div', { class: 'off-cell' }, [
      el('div', { class: 'off-label', text: 'Official ENSO state' }),
      el('div', { class: 'off-value', text: enso.state }),
      enso.alert_status ? el('div', { class: 'off-sub', text: 'Alert System Status: ' + enso.alert_status }) : null,
      el('div', { class: 'off-sub' }, [link(enso.source_url, 'CPC ENSO Diagnostic Discussion')])
    ]));
  }
  // CPC's own strength outlook for this El Niño, quoted verbatim from the
  // diagnostic discussion.  The quotes carry CPC's probabilities, so the
  // marker states the project attached none of its own - worded differently
  // from the caveats card's marker on purpose, so the two cards are checked
  // independently (a shared phrase would let one card cover for the other).
  const estr = outlook.enso_strength;
  if (estr && estr.available) {
    const squotes = (estr.quotes || []).map(q => [
      el('blockquote', { class: 'off-quote', text: '\u201c' + q.text + '\u201d' }),
      el('div', { class: 'off-quote-label', text: q.label || q.key || '' })
    ]);
    cells.push(el('div', { class: 'off-cell' }, [
      el('div', { class: 'off-label', text: 'How strong CPC expects this El Ni\u00f1o to get' }),
      ...[].concat(...squotes),
      (estr.issued_line
        ? el('div', { class: 'off-sub', text: 'Discussion issued ' + estr.issued_line })
        : null),
      (estr.not_found && estr.not_found.length
        ? el('div', { class: 'off-sub',
            text: 'Watched for but not stated in this discussion: ' + estr.not_found.join(', ') + '.' })
        : null),
      el('div', { class: 'off-sub' }, [
        document.createTextNode('Quoted verbatim from CPC\u2019s discussion \u2014 no number or date of its own added by this project \u00b7 '),
        link(estr.source_url, 'Read CPC\u2019s ENSO Diagnostic Discussion')
      ])
    ]));
  } else if (estr && !estr.available) {
    cells.push(el('div', { class: 'off-cell' }, [
      el('div', { class: 'off-label', text: 'How strong CPC expects this El Ni\u00f1o to get' }),
      el('div', { class: 'off-sub', text: estr.reason || 'The archived ENSO discussion could not be read this run.' }),
      el('div', { class: 'off-sub' }, [link(estr.source_url, 'Read CPC\u2019s ENSO Diagnostic Discussion')])
    ]));
  }
  const tilt = outlook.cpc_tilt;
  if (tilt) {
    cells.push(el('div', { class: 'off-cell' }, [
      el('div', { class: 'off-label', text: 'Official CPC precipitation outlooks covering Oct 2026 \u2013 Jan 2027' }),
      el('div', { class: 'off-value',
        text: `${tilt.periods_with_a_tilt} of ${tilt.periods_covering_this_season} periods carry a tilt above the ` +
              `${tilt.baseline_pct}% baseline` }),
      tilt.highest_probability
        ? el('div', { class: 'off-sub',
            text: `Strongest: ${tilt.highest_probability.period} \u2014 ` +
                  `${tilt.highest_probability.category_label} at ${tilt.highest_probability.probability_pct}% ` +
                  `(issued ${tilt.highest_probability.issued})` })
        : null,
      el('div', { class: 'off-sub',
        text: `${tilt.periods_at_climatological_baseline} period(s) sit on the baseline and are not counted as a tilt. ` +
              'These are probabilities for whole periods, never for a day.' })
    ]));
  }
  // What the outlook's own authors wrote to qualify it.  Quotations only:
  // CPC's forecasters, verbatim, with the link to read the whole discussion.
  // A discussion that no longer contains a watched-for sentence is reported
  // as not found - it is never paraphrased or held over from a previous run.
  const cav = outlook.prognostic_caveats;
  if (cav && cav.available) {
    const quotes = (cav.quotes || []).map(q => [
      el('blockquote', { class: 'off-quote', text: '\u201c' + q.text + '\u201d' }),
      el('div', { class: 'off-quote-label', text: q.label || q.key || '' })
    ]);
    cells.push(el('div', { class: 'off-cell' }, [
      el('div', { class: 'off-label', text: 'What the outlook\u2019s own authors caution' }),
      ...[].concat(...quotes),
      (cav.issued_line
        ? el('div', { class: 'off-sub', text: 'Discussion issued ' + cav.issued_line })
        : null),
      (cav.not_found && cav.not_found.length
        ? el('div', { class: 'off-sub',
            text: 'Watched for but not stated in this discussion: ' + cav.not_found.join(', ') + '.' })
        : null),
      el('div', { class: 'off-sub' }, [
        document.createTextNode('Verbatim quotations, located by pattern in the fetched text \u2014 no number or date attached by this project \u00b7 '),
        link(cav.source_url, 'Read CPC\u2019s prognostic discussion')
      ])
    ]));
  } else if (cav && !cav.available) {
    cells.push(el('div', { class: 'off-cell' }, [
      el('div', { class: 'off-label', text: 'What the outlook\u2019s own authors caution' }),
      el('div', { class: 'off-sub', text: cav.reason || 'The archived discussion could not be read this run.' }),
      el('div', { class: 'off-sub' }, [link(cav.source_url, 'Read CPC\u2019s prognostic discussion')])
    ]));
  }
  // The one legitimate bridge between "the official outlook says X" and "that
  // costs Y": the same 30 seasons, split by the ENSO phase NOAA published for
  // them.  It is a conditional average of what happened, and the cell says so
  // - it never presents the average as the outlook for this season.
  const cond = outlook.enso_conditioned_record;
  if (cond && cond.mean_in !== null && cond.mean_in !== undefined) {
    const contrast = (cond.contrast || [])
      .filter(c => c.mean_in !== null && c.mean_in !== undefined)
      .map(c => `${c.phase_label || c.phase} ${n(c.mean_in, 2)} in (${c.seasons})`)
      .join(' · ');
    cells.push(el('div', { class: 'off-cell' }, [
      el('div', { class: 'off-label', text: 'What past seasons in this same ENSO phase delivered' }),
      el('div', { class: 'off-value',
        text: `${n(cond.mean_in, 2)} in average` }),
      el('div', { class: 'off-sub',
        text: `${cond.seasons_in_phase} of the 30 seasons in the record sat in ` +
              `${cond.phase_label || cond.phase}; their Oct 1 \u2013 Jan 31 totals ranged ` +
              `${n(cond.min_in, 2)} \u2013 ${n(cond.max_in, 2)} in (median ${n(cond.median_in, 2)}). ` +
              (contrast ? `Other phases: ${contrast}. ` : '') +
              'A conditional average of what happened, not a forecast for 2026-27.' }),
      el('div', { class: 'off-sub' }, [
        link(cond.source_url, 'CPC ONI (phase assignment)'), document.createTextNode(' \u00b7 '),
        link(cond.phase_source_url, 'CPC ENSO Diagnostic Discussion (current state)')
      ])
    ]));
  }
  // The same bridge for the severity questions: hard-rain days, gusts and
  // wind + rain in the seasons that sat in this phase, beside all 30.  Every
  // row prints the phase's n and the all-season figure, so a small-sample
  // conditional average can never be read as a settled number or a forecast.
  const cs = outlook.enso_conditioned_severity;
  if (cs && Array.isArray(cs.rows) && cs.rows.length) {
    const srcs = (cs.sources || []).filter(s => s && s.url);
    cells.push(el('div', { class: 'off-cell off-cell-wide', 'data-test': 'enso-conditioned-severity' }, [
      el('div', { class: 'off-label',
        text: `Hard rain, wind and wind + rain in past ${cs.phase_label || cs.phase} seasons ` +
              `(${cs.seasons_in_phase} of the ${cs.seasons_total}), beside all seasons` }),
      table(
        [{ label: 'Counter (per Oct 1 \u2013 Jan 31 season)' },
         { label: `${cs.phase_label || cs.phase} seasons (n = ${cs.seasons_in_phase}): mean \u00b7 median \u00b7 max`, num: true },
         { label: `All ${cs.seasons_total} seasons: mean \u00b7 max`, num: true }],
        cs.rows.map(r => [
          r.label,
          `${fmtOrDash(r.phase_mean)} \u00b7 ${fmtOrDash(r.phase_median)} \u00b7 ${fmtOrDash(r.phase_max)}`,
          `${fmtOrDash(r.all_mean)} \u00b7 ${fmtOrDash(r.all_max)}`
        ])),
      el('div', { class: 'off-sub', text: cs.how_to_read || '' }),
      srcs.length ? el('div', { class: 'off-sub' }, srcs.flatMap((s, i) => [
        i ? document.createTextNode(' \u00b7 ') : null, link(s.url, s.label || s.url)
      ])) : null
    ]));
  }
  const horizon = outlook.daily_forecast || {};
  if (horizon.official_horizon_ends !== undefined) {
    cells.push(el('div', { class: 'off-cell' }, [
      el('div', { class: 'off-label', text: 'Real day-by-day forecast available today' }),
      el('div', { class: 'off-value', text: `through ${horizon.official_horizon_ends || DASH}` }),
      el('div', { class: 'off-sub',
        text: `${horizon.days_in_this_scoreboard_with_a_real_forecast || 0} of the 123 scoreboard days ` +
              'are inside it, so far. Beyond that, this site shows observed climatology and says so.' })
    ]));
  }
  if (cells.length) strip.append(...cells);
}

function renderSunsetProfile(ll) {
  const host = $('#landlord-sunset-profile');
  if (!host) return;
  host.innerHTML = '';
  const exec = (ll && ll.executive_summary) || {};
  const osp = exec.outer_sunset_profile || {};
  if (!osp.neighborhood) {
    host.append(el('p', { class: 'empty', text: 'Outer Sunset profile unavailable in this run.' }));
    return;
  }
  host.append(el('table', { class: 'kv' }, [
    el('tr', {}, [el('th', { text: 'Neighborhood' }), el('td', { text: osp.neighborhood })]),
    el('tr', {}, [el('th', { text: 'Centroid & Location' }), el('td', { text: osp.centroid_coordinates })]),
    el('tr', {}, [el('th', { text: 'Pacific Ocean Exposure' }), el('td', { text: osp.ocean_exposure })]),
    el('tr', {}, [el('th', { text: 'Building Stock & Vulnerabilities' }), el('td', { text: osp.building_stock_vulnerabilities })]),
    el('tr', {}, [el('th', { text: 'Subsoil & Urban Drainage' }), el('td', { text: osp.soil_and_drainage })]),
    el('tr', {}, [el('th', { text: 'Salt-Air Marine Environment' }), el('td', { text: osp.marine_corrosion })]),
  ]));
}

function renderLandlord(ll, cal) {
  if (!ll || !ll.executive_summary) {
    $('#landlord').append(el('p', { class: 'empty', text: 'Landlord summary unavailable in this run.' }));
    return;
  }
  const exec = ll.executive_summary;
  $('#landlord-key-finding').textContent = exec.key_finding || '';
  renderSunsetProfile(ll);
  renderBottomLine(ll);

  // Stats cards
  const stats = [
    {
      cls: 'total rain',
      title: 'Season total (Oct-Jan)',
      value: exec.season_total_prcp ? `${n(exec.season_total_prcp.mean, 2)} in mean` : DASH,
      sub: exec.season_total_prcp ? `Median ${n(exec.season_total_prcp.median, 2)} in · Range ${n(exec.season_total_prcp.min, 2)} – ${n(exec.season_total_prcp.max, 2)} in · ${exec.season_total_prcp.n} seasons · Source: GHCN-Daily USW00023272` : '',
    },
    {
      cls: 'duration',
      title: 'Longest wet streak',
      value: exec.longest_streak ? `${n(exec.longest_streak.mean, 1)} days avg` : DASH,
      sub: exec.longest_streak ? `Max ${n(exec.longest_streak.max, 0)} days on record · ${exec.streak_probability?.ge_7_days?.pct || DASH}% seasons have ≥7 days, ${exec.streak_probability?.ge_10_days?.pct || DASH}% have ≥10 days` : '',
    },
    {
      // Headline value is the hour-by-hour count when the run has it, because
      // "at the same time" is an hourly statement.  The whole-day figure stays
      // in the subtitle rather than disappearing.
      cls: 'wind',
      title: 'Wind + rain together',
      value: (exec.wind_and_rain_hourly?.available && exec.wind_and_rain_hourly?.days_with_a_simultaneous_hour?.mean !== undefined
        ? `${n(exec.wind_and_rain_hourly.days_with_a_simultaneous_hour.mean, 1)} days/season`
        : (exec.wind_and_rain ? `${n(exec.wind_and_rain.mean, 1)} days/season` : DASH)),
      sub: exec.wind_and_rain_hourly?.available
        ? `Same-hour co-occurrence at SFO (SFO reference value, not a bound for the Sunset) · Median ${n(exec.wind_and_rain_hourly.days_with_a_simultaneous_hour?.median, 0)} · Max ${n(exec.wind_and_rain_hourly.days_with_a_simultaneous_hour?.max, 0)} · whole-day pairing: ${n(exec.wind_and_rain?.mean, 1)} days avg`
        : (exec.wind_and_rain ? `At SFO (SFO reference value, not a bound for the Sunset). Median ${n(exec.wind_and_rain.median, 0)} · Max ${n(exec.wind_and_rain.max, 0)} · Heavy (≥0.5 in + gust ≥35 kt): ${n(exec.heavy_wind_and_rain?.mean, 1)} days avg` : ''),
    },
    {
      cls: 'gust',
      title: 'Strongest gust',
      value: exec.max_gust ? `${n(exec.max_gust.mean, 0)} mph mean max` : DASH,
      sub: exec.max_gust ? `Median ${n(exec.max_gust.median, 0)} mph · Record ${n(exec.max_gust.max, 0)} mph · SFO ASOS` : '',
    },
    {
      cls: 'enso',
      title: 'ENSO now',
      // The ONI value is season-labelled ("JJA 2026"), not month-labelled:
      // an earlier version looked for year_month only and printed a bare
      // "ONI" with the raw "el_nino" token.  Use the season label and the
      // mapped phase; fall back to the raw data only if it is honestly raw.
      value: exec.current_enso
        ? `${exec.current_enso.phase_label || phaseLabel(exec.current_enso.phase)}` +
          (exec.current_enso.oni_c_fmt ? ` ${exec.current_enso.oni_c_fmt}`
            : exec.current_enso.oni_c !== undefined
              ? ` ${exec.current_enso.oni_c > 0 ? '+' : ''}${exec.current_enso.oni_c}°C` : '')
        : DASH,
      sub: exec.current_enso
        ? `${[exec.current_enso.label || exec.current_enso.year_month, 'ONI'].filter(Boolean).join(' ')} · ` +
          `El Niño mean ${n(exec.enso_stratified?.el_nino?.mean, 2)} in vs La Niña ${n(exec.enso_stratified?.la_nina?.mean, 2)} in`
        : '',
    },
    {
      cls: 'rain',
      title: 'Wet days per season',
      value: exec.wet_days_per_season ? `${n(exec.wet_days_per_season.mean, 1)} days` : DASH,
      sub: exec.wet_days_per_season ? `Median ${n(exec.wet_days_per_season.median, 0)} · Min ${n(exec.wet_days_per_season.min, 0)} · Max ${n(exec.wet_days_per_season.max, 0)} · 1991-2020` : '',
    }
  ];
  $('#landlord-stats').append(...stats.map(s => el('div', { class: 'card landlord-stat ' + s.cls }, [
    el('h4', { text: s.title }),
    el('div', { class: 'stat-value', text: s.value }),
    el('div', { class: 'stat-sub', text: s.sub })
  ])));

  // Monthly
  const monthly = ll.monthly || [];
  $('#landlord-monthly').append(table(
    [{ label: 'Month' }, { label: 'Mean (in)', num: true }, { label: 'Median (in)', num: true },
     { label: 'Range (in)', num: true }, { label: 'P90 (in)', num: true }, { label: 'Wet days', num: true }, { label: 'CPC outlook' }],
    monthly.map(m => [
      `${m.month} ${m.year}`,
      n(m.mean_in, 2), n(m.median_in, 2),
      m.min_in !== undefined ? `${n(m.min_in, 2)} – ${n(m.max_in, 2)}` : DASH,
      n(m.p90_in, 2), n(m.expected_wet_days, 1),
      // Label each outlook with the variable it belongs to.  This table is
      // about rain, and an earlier version printed raw "Oct 2026: Above normal
      // 40%" rows that were actually the *temperature* outlook - sitting next
      // to rainfall columns with nothing to say so.
      cpcOutlookCell(m.cpc_outlooks)
    ])
  ));

  // Duration
  const sp = exec.streak_probability || {};
  $('#landlord-duration').append(table(
    [{ label: 'Streak' }, { label: 'Share', num: true }, { label: 'Seasons' }],
    Object.entries(sp).map(([k, v]) => [
      k.replace('ge_', '≥').replace('_days', ' days'),
      pct(v.pct, 1), `${v.seasons} of 30`
    ])
  ));
  $('#landlord-duration-note').textContent =
    `Longest streak per season: mean ${n(exec.longest_streak?.mean, 1)} days, max ${n(exec.longest_streak?.max, 0)} days. ` +
    `A 7-day wet run happens in ${sp.ge_7_days?.pct || DASH}% of years — close to a coin flip. ` +
    `Plan gutters, roof drains, and tenant comms for week-long rain.`;

  // Wind+rain.  Two methods are published side by side: the hour-by-hour
  // co-occurrence (the one that actually means "at the same time") and the
  // whole-day pairing this page used before it.  Neither replaces the other;
  // an unavailable figure says so instead of rendering as a zero.
  const hwr = exec.wind_and_rain_hourly || {};
  const hDays = hwr.days_with_a_simultaneous_hour || {};
  const hHours = hwr.simultaneous_hours_per_season || {};
  const hPair = hwr.days_daily_pair_same_station || {};
  const windRainRows = [];
  if (hwr.available) {
    windRainRows.push([
      'Wind+rain days/season — same HOUR (hour-by-hour record, SFO)',
      `mean ${n(hDays.mean, 1)} · median ${n(hDays.median, 0)} · max ${n(hDays.max, 0)} over ${n(hwr.n_seasons_used, 0)} seasons (${hwr.season_window || DASH})`]);
    windRainRows.push([
      'Simultaneous wind+rain hours/season',
      `mean ${n(hHours.mean, 1)} · median ${n(hHours.median, 0)} · max ${n(hHours.max, 0)}`]);
    windRainRows.push([
      'Wind+rain days/season — same DAY, same station (for comparison)',
      hwr.same_station_daily_fields_available
        ? `mean ${n(hPair.mean, 1)} · median ${n(hPair.median, 0)} · max ${n(hPair.max, 0)}`
        : "not published in this run's hourly dataset"]);
  }
  windRainRows.push([
    'Wind+rain days/season — same DAY, downtown gauge + SFO wind',
    `mean ${n(exec.wind_and_rain?.mean, 1)} · median ${n(exec.wind_and_rain?.median, 0)} · max ${n(exec.wind_and_rain?.max, 0)}`]);
  windRainRows.push([
    'Heavy wind+rain (≥35kt gust + ≥0.5in, whole days)',
    `mean ${n(exec.heavy_wind_and_rain?.mean, 1)} · median ${n(exec.heavy_wind_and_rain?.median, 0)} · max ${n(exec.heavy_wind_and_rain?.max, 0)}`]);
  windRainRows.push([
    'Season max gust (SFO reference value)',
    `mean ${n(exec.max_gust?.mean, 0)} mph · median ${n(exec.max_gust?.median, 0)} mph · max ${n(exec.max_gust?.max, 0)} mph`]);
  windRainRows.push([
    'Source',
    hwr.available
      ? 'NCEI ISD hourly 72494023234 (KSFO) for the hourly figure, GSOD 72494023234 + GHCN-Daily USW00023272 for the whole-day figures — no source held here says whether the ocean-facing Sunset is windier or calmer than SFO, so these are SFO reference values, not a bound'
      : 'NCEI GSOD 72494023234 (KSFO) + GHCN-Daily USW00023272 — no source held here says whether the ocean-facing Sunset is windier or calmer than SFO, so these are SFO reference values, not a bound']);
  $('#landlord-windrain').append(el('table', { class: 'kv' }, windRainRows.map(([k, v]) =>
    el('tr', {}, [el('th', { text: k }), el('td', { text: v })]))));
  if (hwr.available && hwr.method) {
    $('#landlord-windrain').append(el('p', { class: 'fine', text:
      `Hour-by-hour definition: ${hwr.method} Days are local calendar days (${hwr.timezone || 'America/Los_Angeles'}).` }));
  }
  (hwr.notes || []).forEach(note => {
    $('#landlord-windrain').append(el('p', { class: 'fine', text: 'Note: ' + note }));
  });

  // CPC
  const cpcRecs = ll.cpc_outlooks_relevant || [];
  $('#landlord-cpc').append(table(
    [{ label: 'Period' }, { label: 'Variable' }, { label: 'Outlook' }, { label: 'Prob' }, { label: 'Issued' }, { label: 'Source' }],
    cpcRecs.map(r => [
      r.valid_season || DASH,
      r.variable === 'temp' ? 'Temp' : r.variable === 'prcp' ? 'Precip' : DASH,
      r.category_label ? cpcCategoryCell(r) : DASH,
      r.prob !== undefined && r.prob !== null ? r.prob + '%' : DASH,
      r.issued || DASH,
      link(r.url, 'CPC shapefile')
    ]),
    { empty: 'No CPC outlooks for Oct 2026-Jan 2027 could be sampled at this location in this run.' }
  ));
  // The DBF's category field and its probability do not always agree: several
  // CPC polygons carry Cat="Above" with Prob=33.0, and 33% is the baseline for
  // a three-way split.  Say so on the page instead of presenting a no-tilt
  // value as a tilt.
  if (cpcRecs.some(r => r.probability_at_climatological_baseline)) {
    $('#landlord-cpc').append(el('p', { class: 'fine', text:
      'Rows marked “at the 33% baseline” carry a category of Above/Below in CPC’s ' +
      'attribute table but a probability equal to the climatological baseline for a ' +
      'three-way split (100 ÷ 3 = 33.3%). Read those as no tilt. The raw category and ' +
      'probability are shown exactly as CPC published them, and the raw DBF row for ' +
      'each sample ships in the dataset so the two can be compared.' }));
  }

  // High-risk dates
  const high = ll.high_risk_dates || [];
  $('#landlord-highrisk').append(table(
    [{ label: 'Date' }, { label: 'Rain chance', num: true }, { label: 'Mean amount (in)', num: true }, { label: 'Max gust record', num: true }, { label: 'Wind+rain chance', num: true }],
    high.map(d => [
      `${d.month_label} ${d.day}`,
      pct(d.rain_chance_pct, 0),
      n(d.mean_prcp_in, 3),
      d.max_gust_record_mph ? n(d.max_gust_record_mph, 0) + ' mph' : DASH,
      pct(d.wind_and_rain_pct, 0)
    ])
  ));

  // Actions
  const actions = ll.action_items || [];
  const container = $('#landlord-actions');
  container.append(...actions.map(a => {
    const prio = (a.priority || 'medium').toLowerCase();
    return el('div', { class: 'action-item ' + prio }, [
      el('div', { class: 'action-meta' }, [
        el('span', { class: 'badge ' + (prio === 'high' ? 'badge-error' : prio === 'medium' ? 'badge-warn' : 'badge-ok'), text: prio }),
        document.createTextNode(' ' + (a.category || ''))
      ]),
      el('h4', { text: a.title }),
      el('p', { text: a.detail }),
      el('div', { class: 'action-source' }, [
        document.createTextNode('Source: '),
        // Show the whole URL.  An earlier version sliced the display text to 80
        // characters, which rendered "...access/USW000" - a string that looks
        // like a station ID but is not one, on a page whose entire premise is
        // that a reader can click through and check the source by hand.
        link(a.source_url || a.source, a.source_url
          ? a.source_url.replace(/^https?:\/\//, '')
          : a.source)
      ])
    ]);
  }));

  renderCostDrivers(ll);
}

/* ---------------------------------------------- maintenance cost drivers */

/** Ranked repair & maintenance cost drivers, straight from landlord.json.
 *
 *  The block separates two kinds of content on purpose: the "why it matters"
 *  sentence is maintenance *guidance* (labelled as such on the card), while
 *  every row in the evidence table is a number copied from the verified
 *  datasets.  A driver with no evidence rows would be an unverifiable claim,
 *  so the renderer refuses to show one.
 */
function renderCostDrivers(ll) {
  const host = $('#landlord-cost-drivers');
  if (!host) return;
  const exec = (ll && ll.executive_summary) || {};
  const note = $('#landlord-cost-note');
  if (note) note.textContent = exec.cost_drivers_note || '';
  const drivers = exec.cost_drivers || [];
  if (!drivers.length) {
    host.append(el('p', { class: 'empty', text: 'Cost-driver summary unavailable in this run.' }));
    return;
  }
  drivers.forEach(d => {
    const evidence = Array.isArray(d.evidence) ? d.evidence : [];
    if (!evidence.length) return; // never show a claim without its numbers
    const srcNode = el('div', { class: 'action-source' });
    srcNode.append(document.createTextNode('Sources: '));
    let firstSrc = true;
    (Array.isArray(d.sources) ? d.sources : []).forEach(s => {
      if (!s || !s.url) return;
      if (!firstSrc) srcNode.append(document.createTextNode(' \u00b7 '));
      firstSrc = false;
      // Show the whole URL, like the action checklist, so the link text can
      // be compared with the href character for character.
      srcNode.append(link(s.url, s.url.replace(/^https?:\/\//, '')));
    });
    host.append(el('div', { class: 'cost-driver' }, [
      el('div', { class: 'cd-head' }, [
        el('span', { class: 'cd-rank', text: '#' + (d.rank !== undefined ? d.rank : '?') }),
        el('h4', { text: d.driver || DASH })
      ]),
      el('p', { class: 'cd-why' }, [
        el('span', { class: 'cd-why-tag', text: 'Why it matters (guidance, not a weather claim): ' }),
        document.createTextNode(d.why_it_costs || '')
      ]),
      el('table', { class: 'kv cd-ev' }, evidence.map(ev =>
        el('tr', {}, [el('th', { text: ev.label }), el('td', { text: ev.value })]))),
      srcNode
    ]));
  });
}

/* --------------------------------------------------------------- sections */

function renderReality(cal) {
  const win = cal.nws_window || {};
  const covered = win.scoreboard_days_in_horizon || 0;
  const total = (cal.days || []).length;
  // Say how long the official horizon is, not how many scoreboard days fall
  // inside it: today that count is 0 (the horizon ends before 1 October), and
  // "reaches 0 day(s)" reads like a bug rather than a fact.
  const horizon = win.horizon_days || (cal.current_forecast && cal.current_forecast.horizon_days) || 0;
  $('#rc-horizon').textContent = win.last_day
    ? `${horizon} day(s) of real forecast \u2014 through ${win.last_day}` : DASH;
  $('#rc-end').textContent = 'January 2027';
  // The two branches are fully independent sentences.  An earlier version
  // shared a tail ("...carry a real NWS forecast.") between them, so when no
  // day was inside the horizon the page read "...as they come into range.
  // carry a real NWS forecast." - a broken sentence in the one section that
  // exists to explain the limits of the data.
  $('#rc-count').innerHTML = covered === 0
    ? `No day on this scoreboard is inside the official horizon yet \u2014 the horizon ends ` +
      `<strong>${win.last_day || 'n/a'}</strong>, before the first day shown (1 Oct 2026). ` +
      `All <strong>${total}</strong> days therefore show observed 1991\u20132020 climatology and are ` +
      `badged <span class="badge badge-climo">Climatology</span>; none of them is a forecast. ` +
      `The page rebuilds nightly, so days convert to real NWS forecasts automatically ` +
      `as they come into range.`
    : `Right now <strong>${covered}</strong> of the <strong>${total}</strong> days on this scoreboard ` +
      `carry a real NWS forecast and are badged <span class="badge badge-nws">NWS forecast</span>. ` +
      `The remaining <strong>${total - covered}</strong> show observed 1991\u20132020 climatology and are ` +
      `badged <span class="badge badge-climo">Climatology</span>. ` +
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
  /* Official geography evidence for the single point every number refers to.
   * The Census county subdivision is what names the district; "Inner/Outer
   * Sunset" is a local split with no federal boundary, and the naming_note that
   * says so comes from the data rather than being typed here. */
  const g = c.census_geographies || null;
  const geoRows = g ? [
    ['County subdivision (Census)', g.county_subdivision
      ? `${g.county_subdivision} · GEOID ${g.county_subdivision_geoid || DASH}` : null],
    ['County', g.county ? `${g.county} · GEOID ${g.county_geoid || DASH}` : null],
    ['Incorporated place', g.place ? `${g.place} · GEOID ${g.place_geoid || DASH}` : null],
    ['Census tract', g.census_tract
      ? `${g.census_tract} · GEOID ${g.census_tract_geoid || DASH}` : null],
    ['Census block', g.census_block_geoid || null],
    // The layer name carries the Congress the district belongs to (119th,
    // 120th ...); it is published so the vintage the geocoder answered with is
    // visible, never assumed (bug 75).
    ['Congressional district', g.congressional_district
      ? `${g.congressional_district}${g.congressional_district_layer ? ' (' + g.congressional_district_layer + ')' : ''}`
      : null],
    ['Urban area', g.urban_area || null],
    ['Geography source', link(g.url, 'U.S. Census Bureau geocoder — reverse lookup of this point')]
  ] : [
    ['County subdivision (Census)',
      'not retrieved this run — see Data quality; nothing was inferred in its place']
  ];
  $('#tbl-location').append(kvTable([
    ['ZIP code', (run.target || {}).zip || '94122'],
    ['Area label used here', (run.target || {}).label || null],
    ['Latitude', c.lat === undefined ? null : c.lat.toFixed(4) + '\u00b0 N'],
    ['Longitude', c.lon === undefined ? null : c.lon.toFixed(4) + '\u00b0 W'],
    ['Land area', c.land_area_sqmi === undefined ? null : c.land_area_sqmi + ' sq mi'],
    ['Water area', c.water_area_sqmi === undefined ? null : c.water_area_sqmi + ' sq mi'],
    ['Source', link(c.url, 'U.S. Census Bureau Gazetteer' + (c.gazetteer_year ? ' (' + c.gazetteer_year + ')' : ''))],
    ['Verified against Census', c.verified ? 'Yes' : 'No \u2014 fallback value, see data quality'],
    ...geoRows
  ]));
  $('#location-note').textContent =
    'The coordinate is the Census Bureau\u2019s internal point (centroid) for ZIP Code Tabulation Area ' +
    '94122, downloaded and matched in the build rather than typed in. San Francisco has sharp ' +
    'microclimates, so a single point cannot represent the whole ZIP, but it is an official, ' +
    'reproducible choice.' + (g && g.naming_note ? ' ' + g.naming_note : '');
  if (g && g.geography_types_returned && g.geography_types_returned.length) {
    $('#location-note').append(el('span', { class: 'src-url', text:
      ' Geographies returned by the Census for this point: ' +
      g.geography_types_returned.join('; ') + '.' }));
  }

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
  /* Everything below is read from data/enso.json, which the nightly job fills
   * from official CPC endpoints.  No sentence and no number is typed here: the
   * quotes are the verbatim official strings captured at fetch time, each with
   * the SHA-256 of the page they came from. */
  const enso = cal.enso || {};
  const official = enso.latest_official || (enso.official || {}).latest || {};
  const cross = enso.cross_check || {};
  const box = $('#enso-body');
  if (!box) return;

  // Phase and strength are machine tokens ("el_nino", "very_strong").  The
  // pipeline publishes a reader-facing label next to each; fall back to the
  // shared mappers so a token can never be printed raw, and never by
  // character substitution - which is what produced "el nino" here while the
  // executive summary correctly printed "El Niño" from the same value.
  const strengthLabel = s => {
    const m = { very_strong: 'very strong', strong: 'strong', moderate: 'moderate',
                weak: 'weak', neutral: 'neutral' };
    if (s === null || s === undefined || s === '') return '';
    return m[s] || String(s).replace(/_/g, ' ');
  };
  const facts = [
    ['ENSO state (official ONI)', official.label
      ? `${official.label} \u2192 ` +
        `${official.oni_c_fmt || ((official.oni_c > 0 ? '+' : '') + official.oni_c + '\u00b0C')} = ` +
        `${official.phase_label || phaseLabel(official.phase)}, ` +
        `${official.strength_label || strengthLabel(official.strength)}`
      : null],
    ['CPC Alert System Status', enso.diagnostic_status || null],
    ['Official ONI definition', 'ONI = 3-month running mean of ERSSTv5 Ni\u00f1o 3.4 ' +
      'sea-surface-temperature anomalies. NOAA declares El Ni\u00f1o at \u2265 +0.5\u00b0C and ' +
      'La Ni\u00f1a at \u2264 \u22120.5\u00b0C.'],
    ['Official ONI product (number shown above)',
      link((enso.official || {}).url || enso.table_url, 'CPC oni.ascii.txt')],
    ['Raw monthly Ni\u00f1o 3.4 table (cross-check only)',
      link(enso.table_url, 'CPC detrend.nino34.ascii.txt')]
  ];
  box.append(kvTable(facts));

  if (cross && cross.checked) {
    box.append(el('p', { class: 'fine', text:
      'Cross-check: the project also computes its own 3-month mean from the raw monthly ' +
      `table. For ${cross.season_label} it gets ${cross.derived_oni_c}\u00b0C against NOAA's ` +
      `published ${cross.official_oni_c}\u00b0C (difference ${cross.difference_c}\u00b0C). ` +
      'The published product is what this site displays.' }));
  }

  const seasons = (enso.official || {}).seasons || [];
  if (seasons.length) {
    box.append(el('p', { class: 'fine', text: 'Most recent official ONI seasons (as published):' }));
    box.append(table([{ label: 'Season' }, { label: 'ONI (\u00b0C)', num: true }, { label: 'Phase' }],
      seasons.slice().reverse().map(r => [r.label, (r.anomaly_c > 0 ? '+' : '') + r.anomaly_c,
        (r.anomaly_c >= 0.5 ? 'El Ni\u00f1o' : (r.anomaly_c <= -0.5 ? 'La Ni\u00f1a' : 'Neutral'))])));
  }

  /* Verbatim official statements, straight from the fetched pages -------- */
  const sources = (enso.sources || []).filter(x => x.ok !== false);
  sources.forEach(src => {
    const issued = src.issued ? ' issued ' + src.issued : '';
    box.append(el('p', { class: 'fine' }, [
      el('strong', { text: 'Verbatim from ' }), link(src.url, src.label || src.url),
      document.createTextNode(issued + (src.retrieved_utc ? ' \u00b7 retrieved ' + src.retrieved_utc : '') +
        (src.sha256 ? ' \u00b7 sha256 ' + src.sha256.slice(0, 16) + '\u2026' : ''))
    ]));
    (src.key_sentences || []).slice(0, 6).forEach(q =>
      box.append(el('div', { class: 'quote', html: '&ldquo;' + esc(q) + '&rdquo;' })));
  });
  if (!sources.length) {
    box.append(el('p', { class: 'empty', text:
      'No ENSO narrative could be captured from CPC this run; the numbers above still come ' +
      'from the official ONI product.' }));
  }
  const unusable = enso.unusable_pages || [];
  if (unusable.length) {
    box.append(el('p', { class: 'fine', text:
      'Not quoted because the page carries no current-year text (stale or client-rendered): ' +
      unusable.map(u => u.label || u.url).join(', ') + '.' }));
  }

  /* CPC seasonal outlooks -------------------------------------------- */
  const seasonal = (cal.cpc.records || []).filter(r => r.kind === 'season' || r.kind === 'month');
  const wanted = ['SON 2026', 'OND 2026', 'NDJ 2026-2027', 'DJF 2026-2027', 'JFM 2027'];
  const rows = [];
  const periodCell = (label, ...recs) => {
    const issued = recs.filter(Boolean).map(r => r.issued).filter(Boolean).sort().pop();
    return el('div', {}, [
      el('strong', { text: label }),
      issued ? el('span', { class: 'fine', text: ' issued ' + issued }) : null
    ].filter(Boolean));
  };
  wanted.forEach(w => {
    const prcp = seasonal.find(r => r.valid_season === w && r.variable === 'prcp');
    const temp = seasonal.find(r => r.valid_season === w && r.variable === 'temp');
    if (!prcp && !temp) return;
    // A record whose probability sits on CPC's 33.3% three-way baseline is
    // labelled as such here too, so the same value cannot read as a tilt in
    // one table and as no-tilt in another.
    const fmt = r => {
      if (!r) return DASH;
      const node = el('span', {}, [
        document.createTextNode(`${r.category_label} (${r.prob}%)`),
        r.used_nearest_polygon ? document.createTextNode(' \u26a0') : null
      ]);
      if (!r.probability_at_climatological_baseline) return node;
      return el('span', { title: r.baseline_note || '' }, [
        node, document.createTextNode(' '),
        el('span', { class: 'badge badge-warn', text: 'at the 33% baseline' })
      ]);
    };
    rows.push([
      periodCell(w, prcp, temp),
      fmt(temp), fmt(prcp),
      el('div', {}, [link(prcp ? prcp.url : temp.url, 'CPC shapefile'),
        (prcp && prcp.polygon_bbox_lon_lat) ? el('div', { class: 'fine',
          text: 'polygon #' + prcp.polygon_index + ' bbox ' +
            prcp.polygon_bbox_lon_lat.join(', ') }) : null].filter(Boolean))
    ]);
  });
  $('#cpc-season-table').append(el('h4', { text: 'Outlooks whose period overlaps 1 Oct 2026 \u2013 31 Jan 2027' }));
  $('#cpc-season-table').append(table(
    [{ label: 'Period' }, { label: 'Temperature' }, { label: 'Precipitation' }, { label: 'Source' }],
    rows,
    { empty: 'No CPC long-lead outlook could be sampled for this location.' }));
  // Everything else CPC published was also sampled, but its period does NOT
  // reach into this window, so it belongs in its own clearly-labelled table.  It
  // used to be appended to the table above, under a caption claiming those were
  // the only outlooks that cover Oct 2026 - Jan 2027, which they were not.
  const other = seasonal.filter(r => !(wanted.includes(r.valid_season)));
  if (other.length) {
    const orows = other.filter(r => r.variable === 'prcp').map(r => {
      const t = seasonal.find(x => x.valid_season === r.valid_season && x.variable === 'temp');
      return [periodCell(r.valid_season + (r.kind === 'month' ? ' (month)' : ''), r, t),
        t ? `${t.category_label} (${t.prob}%)` + (t.used_nearest_polygon ? ' \u26a0' : '') : DASH,
        `${r.category_label} (${r.prob}%)` + (r.used_nearest_polygon ? ' \u26a0' : ''),
        link(r.url, 'CPC shapefile')];
    });
    if (orows.length) {
      $('#cpc-season-table').append(el('h4', { text: 'Other CPC periods sampled at this point (outside the Oct 2026 \u2013 Jan 2027 window)' }));
      $('#cpc-season-table').append(el('p', { class: 'fine', text:
        'Shown for completeness and to prove the sampler read the whole archive. ' +
        'These periods do not cover the season this site is about, so nothing here ' +
        'is used anywhere else on the page.' }));
      $('#cpc-season-table').append(table(
        [{ label: 'Period' }, { label: 'Temperature' }, { label: 'Precipitation' }, { label: 'Source' }],
        orows));
    }
  }
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
  const stratStreaks = cal.enso_stratified_streaks || {};
  // Label from the record the pipeline publishes; the previous hard-coded
  // ternary left "neutral" lower-case beside "El Niño" / "La Niña".
  //
  // The last two columns answer the duration question for the phase the season
  // is actually in.  Both are observed frequencies in that subset of the 30
  // seasons - the column header carries the denominator so a small sample can
  // never be read as a settled number, and a phase with no 7+ day spell shows
  // the count (0 of n) rather than a blank.
  // The severity counters per phase (hard-rain days, gusts, wind + rain) come
  // from the same season rows; the three columns added here print the mean
  // with the max in brackets, exactly as the dataset carries them.
  const stratSev = cal.enso_stratified_severity || {};
  const sevCell = (phase, key) => {
    const m = ((stratSev[phase] || {}).metrics || {})[key];
    if (!m || m.mean === undefined || m.mean === null) return null;
    // Counts are published to one decimal and their maxima are whole days;
    // n() keeps 4.0 from printing as 4 beside a 3.7 in the row above.
    return `${n(m.mean, 1)} (max ${n(m.max, 0)})`;
  };
  const srows = Object.entries(strat).map(([phase, d]) => {
    const st = stratStreaks[phase] || {};
    const longRun = st.longest_streak_days || {};
    return [
      d.phase_label || phaseLabel(phase),
      d.n, n(d.mean, 2), n(d.median, 2),
      d.min === undefined ? null : `${Number(d.min).toFixed(2)} \u2013 ${Number(d.max).toFixed(2)}`,
      st.ge_7_days === undefined ? null : `${n(st.ge_7_days.pct, 1)}% (${st.ge_7_days.seasons} of ${st.n})`,
      longRun.mean === undefined ? null : `${n(longRun.mean, 1)} d (max ${n(longRun.max, 0)})`,
      sevCell(phase, 'wet_days_ge_1in'),
      sevCell(phase, 'gust_days_ge_40kt'),
      sevCell(phase, 'wind_and_rain_days')
    ];
  });
  $('#enso-strat').append(table(
    [{ label: 'Phase' }, { label: 'Seasons', num: true }, { label: 'Mean (in)', num: true },
     { label: 'Median (in)', num: true }, { label: 'Range (in)', num: true },
     { label: '7+ day wet spell', num: true }, { label: 'Longest run, mean', num: true },
     { label: 'Days \u2265 1.00 in, mean', num: true }, { label: 'Days gust \u2265 40 kt, mean', num: true },
     { label: 'Wind + rain days (whole-day), mean', num: true }], srows,
    { empty: 'Not enough ENSO-classified seasons to stratify.' }));
  if (Object.keys(stratStreaks).length) {
    $('#enso-strat').append(el('p', { class: 'fine', text:
      'The 7+ day spell and longest-run columns condition the rain-duration question on the phase: how often a ' +
      '7+ consecutive-wet-day spell occurred in the seasons the record assigns to that phase, ' +
      'and the mean longest spell in those seasons. They are observed frequencies in that ' +
      'subset of the 1991-2020 seasons - the sample size is printed in the column - not a ' +
      'forecast for any coming season.' }));
  }
  if (Object.keys(stratSev).length) {
    $('#enso-strat').append(el('p', { class: 'fine', text:
      'The last three columns do the same for severity: mean days per season with \u2265 1.00 in of rain ' +
      '(downtown gauge), with a gust \u2265 40 kt (SFO), and with rain and sustained wind \u2265 20 kt on the ' +
      'same day (whole-day pairing, SFO), each with the worst season in brackets. Same rows, same ' +
      'small samples, same caveat: observed, not forecast.' }));
  }

  /* discussions --------------------------------------------------------- */
  const discs = (cal.cpc.discussions || []).filter(d => !d.stale);
  $('#discussions').append(...(discs.length ? discs : []).map(d => el('div', { class: 'quote' }, [
    el('strong', { text: d.label }), el('br'),
    link(d.human_url || d.url, d.url)
  ])));
  if (!discs.length) $('#discussions').append(el('p', { class: 'empty', text: 'No CPC discussion passed the staleness check in this run.' }));
}

/** Storm-pattern language in NWS's own Area Forecast Discussion.
 *
 *  Every line rendered here is a verbatim quotation produced by
 *  climo.afd_language_scan() and re-checked against the fetched product text by
 *  the claim ledger.  Nothing in this function derives a number, attaches a date
 *  to a quotation, or paraphrases: the scan publishes the sentence, the section
 *  it came from and the phrase that matched, and that is all that is shown.
 */
function renderAfdLanguage(cal) {
  const box = $('#afd-language');
  if (!box) return;
  const a = (cal || {}).afd_language;
  if (!a) {
    box.append(el('p', { class: 'empty', text:
      'The Area Forecast Discussion scan is not present in this dataset.' }));
    return;
  }
  if (!a.scanned) {
    box.append(el('p', { class: 'empty', text:
      'Not scanned this run: ' + (a.reason || 'no reason recorded') + '.' }));
    if (a.source_url) box.append(el('p', { class: 'fine' }, [link(a.source_url, 'NWS product endpoint')]));
    return;
  }

  box.append(el('p', { class: 'fine' }, [
    el('strong', { text: 'Discussion issued ' }),
    document.createTextNode(a.issuance_time || DASH),
    document.createTextNode(` \u00b7 ${a.sentences_scanned} sentences scanned across ` +
      `${(a.sections_scanned || []).length} land-forecast section(s)` +
      ` (${(a.sections_scanned || []).join(', ') || 'none'}) \u00b7 ` +
      `${(a.sections_excluded_this_run || []).length} section(s) excluded: ` +
      `${(a.sections_excluded_this_run || []).join(', ') || 'none'} \u00b7 ` +
      `${a.furniture_sentences_dropped} product-furniture line(s) dropped \u00b7 `),
    link(a.source_url, 'open the discussion at NWS'),
    document.createTextNode(` \u00b7 ${a.text_chars} characters fetched`)
  ]));

  const cats = a.categories || [];
  box.append(table(
    [{ label: 'Pattern' }, { label: 'Sentences flagged', num: true }, { label: 'Why a landlord cares' }],
    cats.map(c => [
      el('span', { class: 'afd-cat', text: c.label }),
      el('span', {
        class: 'pill ' + (c.sentence_count > 0 ? 'pill-warn' : 'pill-ok'),
        text: c.sentence_count > 0 ? `${c.sentence_count} found` : 'none found'
      }),
      el('span', { class: 'fine', text: c.why_it_matters })
    ]),
    { empty: 'No categories were scanned.' }));

  const flagged = cats.filter(c => (c.sentences || []).length);
  if (!flagged.length) {
    box.append(el('div', { class: 'callout callout-info' }, [
      el('p', { text: a.none_found_statement || 'No listed phrase was found in this discussion.' })
    ]));
  } else {
    flagged.forEach(c => {
      box.append(el('h4', { class: 'afd-heading', text: c.label }));
      (c.sentences || []).forEach(s => {
        box.append(el('div', { class: 'quote' }, [
          el('div', { class: 'afd-quote', text: '\u201c' + s.sentence + '\u201d' }),
          el('div', { class: 'fine' }, [
            document.createTextNode(`Section: ${s.section} \u00b7 matched: ` +
              (s.matched_patterns || []).join(', '))
          ])
        ]));
      });
      if (c.note) box.append(el('p', { class: 'fine', text: c.note }));
    });
  }

  box.append(el('p', { class: 'fine' }, [
    el('strong', { text: 'Scope: ' }), document.createTextNode(a.scope_caveat || DASH)
  ]));
  box.append(el('p', { class: 'fine' }, [
    el('strong', { text: 'How to read this: ' }), document.createTextNode(a.usage_note || DASH)
  ]));
  box.append(el('p', { class: 'fine' }, [
    el('strong', { text: 'Verbatim rule: ' }), document.createTextNode(a.verbatim_rule || DASH)
  ]));

  /* Issuance history: "the last discussion to mention X was ...".  A history
   * of what NWS wrote -- quotations only, same as the live scan -- never a
   * forecast and never attached to a scoreboard day. */
  const hist = a.history || {};
  const lm = hist.last_mention || {};
  if (Object.keys(lm).length) {
    box.append(el('h4', { text: 'When each pattern was last mentioned' }));
    box.append(el('p', { class: 'fine', text:
      `${hist.n_issuances || 0} issuance(s) on file. ` + (hist.note || '') }));
    box.append(table(
      [{ label: 'Pattern' }, { label: 'Last discussion mentioning it' }, { label: 'In tonight\u2019s discussion' }],
      Object.values(lm).map(b => [
        b.label || DASH,
        b.last_issuance_time || 'never on file',
        el('span', {
          class: 'pill ' + ((b.current_sentence_count || 0) > 0 ? 'pill-warn' : 'pill-ok'),
          text: (b.current_sentence_count || 0) > 0
            ? `${b.current_sentence_count} sentence(s)` : 'not tonight'
        })
      ])));
    box.append(el('p', { class: 'fine' }, ['Full history: ',
      link('data/afd_history.json', 'afd_history.json')]));
  }
}

function renderNow(nws, cal) {
  /* Current official forecast, day by day ---------------------------------
   * This is the only part of the site that is a real forecast, so it is shown
   * first and it is not filtered to the Oct-Jan window: whatever the NWS
   * horizon reaches today is what appears here. */
  const cf = (cal || {}).current_forecast || {};
  const cfDays = cf.days || [];
  const cfBox = $('#now-current');
  if (cfBox) {
    if (cfDays.length) {
      cfBox.append(el('p', { class: 'fine', text:
        'Official NWS gridded forecast for the 94122 point, aggregated to local calendar ' +
        `days from the hourly grid. Horizon: ${cf.first_day} to ${cf.last_day} ` +
        `(${cf.horizon_days} days). This window is updated by the nightly job; it is the only ` +
        'part of this site that is a forecast rather than a climatology.' }));
      // The first and last day of the horizon are partial: the grid starts and
      // ends mid-day, so their "high" is the high of the hours covered, not of
      // the calendar day.  The hour count is published for exactly this reason
      // and used to be dropped on the floor, which made a partial day look like
      // it disagreed with NWS's own day-level forecast.
      const partial = d => (d.hours_covered !== null && d.hours_covered !== undefined
        && d.hours_covered < 24);
      cfBox.append(table(
        [{ label: 'Day' }, { label: 'Grid hours', num: true }, { label: 'High / low', num: true },
         { label: 'Humidity (mean)', num: true },
         { label: 'Rain chance (max hourly POP)', num: true }, { label: 'Rain amount (NWS QPF)', num: true },
         { label: 'Wind max', num: true }, { label: 'Gust max', num: true }],
        cfDays.map(d => [
          el('div', {}, [el('strong', { text: d.date }), el('br'),
            el('span', { class: 'fine', text: d.weekday || '' })]),
          partial(d)
            ? el('span', { class: 'pill pill-warn', text: `${d.hours_covered} of 24 (partial day)` })
            : el('span', { class: 'fine', text: `${d.hours_covered === null || d.hours_covered === undefined ? DASH : d.hours_covered} of 24` }),
          `${n(d.high_f, 0)}\u00b0F / ${n(d.low_f, 0)}\u00b0F`,
          d.humidity_pct === null ? null : pct(d.humidity_pct, 0) +
            (d.humidity_min_pct !== null && d.humidity_max_pct !== null
              ? ` (${n(d.humidity_min_pct, 0)}\u2013${n(d.humidity_max_pct, 0)}%)` : ''),
          pct(d.rain_chance_pct, 0),
          d.rain_amount_in === null ? null : Number(d.rain_amount_in).toFixed(2) + ' in',
          d.wind_max_mph === null ? null : n(d.wind_max_mph, 0) + ' mph',
          d.gust_max_mph === null ? null : n(d.gust_max_mph, 0) + ' mph'
        ])));
      if (!cf.inside_season_window) {
        cfBox.append(el('p', { class: 'fine', text:
          'Note: these days fall before 1 October 2026, so they are outside the Oct 2026 \u2013 ' +
          'Jan 2027 scoreboard. They are shown because they are the current official forecast.' }));
      }
      const nPartial = cfDays.filter(partial).length;
      if (nPartial) {
        cfBox.append(el('p', { class: 'fine', text:
          `${nPartial} of these ${cfDays.length} days cover only part of the calendar day, ` +
          'because the NWS hourly grid begins and ends mid-day. On a partial day the high ' +
          'and low are the extremes of the hours covered, so they can differ from NWS\u2019s ' +
          'own day-level forecast for the same date \u2014 that is a coverage difference, not a ' +
          'disagreement. The \u201cGrid hours\u201d column shows exactly how much of each day is covered.' }));
      }
      cfBox.append(el('p', { class: 'fine' }, [
        'Issued ', document.createTextNode(cf.forecast_updated || DASH), ' \u00b7 ',
        // Select sources by what they are, not by position: inserting the
        // gridpoint endpoint into the list shifted these indices and made
        // "Open on weather.gov" point at an API URL.
        link(srcByMatch(cf.sources, /forecast\.weather\.gov/), 'Open on weather.gov'),
        ' \u00b7 ', link(srcByMatch(cf.sources, /forecast\/hourly/), 'NWS API endpoint'),
        ' \u00b7 ', link(srcByMatch(cf.sources, /gridpoints\/[^/]+\/\d+,\d+$/), 'gridpoint data'),
        document.createTextNode(' \u00b7 rain chance is the maximum hourly NWS POP; wind is the hourly maximum. ' +
          'Rain amount and gusts are not carried by the hourly product for this grid cell, so they come from the ' +
          'NWS gridpoint QPF and windGust series - each day\u2019s dialog names the basis actually used.')
      ]));
    } else {
      cfBox.append(el('p', { class: 'empty', text: 'No current NWS forecast was captured this run.' }));
    }
  }

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

  // The NWS station feed returns whatever stations NWS associates with this
  // point, which for 94122 includes sites 11-14 miles away and personal weather
  // stations relayed through MADIS.  A reader cannot judge "latest conditions in
  // 94122" without the distance, so it is shown, and the list is ordered by it.
  const obs = (nws.stations || []).filter(s => s.observation && s.observation.timestamp)
    .slice()
    .sort((a, b) => (a.distance_m || 1e12) - (b.distance_m || 1e12));
  if (obs.length) {
    $('#nws-obs').append(el('p', { class: 'fine', text:
      'These are the stations the NWS feed associates with this point, nearest first. ' +
      'Only the closest is inside the ZIP code; the rest are 4\u201315 miles away and, in San ' +
      'Francisco\u2019s microclimates, can read several degrees apart from the Sunset. ' +
      'Distances are the great-circle distance from the ZIP centroid.' }));
    $('#nws-obs').append(table(
      [{ label: 'Station' }, { label: 'Distance', num: true }, { label: 'Observed' }, { label: 'Temp' },
       { label: 'RH' }, { label: 'Wind' }, { label: 'Gust' }],
      obs.map(s => {
        const o = s.observation;
        const c2f = c => c === null || c === undefined ? null : (c * 9 / 5 + 32).toFixed(0) + '\u00b0F';
        const kmh2mph = v => v === null || v === undefined ? null : (v * 0.621371).toFixed(0) + ' mph';
        const mi = (s.distance_m === null || s.distance_m === undefined)
          ? null : (s.distance_m / 1609.344).toFixed(1) + ' mi';
        return [
          el('div', {}, [el('strong', { text: s.station_id }), el('br'),
            el('span', { class: 'fine', text: s.name || '' })]),
          mi === null ? null
            : el('span', { class: Number.parseFloat(mi) < 1 ? '' : 'fine', text: mi }),
          el('span', { class: 'fine', text: (o.timestamp || DASH).replace('T', ' ').replace('+00:00', 'Z') }),
          c2f(o.temperature_c),
          // The NWS observation is a computed RH with ~14 significant figures.
          // No official product publishes humidity to that precision, and
          // showing it read like a broken value, so it is rounded for display
          // only - the full value stays in data/nws.json.
          o.relative_humidity_pct === null || o.relative_humidity_pct === undefined
            ? null
            : Number(o.relative_humidity_pct).toFixed(0) + '%',
          kmh2mph(o.wind_speed_kmh), kmh2mph(o.wind_gust_kmh)
        ];
      })));
  } else {
    $('#nws-obs').append(el('p', { class: 'empty', text: 'No observations returned.' }));
  }

  const alerts = nws.active_alerts || {};
  const events = alerts.events || [];
  const real = events.filter(a => !a.is_test);
  const tests = events.filter(a => a.is_test);
  if (real.length) {
    $('#nws-alerts').append(table(
      [{ label: 'Event' }, { label: 'Severity' }, { label: 'Effective \u2192 Expires' }, { label: 'Headline' }],
      real.map(a => [
        el('strong', { text: a.event }), a.severity,
        `${(a.effective || '').replace('T', ' ')} \u2192 ${(a.expires || '').replace('T', ' ')}`,
        el('span', { class: 'fine', html: esc(a.headline || '') })
      ])));
  } else {
    $('#nws-alerts').append(el('p', { class: 'empty' }, [
      'No active NWS warning, watch or advisory for this forecast zone. ',
      link('https://www.weather.gov/mtr', 'Check NWS San Francisco Bay Area')
    ]));
  }
  if (tests.length) {
    $('#nws-alerts').append(el('p', { class: 'fine', text:
      `${tests.length} NOAA test message(s) were also active at retrieval time and are ` +
      'deliberately NOT counted as real alerts: ' +
      tests.map(t => (t.headline || t.event || 'test message')).join(' | ') }));
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

    // Keep the "jump to a date" control honest about what this month contains.
    if (days.length) state.monthSpan = { first: days[0].date, last: days[days.length - 1].date };
  }

  /* "Jump to a date" ------------------------------------------------------
   * The brief asks to be able to look up one given day between Oct 2026 and
   * Jan 2027; scanning 123 cells for a single date is not usable, so a date
   * picker switches to the right month, opens that day, and marks the cell.
   * An out-of-range or unpublished date says so rather than failing quietly. */
  const findInput = $('#day-find');
  const findBtn = $('#day-find-go');
  const findHelp = $('#day-find-help');
  const allDays = cal.days || [];
  if (allDays.length) {
    if (findInput) {
      findInput.min = allDays[0].date;
      findInput.max = allDays[allDays.length - 1].date;
    }
    if (findHelp) {
      findHelp.textContent = `Between ${allDays[0].date} and ` +
        `${allDays[allDays.length - 1].date} \u2014 or click any day.`;
    }
  }
  const jump = () => {
    if (!findInput) return;
    const v = findInput.value;
    if (!v) { if (findHelp) findHelp.textContent = 'Pick a date first.'; return; }
    const hit = allDays.find(d => d.date === v);
    if (!hit) {
      const lo = allDays.length ? allDays[0].date : null;
      const hi = allDays.length ? allDays[allDays.length - 1].date : null;
      if (findHelp) {
        findHelp.textContent = (lo && hi && v >= lo && v <= hi)
          ? `${v} is inside the window but is not in this snapshot \u2014 reload, or use the official links below.`
          : `${v} is outside the scoreboard window (${lo} to ${hi}).`;
      }
      return;
    }
    state.month = v.slice(0, 7);
    $$('#month-tabs button').forEach(b =>
      b.setAttribute('aria-selected', String(b.dataset.key === state.month)));
    drawMonth();
    const cell = $$('#calendar-grid .day:not(.blank)').find(c => c.dataset.date === v);
    if (cell) { cell.classList.add('found'); if (cell.focus) cell.focus(); }
    openDay(hit);
  };
  if (findBtn) findBtn.addEventListener('click', jump);
  if (findInput) {
    findInput.addEventListener('change', jump);
    findInput.addEventListener('keydown', e => { if (e.key === 'Enter') jump(); });
  }
}

function dayCell(d) {
  const isForecast = d.tier === 'nws';
  return el('button', {
    class: `day ${rainClass(d.rain_chance_pct)} ${isForecast ? 'is-forecast' : ''}`,
    type: 'button',
    'data-date': d.date,
    'aria-label': `${d.date}: high ${n(d.high_f, 0)}F, low ${n(d.low_f, 0)}F, ` +
      `rain chance ${pct(d.rain_chance_pct, 0)}, rain amount ` +
      `${d.rain_amount_in === null ? 'not published' : Number(d.rain_amount_in).toFixed(2) + ' in'}, ` +
      `wind ${n(d.wind_max_mph, 0)} mph, gust ${n(d.gust_max_mph, 0)} mph, ` +
      `${isForecast ? 'official NWS forecast' : '1991-2020 climatology (not a forecast)'}`,
    onclick: () => openDay(d)
  }, [
    el('div', { class: 'day-top' }, [
      el('span', { class: 'day-date', text: String(d.day) }),
      el('span', { class: 'day-tier t-' + d.tier, text: isForecast ? 'fcst' : 'climo' })
    ]),
    el('div', { class: 'day-temp', text: `${n(d.high_f, 0)}\u00b0 / ${n(d.low_f, 0)}\u00b0` }),
    el('div', { class: 'day-rain', text: pct(d.rain_chance_pct, 0) }),
    el('div', { class: 'day-meta' }, [
      // On a forecast day this is the official QPF for that day; on a
      // climatology day it is the 1991-2020 *mean daily total* for that calendar
      // date.  Labelled differently on purpose: a reader must never read a
      // 30-year mean as "0.01 in is going to fall on this day".
      el('span', { text: d.rain_amount_in === null
        ? (isForecast ? 'rain \u2014' : 'mean \u2014')
        : (isForecast ? 'rain ' : 'mean ') + Number(d.rain_amount_in).toFixed(2) + '"' }),
      el('span', { text: `wind ${n(d.wind_max_mph, 0)} / gust ${n(d.gust_max_mph, 0)}` }),
      el('span', { text: d.humidity_pct === null ? 'RH \u2014' : 'RH ' + n(d.humidity_pct, 0) + '%' })
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
  /* Every field names the basis it used.  withBasis() is the single place that
   * pattern is written, so a field cannot quietly lose its provenance line:
   * a value with no basis string renders as the value alone, and the claim
   * ledger fails the run if any of the six is missing from the data. */
  const withBasis = (value, basis, absentMessage) => {
    if (value === null || value === undefined) {
      return el('span', { class: 'fine', text: absentMessage || DASH });
    }
    return el('span', {}, [document.createTextNode(String(value)),
      basis ? el('span', { class: 'fine', text: ' \u00b7 ' + basis }) : null].filter(Boolean));
  };
  body.append(el('table', { class: 'kv' }, [
    ['High / low', withBasis(`${n(d.high_f, 0)}\u00b0F / ${n(d.low_f, 0)}\u00b0F`, d.temp_basis)],
    ['Humidity (mean)', withBasis(d.humidity_pct === null ? null : pct(d.humidity_pct, 0),
      d.humidity_basis, 'not available from official normals')],
    [isForecast ? 'Chance of rain (max hourly POP)' : 'Chance of rain (1991–2020)',
      withBasis(d.rain_chance_pct === null ? null : pct(d.rain_chance_pct, 0),
        d.rain_chance_basis)],
    [isForecast ? 'Rain amount' : 'Rain amount (1991–2020 mean)',
      withBasis(d.rain_amount_in === null ? null : Number(d.rain_amount_in).toFixed(2) + ' in',
        d.rain_amount_basis, 'no official QPF published for this day')],
    ['Max wind', withBasis(d.wind_max_mph === null ? null : n(d.wind_max_mph, 0) + ' mph',
      d.wind_basis)],
    ['Max gust', withBasis(d.gust_max_mph === null ? null : n(d.gust_max_mph, 0) + ' mph',
      d.gust_basis, 'no official gust published for this day')]
  ].map(([k, v]) => el('tr', {}, [el('th', { text: k }), kvCell(v)]))));

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
  ].map(([k, v]) => el('tr', {}, [el('th', { text: k }), kvCell(v)]))));

  // ---- NOAA's own published normals for this date, next to this project's ----
  const off = d.official_normal;
  if (off) {
    body.append(el('h4', { text: 'NOAA\u2019s published normals for this date (official)' }));
    // The threshold each GE###HI column means is published with the data
    // (layout.thresholds_in) rather than re-typed here, so the label and the
    // number can never drift apart.  The digits are hundredths of an inch:
    // GE001HI is ">= 0.01 in".
    const ge = (key) => {
      const t = publishedThresholds(key);
      return t === null ? '>= ' + key : '>= ' + t.toFixed(2) + ' in';
    };
    body.append(el('p', { class: 'fine', text:
      'Read column-for-column from NOAA NCEI\u2019s 1991-2020 daily normals for this station. ' +
      'The \u201cthis project\u201d column is the site\u2019s own count over the same 30 seasons of ' +
      'GHCN-Daily. Both are shown and the difference is stated \u2014 the two are never averaged ' +
      'into one number. NOAA smooths its published values across neighbouring dates while ' +
      'this project\u2019s are raw counts in 3.33-point steps, so a few points of difference ' +
      'is expected; a large one would be a problem and is flagged.' }));
    const pubRows = [
      ['Normal high (DLY-TMAX-NORMAL)', off.normal_high_f, 'normal high', '\u00b0F'],
      ['Normal low (DLY-TMIN-NORMAL)', off.normal_low_f, 'normal low', '\u00b0F'],
      [ge('p_pcp_ge_0p01in_pct') + ' (PCTALL-GE001HI)', off.p_pcp_ge_0p01in_pct,
        'share of years with >= 0.01 in', '%'],
      [ge('p_pcp_ge_0p10in_pct') + ' (PCTALL-GE010HI)', off.p_pcp_ge_0p10in_pct, null, '%'],
      [ge('p_pcp_ge_0p25in_pct') + ' (PCTALL-GE025HI)', off.p_pcp_ge_0p25in_pct,
        'share of years with >= 0.25 in', '%'],
      [ge('p_pcp_ge_0p50in_pct') + ' (PCTALL-GE050HI)', off.p_pcp_ge_0p50in_pct, null, '%'],
      [ge('p_pcp_ge_1p00in_pct') + ' (PCTALL-GE100HI)', off.p_pcp_ge_1p00in_pct,
        'share of years with >= 1.00 in', '%'],
      [ge('p_pcp_ge_2p00in_pct') + ' (PCTALL-GE200HI)', off.p_pcp_ge_2p00in_pct, null, '%'],
      [ge('p_pcp_ge_4p00in_pct') + ' (PCTALL-GE400HI)', off.p_pcp_ge_4p00in_pct, null, '%'],
      [ge('p_pcp_ge_6p00in_pct') + ' (PCTALL-GE600HI)', off.p_pcp_ge_6p00in_pct, null, '%'],
      ['Precipitation 25th pctile, wet days (DLY-PRCP-25PCTL)', off.pcp_25pctl_in, null, 'in'],
      ['Precipitation 50th pctile, wet days (DLY-PRCP-50PCTL)', off.pcp_50pctl_in, null, 'in'],
      ['Precipitation 75th pctile, wet days (DLY-PRCP-75PCTL)', off.pcp_75pctl_in, null, 'in']
    ];
    // The comparison block already carries the matched pairs, so look the
    // derived value up by its label rather than re-deriving the pairing here.
    const cmp = off.derived_comparison || [];
    const byLabel = {};
    cmp.forEach(r => { byLabel[r.quantity] = r; });
    const rows = pubRows.map(([label, val, cmpLabel, unit]) => {
      const match = cmpLabel ? byLabel[cmpLabel] : null;
      return [
        el('span', { text: label }),
        val === null || val === undefined ? DASH
          : (unit === 'in' ? Number(val).toFixed(2) : Number(val).toFixed(1)) + ' ' + unit,
        match ? (unit === 'in' ? Number(match.derived).toFixed(2)
                               : Number(match.derived).toFixed(1)) + ' ' + unit : DASH,
        match ? el('span', { class: Math.abs(match.difference) > 3 ? 'pill pill-warn' : 'fine',
          text: (match.difference > 0 ? '+' : '') + match.difference.toFixed(1) + ' ' + unit }) : DASH
      ];
    });
    body.append(table(
      [{ label: 'Published quantity (NOAA column)' }, { label: 'NOAA published', num: true },
       { label: 'This project', num: true }, { label: 'Difference', num: true }],
      rows));
    // NCEI cannot compute a wet-day percentile for a calendar date with too few
    // wet days in the 30-year record, and writes its missing-value sentinel
    // (-9999) in that cell.  The parser drops those, so the row is blank rather
    // than a number; say why, so a reader does not read the blank as an omission
    // on this project's side.  It is real information: this date is normally dry.
    const pctlBlank = ['pcp_25pctl_in', 'pcp_50pctl_in', 'pcp_75pctl_in']
      .filter(k => off[k] === null || off[k] === undefined).length;
    if (pctlBlank) {
      body.append(el('p', { class: 'fine', text:
        pctlBlank === 3
          ? 'NOAA publishes no wet-day precipitation percentile for this date: in the '
            + '1991-2020 record it does not rain often enough here to compute one. The '
            + 'three percentile rows are therefore blank. That is a property of the '
            + 'date, not missing data on this page.'
          : 'Some wet-day precipitation percentiles are blank because NOAA does not '
            + 'publish them for this date.' }));
    }
    // The count is read from the data, never typed: the previous wording said
    // "13 element columns ... including 14 traced" because the hard-coded 13 did
    // not know about the year-count column the column map also carries.
    const pubCols = off.published_columns || {};
    const nCols = Object.keys(pubCols).length;
    body.append(el('p', { class: 'fine' }, [
      'Source: ',
      link(off.source_url, 'NCEI 1991-2020 daily normals for ' + (off.station_id || 'this station')),
      document.createTextNode(nCols
        ? ` \u00b7 ${nCols} column(s) of the published file traced to named elements.`
        : '')
    ]));
  }

  if (d.cpc && d.cpc.length) {
    body.append(el('h4', { text: 'Official CPC outlooks covering this day' }));
    body.append(el('p', { class: 'fine', text:
      'Each row is a point-in-polygon sample of the official CPC shapefile at the 94122 ' +
      'coordinate. Probability and category come straight from that polygon\u2019s DBF row; ' +
      'the polygon index and bounding box are in the JSON record so it can be found on the ' +
      'official map.' }));
    body.append(table([{ label: 'Period' }, { label: 'Issued' }, { label: 'Variable' },
      { label: 'Outlook' }, { label: 'Source' }],
      d.cpc.map(r => [
        r.valid_season || (r.start_date ? `${r.start_date} \u2192 ${r.end_date}` : DASH),
        r.issued || DASH,
        r.variable === 'temp' ? 'Temperature' : r.variable === 'prcp' ? 'Precipitation' : DASH,
        // Same baseline-aware cell as the two CPC tables above, so a 33%
        // "Above" polygon is labelled identically wherever it appears.
        el('span', {}, [cpcCategoryCell(r),
          document.createTextNode(` (${r.prob}%)` + (r.used_nearest_polygon ? ' \u26a0' : ''))]),
        linkShort(r.url, 40)
      ])));
    body.append(el('p', { class: 'fine', text:
      'These are probabilities for the whole period, not for this day. Where an outlook is ' +
      'available from more than one issuance date, the most recent is shown.' }));
  }

  /* Per-field deep links: the exact official row/file behind each headline
   * number, so a reader can re-derive it without hunting through this
   * project's code.  The claim ledger fails the run if a tier's day lacks
   * the expected deep-link keys. */
  const dl = d.deep_links || {};
  const dlRows = [
    ['High / low', 'temp'], ['Humidity', 'humidity'], ['Chance of rain', 'rain_chance'],
    ['Rain amount', 'rain_amount'], ['Max wind', 'wind'], ['Max gust', 'gust'],
    ['NOAA\u2019s published normals', 'published_normals'],
    ['Human-readable forecast', 'human']
  ].filter(([, k]) => dl[k] && dl[k].url);
  if (dlRows.length) {
    body.append(el('h4', { text: 'Verify each number yourself' }));
    body.append(table([{ label: 'Field' }, { label: 'Official row / file' }, { label: 'How to read it' }],
      dlRows.map(([label, k]) => [
        label,
        link(dl[k].url, dl[k].label || dl[k].url),
        el('span', { class: 'fine', text: dl[k].hint || '' })
      ])));
  }

  body.append(el('h4', { text: 'Sources for this day' }));
  body.append(el('ul', {}, (d.sources || []).map(s =>
    el('li', { class: 'fine' }, [link(s.url, s.label)]))));

  // showModal() is standard in every current browser; the fallback keeps the
  // page usable (and testable headlessly) where it is not implemented.
  const dlg = $('#day-dialog');
  if (dlg && typeof dlg.showModal === 'function') dlg.showModal();
  else if (dlg) dlg.setAttribute('open', '');
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

/** CPC category with the baseline caveat attached where it applies. */
function cpcCategoryCell(r) {
  const label = r.category_label || DASH;
  if (!r.probability_at_climatological_baseline) return document.createTextNode(label);
  const note = r.baseline_note ||
    'category field says ' + label + ' but the probability is the 33.3% baseline';
  return el('span', { title: note }, [
    document.createTextNode(label + ' '),
    el('span', { class: 'badge badge-warn', text: 'at the 33% baseline' })
  ]);
}

/** "mean X · p10–p90 Y–Z per season", or an em dash when the run did not
 *  compute it.  Severity counters are days per season at or above a plain
 *  threshold; no NWS warning category is implied by any of them. */
function noteMissingAgreementVerdict() {
  // Not an error - an older snapshot simply has no verdict - but it must not
  // read as "the methods agree" by omission, so the page says so instead.
  const host = $('#storm-summary');
  if (host) host.append(el('p', { class: 'fine bl-warn',
    text: 'This snapshot does not carry a computed agreement verdict for the two methods.' }));
}

function severityLine(d) {
  if (!d || d.mean === null || d.mean === undefined) return DASH;
  const band = (d.p10 !== undefined && d.p90 !== undefined)
    ? ` \u00b7 p10\u2013p90 ${n(d.p10, 1)}\u2013${n(d.p90, 1)}` : '';
  return `mean ${n(d.mean, 1)} of ${n(d.max, 0)} days in the worst season${band}`;
}

function renderWind(cal, landlord) {
  const days = cal.days || [];
  const dist = cal.season_summary || {};
  const jr = dist.wind_and_rain_days || {}, hj = dist.heavy_wind_and_rain_days || {}, mg = dist.max_gust_mph || {};

  const avg = key => {
    const vals = days.map(d => (d.climo || {})[key]).filter(v => v !== null && v !== undefined);
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };

  const hwr = ((landlord || {}).executive_summary || {}).wind_and_rain_hourly || {};
  const hDays = hwr.days_with_a_simultaneous_hour || {};
  const hHours = hwr.simultaneous_hours_per_season || {};
  const hRows = [];
  if (hwr.available) {
    hRows.push(['Wind+rain days per season (same HOUR, SFO hourly record)',
      `mean ${n(hDays.mean, 1)} \u00b7 median ${n(hDays.median, 1)} \u00b7 max ${n(hDays.max, 0)} over ${n(hwr.n_seasons_used, 0)} seasons`]);
    hRows.push(['Simultaneous wind+rain hours per season',
      `mean ${n(hHours.mean, 1)} \u00b7 median ${n(hHours.median, 1)} \u00b7 max ${n(hHours.max, 0)}`]);
  }
  $('#wind-table').append(el('table', { class: 'kv' }, [
    ['Average daily max wind (SFO)', n(avg('normal_max_sustained_mph'), 1) + ' mph'],
    ['Average daily max gust (SFO)', n(avg('normal_max_gust_mph'), 1) + ' mph'],
    ...hRows,
    ['Wind+rain days per season (same DAY, whole-day pairing)', `mean ${n(jr.mean, 1)} \u00b7 median ${n(jr.median, 1)} \u00b7 max ${n(jr.max, 0)}`],
    ['Heavy wind+rain days per season', `mean ${n(hj.mean, 1)} \u00b7 median ${n(hj.median, 1)} \u00b7 max ${n(hj.max, 0)}`],
    ['Strongest gust of the season', `mean ${n(mg.mean, 0)} mph \u00b7 median ${n(mg.median, 0)} mph \u00b7 max ${n(mg.max, 0)} mph`],
    ['Days per season with sustained wind ≥ 30 kt', severityLine(dist.wind_days_ge_30kt)],
    ['Days per season with a gust ≥ 40 kt', severityLine(dist.gust_days_ge_40kt)],
    ['Days per season with a gust ≥ 50 kt', severityLine(dist.gust_days_ge_50kt)],
    ['Definition: wind+rain day', (cal.definitions || {}).wind_and_rain_day || DASH],
    ['Definition: simultaneous wind+rain hour', ((landlord || {}).executive_summary || {}).wind_and_rain_hourly?.method || DASH],
    ['Definition: heavy wind+rain day', (cal.definitions || {}).heavy_wind_and_rain_day || DASH]
  ].map(([k, v]) => el('tr', {}, [el('th', { text: k }), el('td', { text: v })]))));

  // The most extreme wind day on record in the window, named by the season it
  // fell in, so the count above can be checked against the source file.
  const rg = cal.severity_record || {};
  if (rg.max_gust_mph && rg.max_gust_mph.season) {
    $('#wind-table').append(el('p', { class: 'fine', text:
      `Most extreme gust on record in the window: ${n(rg.max_gust_mph.value, 1)} mph, ` +
      `season ${rg.max_gust_mph.season} (GSOD daily maximum at SFO, 11.9 mi away; an SFO reference value, not a bound for 94122).` }));
  }

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

function renderStorms(s, cal) {
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

  // Severity counters, from the same two NCEI files as every other number on
  // this page.  They count days at or above a plain threshold; they are not a
  // restatement of any NWS warning criterion.
  const dist = cal.season_summary || {};
  const rec = cal.severity_record || {};
  const anySeverity = ['wet_days_ge_050in', 'wet_days_ge_1in', 'wet_days_ge_2in',
    'wet_days_ge_400in', 'severe_wind_and_rain_days'].some(k => dist[k]);
  if (anySeverity) {
    $('#storm-summary').append(el('h4', { text: 'How hard it rains, from the daily record' }));
    const sevRows = [
      ['Days per season with ≥ 0.50 in', severityLine(dist.wet_days_ge_050in)],
      ['Days per season with ≥ 1.00 in', severityLine(dist.wet_days_ge_1in)],
      ['Days per season with ≥ 2.00 in', severityLine(dist.wet_days_ge_2in)],
      ['Days per season with ≥ 4.00 in', severityLine(dist.wet_days_ge_400in)],
      ['Wettest single day in the 30-season window',
        rec.max_daily_prcp_in
          ? `${n(rec.max_daily_prcp_in.value, 2)} in (season ${rec.max_daily_prcp_in.season})` : DASH]
    ];
    if (dist.severe_wind_and_rain_days) {
      sevRows.push(['Days per season that are BOTH ≥ 1.00 in and a gust ≥ 40 kt',
        severityLine(dist.severe_wind_and_rain_days)]);
      const recSevere = rec.most_severe_wind_and_rain_days;
      if (recSevere && recSevere.value !== undefined) {
        sevRows.push(['Most such days in one season',
          `${recSevere.value} in ${recSevere.season}` +
          (rec.most_days_gust_ge_50kt
            ? ` · most ≥ 50 kt gust days: ${rec.most_days_gust_ge_50kt.value} in ${rec.most_days_gust_ge_50kt.season}`
            : '')]);
      }
    }
    sevRows.push(['Thresholds',
      'Plain NCEI thresholds in inches of liquid precipitation and knots of wind, both read from ' +
      'the same station files as everything else here. No NWS warning category is applied - those ' +
      'criteria are written per forecast zone and this project does not restate them.']);
    $('#storm-summary').append(el('table', { class: 'kv' }, sevRows
      .map(([k, v]) => el('tr', {}, [el('th', { text: k }), el('td', { text: v })]))));
  }

  // The two methods, side by side, for every precipitation threshold NOAA
  // publishes a percent-of-years value for.  This is the block a sceptical
  // reader should read first: it shows the project's own count and NOAA's own
  // published expectation agreeing (or not) on the same threshold, at the same
  // station, rather than asking anyone to trust one of them.
  const llSev = (((state.data.landlord || {}).executive_summary) || {}).severity || {};
  const cmp = llSev.threshold_comparison || [];
  if (cmp.length) {
    $('#storm-summary').append(el('h4', { text: 'Heavy-rain days per season — counted vs NOAA-published' }));
    const num = (v, d) => (v === null || v === undefined ? DASH : n(v, d));
    $('#storm-summary').append(table(
      [{ label: 'Threshold' }, { label: 'Method A: counted in the record', num: true },
       { label: 'Method B: NOAA published', num: true }, { label: 'A − B', num: true },
       { label: 'Peak season (method A)', num: true }],
      cmp.map(t => [
        `≥ ${Number(t.threshold_in).toFixed(2)} in`,
        num(t.project_mean_days, 2), num(t.noaa_expected_days, 2),
        (t.difference_days === null || t.difference_days === undefined) ? DASH
          : (t.difference_days > 0 ? '+' : '') + Number(t.difference_days).toFixed(2),
        num(t.project_max_days, 0)
      ])));
    // The verdict on whether the two methods agree is computed in the pipeline
    // from the differences themselves and quoted here verbatim - so the page
    // cannot claim agreement on a day the numbers stop agreeing.
    const agree = llSev.two_method_agreement || {};
    $('#storm-summary').append(el('p', { class: 'fine', text:
      'Both columns answer the same question — how many days a season reach this threshold — from two ' +
      'independent NOAA products: this project counting daily values in the station record, and the sum of ' +
      "NOAA's own published percent-of-years value for each calendar date (DLY-PRCP-PCTALL-GE***HI in the " +
      '1991-2020 daily normals). ' + (agree.statement ? agree.statement + ' ' : '') +
      (agree.source_note ? agree.source_note : '') }));
    if (agree.statement === undefined) {
      noteMissingAgreementVerdict();
    }
  }

  // NCEI writes damage as a number plus a magnitude suffix (K / M / B).  The old
  // version parsed the number but ignored the suffix when *sorting*, so "0.01K"
  // and "1.00M" ranked against each other as 0.01 vs 1.00 - i.e. $10 outranked
  // $1,000,000.  Parse to real dollars, once, and sort on that.
  const damageUsd = v => {
    if (v === null || v === undefined || v === '') return null;
    const str = String(v).trim().toUpperCase();
    const num = parseFloat(str);
    if (!Number.isFinite(num)) return null;
    if (str.endsWith('B')) return num * 1e9;
    if (str.endsWith('M')) return num * 1e6;
    if (str.endsWith('K')) return num * 1e3;
    return num;
  };
  const money = v => {
    const usd = damageUsd(v);
    if (usd === null) return null;
    return usd.toLocaleString(undefined, { style: 'currency', currency: 'USD',
      maximumFractionDigits: usd < 100 ? 2 : 0 });
  };
  // The magnitude column carries a NCEI magnitude code.  EG is "estimated gust"
  // (mph) and MG is "measured gust"; printing the bare code read as a unit.
  const MAGNITUDE = { EG: 'mph (estimated gust)', MG: 'mph (measured gust)',
                      ES: 'mph (estimated sustained)', MS: 'mph (measured sustained)' };
  const magnitude = e => {
    if (e.magnitude === null || e.magnitude === undefined || e.magnitude === '') return DASH;
    const code = String(e.magnitude_type || '').toUpperCase();
    const label = MAGNITUDE[code];
    return label ? `${e.magnitude} ${label}` : `${e.magnitude} ${code}`.trim();
  };
  const events = (s.events || []).slice()
    .sort((a, b) => (damageUsd(b.damage_property) || 0) - (damageUsd(a.damage_property) || 0)
      || String(b.begin_date || '').localeCompare(String(a.begin_date || '')));
  const withDamage = events.filter(e => (damageUsd(e.damage_property) || 0) > 0);
  const top = (withDamage.length ? withDamage : events).slice(0, 20);
  $('#storm-table').append(el('p', { class: 'fine', text:
    withDamage.length
      ? `Showing the ${top.length} record(s) carrying a non-zero property-damage figure, ` +
        `largest first. Every value NCEI holds for this county is a token amount - ` +
        `real flood losses are not itemised in this database, so this table shows how ` +
        `events were *reported*, never a dollar total. See LIMITATIONS.md.`
      : 'No event record for this county carries a non-zero property-damage figure, so ' +
        'the most recent events are shown instead. NCEI damage fields for this county ' +
        'are mostly zero placeholders - they are not a measure of real loss.' }));
  $('#storm-table').append(table(
    [{ label: 'Date' }, { label: 'Type' }, { label: 'Magnitude' }, { label: 'Property damage (as recorded)', num: true }],
    top.map(e => [
      (e.begin_date || DASH).replace('T', ' '),
      e.event_type || DASH,
      magnitude(e),
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

/** Published-vs-derived daily normals: two official-source answers, both shown.
 *
 * This is the section that lets a reader check the site's per-date rain
 * probabilities against NOAA's own published ones without leaving the page.
 */
function renderPublishedNormals(cal) {
  const box = $('#published-normals');
  if (!box) return;
  const meta = cal.daily_normals_official;
  const cmp = cal.daily_normals_comparison;
  const landlord = (state.data.landlord || {}).official_daily_normals;
  if (!meta || !meta.url) {
    box.append(el('p', { class: 'empty', text:
      'NOAA\u2019s published per-date daily normals were not available in this snapshot, ' +
      'so this cross-check cannot be shown. Every other climatology figure on the page is ' +
      'still re-derived from the GHCN-Daily record and is labelled as such.' }));
    return;
  }
  box.append(el('p', { class: 'fine', text:
    'Two independent official answers to the same question, published side by side rather ' +
    'than merged: NOAA\u2019s own smoothed 1991-2020 daily normals for this station, and this ' +
    'project\u2019s raw count over the 30 seasons of GHCN-Daily. Both are traceable, and the ' +
    'difference between them is shown. No reconciliation, no averaging.' }));
  box.append(kvTable([
    ['Published source', link(meta.url, meta.url ? meta.url.replace(/^https?:\/\//, '') : DASH)],
    ['Station', meta.station_id ? `${meta.station_id} \u2014 ${meta.station_name || ''}`.trim() : DASH],
    ['Calendar dates parsed', meta.dates_parsed === undefined ? DASH
      : `${meta.dates_parsed} (a full year file is 366)`],
    ['SHA-256 of the fetched file', meta.sha256 || DASH],
    ['Retrieved', meta.retrieved_utc || DASH]
  ]));

  if (!cmp || !cmp.pairs) {
    box.append(el('p', { class: 'empty', text: 'The comparison block was not produced in this snapshot.' }));
    return;
  }
  const ctx = ['(DLY-PRCP-PCTALL-GE001HI)', '(DLY-PRCP-PCTALL-GE025HI)',
               '(DLY-PRCP-PCTALL-GE100HI)', '(DLY-TMAX-NORMAL)', '(DLY-TMIN-NORMAL)'];
  const rows = Object.entries(cmp.pairs).map(([label, b], i) => {
    if (!b || !b.n) return [label, DASH, DASH, DASH, DASH];
    const unit = b.unit === 'pct_points' ? ' pts' : ' \u00b0F';
    const dp = b.unit === 'pct_points' ? 1 : 1;
    const nAgree = b.within_3_units;
    return [
      el('div', {}, [el('strong', { text: label }), el('br'),
        el('span', { class: 'src-url', text: ctx[i] || '' })]),
      b.n,
      (b.mean_difference > 0 ? '+' : '') + Number(b.mean_difference).toFixed(dp) + unit,
      `${(b.largest_difference_published).toFixed(dp)}${unit} vs ` +
        `${(b.largest_difference_derived).toFixed(dp)}${unit} on ${b.largest_difference_date}`,
      `${nAgree} of ${b.n} within 3` + (b.unit === 'pct_points' ? ' pts' : ' \u00b0F')
    ];
  });
  box.append(table(
    [{ label: 'Quantity (published column)' }, { label: 'Dates compared', num: true },
     { label: 'Mean difference', num: true }, { label: 'Largest difference', num: true },
     { label: 'Agreement', num: true }], rows));

  const flagged = cmp.flagged || [];
  if (flagged.length) {
    box.append(el('p', { class: 'fine', text:
      `${flagged.length} date(s) differ by more than 10 percentage points. Both values are ` +
      'shown for each of them in the day dialog \u2014 neither is treated as the right one. ' +
      'A gap that size is expected on a single date, and is not evidence that either side ' +
      'is wrong: this project counts 30 seasons, so a probability near 40% carries a ' +
      'sampling standard error of about \u00b19 percentage points on its own, before ' +
      'NOAA\u2019s smoothing across dates is considered. What the comparison tests is the ' +
      'average, and the average agrees.' }));
    box.append(table(
      [{ label: 'Date' }, { label: 'Quantity' }, { label: 'NOAA published', num: true },
       { label: 'This project', num: true }, { label: 'Difference', num: true }],
      flagged.slice(0, 12).map(r => [r.date, r.quantity, r.published, r.derived, r.difference])));
  }

  const pe = landlord && landlord.published_expected_days;
  if (pe) {
    box.append(el('h4', { text: 'Expected heavy-rain days per season \u2014 both methods' }));
    const exec = ((state.data.landlord || {}).executive_summary) || {};
    const derived = exec.expected_days || {};
    const sevBlk = exec.severity || {};
    const thrFor = inches => (sevBlk.threshold_comparison || [])
      .find(t => Number(t.threshold_in) === inches) || {};
    // Four of these rows now have a project-side counterpart on exactly the
    // same threshold, taken from the severity counters.  The 0.01 in row is the
    // wet-day count, which the climatology already publishes: it read "not
    // derived" for as long as the two names for the same quantity were not
    // joined up.
    const wetDays = ((state.data.calendar || {}).season_summary || {}).wet_days || {};
    box.append(table(
      [{ label: 'Quantity' }, { label: 'From NOAA\u2019s published probabilities', num: true },
       { label: 'From this project\u2019s own count', num: true }, { label: 'Difference', num: true }],
      [['Days \u2265 0.01 in per season', pe.ge_010in_days, wetDays.mean],
       ['Days \u2265 0.25 in per season', pe.ge_025in_days, derived.ge_025in_days],
       ['Days \u2265 0.50 in per season', pe.ge_050in_days, thrFor(0.5).project_mean_days],
       ['Days \u2265 1.00 in per season', pe.ge_100in_days, derived.ge_100in_days],
       ['Days \u2265 2.00 in per season', pe.ge_200in_days, thrFor(2).project_mean_days],
       ['Days \u2265 4.00 in per season', pe.ge_400in_days, thrFor(4).project_mean_days]]
        .filter(r => r[1] !== null && r[1] !== undefined)
        .map(r => [r[0], r[1], r[2] === null || r[2] === undefined ? 'not derived' : r[2],
          (r[2] === null || r[2] === undefined) ? DASH
            : ((r[1] - r[2] > 0 ? '+' : '') + Number(r[1] - r[2]).toFixed(2))])));
    box.append(el('p', { class: 'fine', text: pe.method || '' }));
  } else {
    box.append(el('p', { class: 'empty', text:
      'The published-probability expected-day counts were not produced in this snapshot.' }));
  }
  if (cmp.note) box.append(el('p', { class: 'fine', text: cmp.note }));
}

function renderQuality(q, run) {
  const items = q.irregularities || [];
  const c = q.counts || {};
  const host = $('#quality-report');

  // How far each NCEI archive behind these numbers actually reaches.  Published
  // because an archive can stop updating quietly: a stale file cannot support a
  // statement about current conditions, and the reader should not have to guess
  // which of these is current.
  const cov = (run || {}).record_coverage;
  if (cov && (cov.archives || []).length) {
    host.append(el('h3', { text: 'How current each source archive is' }));
    host.append(el('p', { class: 'fine', text:
      `Newest row this project fetched from each archive, as of ${cov.as_of || DASH}. ` +
      'Every published statistic is a 1991\u20132020 statistic and does not depend on these ' +
      'dates; they are here so nothing on this page is read as describing conditions today.' }));
    host.append(el('table', { class: 'kv' }, cov.archives.map(a => el('tr', {}, [
      el('th', { text: a.label || a.area }),
      el('td', {}, [
        document.createTextNode(`newest row ${a.last_date || 'not retrieved'}` +
          (a.age_days === null || a.age_days === undefined ? '' : ` (${a.age_days} day(s) before this run)`) + ' '),
        a.url ? link(a.url, 'source file') : null
      ])
    ]))));
    const stale = cov.stale_archives || [];
    if (stale.length) {
      // Name the archives the way the table above names them, not by the raw
      // area key, so the flag points at a row the reader can actually find.
      const labelFor = area => {
        const row = (cov.archives || []).find(a => a.area === area);
        return row ? (row.label || area) : area;
      };
      host.append(el('p', { class: 'fine', id: 'quality-stale-flag', text:
        `Flagged: ${stale.map(labelFor).join('; ')} ` +
        (stale.length > 1 ? 'are' : 'is') + ' more than 180 days behind the run date. ' +
        'That is published rather than hidden \u2014 it limits any claim about *recent* ' +
        'conditions, not the 1991\u20132020 statistics.' }));
    }
  }

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

/* ------------------------------------------------- NWS forecast verification */

function renderNwsVerification() {
  const host = $('#nws-verification-body');
  if (!host) return;
  return fetch('data/forecast_verification.json').then(r => r.ok ? r.json() : null).then(v => {
    if (!v) {
      host.append(el('p', { class: 'empty', text: 'No verification dataset is committed yet (data/forecast_verification.json missing).' }));
      return;
    }
    const n = v.total_scored_pairs || 0;
    host.append(el('p', { class: 'fine', text:
      `Status: ${n} forecast-vs-observation pair(s) scored so far. ` +
      (n === 0
        ? 'The first scored pairs appear once observed days accumulate past the current NWS horizon — every run archives a snapshot, and observations are matched automatically as GHCN-Daily updates.'
        : 'Running error and POP calibration statistics are below.') }));

    if (n === 0) {
      host.append(el('div', { class: 'callout callout-info' }, [
        el('h3', { text: 'Waiting for the first observable day' }),
        el('p', { class: 'fine', text:
          'The current NWS horizon reaches out 8 days; a forecast issued today is not scored ' +
          'until that day has passed and NCEI has published a GHCN-Daily observation for it. ' +
          'Archived snapshots build up nightly; scored pairs populate automatically.' })
      ]));
      return;
    }

    const rows = [];
    const mae = v.overall_high_mae_f;
    const pge = v.pop_ge_50_rain_pct;
    const plt = v.pop_lt_50_rain_pct;
    rows.push(['High-temp MAE (all lead days)', mae == null ? DASH : `${mae} °F`]);
    rows.push(['Rain frequency when POP ≥ 50%', pge == null ? DASH : `${pge}%`]);
    rows.push(['Rain frequency when POP < 50%', plt == null ? DASH : `${plt}%`]);
    host.append(el('table', { class: 'kv' }, rows.map(([k, v]) =>
      el('tr', {}, [el('th', { text: k }), el('td', { text: v })]))));

    const byLead = v.by_lead_days || [];
    if (byLead.length) {
      host.append(el('h4', { text: 'By lead time (days from issuance to target)' }));
      host.append(table(
        [{ label: 'Lead (days)' }, { label: 'n' }, { label: 'High MAE (°F)' }, { label: 'Low MAE (°F)' },
         { label: '% rain when POP≥50' }, { label: '% rain when POP<50' }],
        byLead.map(r => [r.lead_days, r.sample_size ?? 0,
          r.high_mae_f ?? DASH, r.low_mae_f ?? DASH,
          r.pop_ge_50_pct_rain == null ? DASH : r.pop_ge_50_pct_rain + '%',
          r.pop_lt_50_pct_rain == null ? DASH : r.pop_lt_50_pct_rain + '%'])));
    }
  }).catch(err => {
    host.append(el('p', { class: 'fine', text: 'Could not read forecast_verification.json: ' + err.message }));
  });
}

/* ----------------------------------------------------------- CPC back-test */

function renderCpcBacktest() {
  const host = $('#cpc-backtest-body');
  if (!host) return;
  return fetch('data/cpc_backtest.json').then(r => r.ok ? r.json() : null).then(bt => {
    if (!bt) {
      host.append(el('div', { class: 'callout callout-info' }, [
        el('h3', { text: 'Back-test file missing this run' }),
        el('p', { class: 'fine', text:
          'pipeline/cpc_backtest.py writes data/cpc_backtest.json on every scheduled run. ' +
          'Until it has, no hit-rate is published here.' })
      ]));
      return;
    }
    /* Pending-backfill is the honest normal state: the live GIS server keeps
     * only recent months, so historical seasprcp_YYYYMM.zip files usually 404.
     * The file says so itself (status + reason), with links to the official
     * Oct-1995 archive and to CPC's own verifications for manual review. */
    if (bt.status === 'pending-backfill' || !(bt.rows || []).length) {
      host.append(el('div', { class: 'callout callout-info' }, [
        el('h3', { text: 'Pending back-fill -- no hit-rate yet, flagged' }),
        el('p', { class: 'fine', text: bt.reason || 'No historical archive was retrievable this run.' }),
        el('p', { class: 'fine', text:
          'Method, ready and waiting: sample each historical August seasprcp issuance at the ' +
          '94122 centroid with the same point-in-polygon code as the live outlooks, and score ' +
          'the sampled Above/Below/EC category against the observed GHCN-Daily OND/NDJ/DJF/JFM ' +
          'total. EC outlooks are unscored, never counted as hits or misses.' }),
        el('p', { class: 'fine', text:
          'The IRI Data Library was considered as an archive source and rejected: it is a ' +
          'Columbia academic mirror, not an official NOAA operational product, it serves HTTP ' +
          '(this project requires HTTPS), and its CPC tree holds monitoring datasets, not the ' +
          'outlook polygons. The official CPC archive is the only accepted source.' })
      ]));
      const links = [];
      if (bt.archive_index) links.push(link(bt.archive_index, 'official CPC long-lead archive (Oct 1995 on)'));
      if (bt.verifications) links.push(link(bt.verifications, 'CPC\u2019s own seasonal verifications (CONUS-wide)'));
      if (links.length) host.append(el('p', { class: 'fine' }, ['For manual review: ',
        ...links.flatMap((l, i) => i ? [' \u00b7 ', l] : [l])]));
      const att = bt.issuances_attempted || [];
      if (att.length) {
        host.append(el('p', { class: 'fine', text:
          `${att.length} historical issuance(s) attempted this run, ` +
          `${bt.n_archives_retrieved || 0} retrieved.` }));
        host.append(table(
          [{ label: 'Issuance' }, { label: 'Result' }],
          att.slice(-12).map(a => [a.issuance_ym || DASH,
            a.ok ? 'retrieved' : `not retained (${a.status || a.error || 'fetch failed'})`])));
      }
      return;
    }
    const s = bt.summary || {};
    host.append(el('p', { class: 'fine', text: bt.note || '' }));
    host.append(el('p', { class: 'fine' }, [
      el('strong', { text: 'Hit-rate over scored (non-EC) rows: ' }),
      document.createTextNode(s.hit_rate_pct == null ? DASH : `${s.hit_rate_pct}% ` +
        `(${s.hits} of ${s.n_rows_scored} rows; ${s.n_rows_unscored_ec} EC row(s) unscored)`)
    ]));
    if (s.by_category && Object.keys(s.by_category).length) {
      host.append(table(
        [{ label: 'CPC category' }, { label: 'Scored', num: true }, { label: 'Hits', num: true },
         { label: 'Hit-rate', num: true }],
        Object.entries(s.by_category).map(([cat, b]) => [cat, b.scored, b.hits,
          b.hit_rate_pct == null ? DASH : b.hit_rate_pct + '%'])));
    }
    host.append(table(
      [{ label: 'Season' }, { label: 'CPC category' }, { label: 'CPC probability' },
       { label: 'Observed total' }, { label: 'Observed tercile' }, { label: 'Hit?' }],
      (bt.rows || []).map(r => [r.season || DASH, r.category_label || r.category || DASH,
        r.probability == null ? DASH : r.probability + '%',
        r.observed_total_in == null ? DASH : Number(r.observed_total_in).toFixed(2) + ' in',
        r.observed_tercile || DASH,
        el('span', { class: 'pill pill-' + (r.hit ? 'ok' : r.hit === false ? 'fail' : 'warn'),
          text: r.hit == null ? 'unscored' : (r.hit ? 'hit' : 'miss') })])));
    host.append(el('p', { class: 'fine', text: bt.method || '' }));
  }).catch(err => {
    host.append(el('p', { class: 'fine', text: 'Could not read cpc_backtest.json: ' + err.message }));
  });
}

function renderDigest(digest) {
  const host = $('#digest-body');
  if (!host) return;
  if (!digest) {
    host.append(el('p', { class: 'empty', text:
      'No digest was produced in this run (pipeline/build_digest.py writes data/digest.json + data/alerts.xml).' }));
    return;
  }
  const c = digest.counts || {};
  host.append(el('p', { class: 'fine', text:
    `Built ${digest.generated_utc || DASH} \u00b7 ${c.nws_alerts || 0} active alert(s) ` +
    `\u00b7 ${c.high_pop_days || 0} NWS-forecast day(s) at or above the ${digest.pop_threshold_pct || 50}% rain-chance threshold.` }));
  const items = [...(digest.nws_alerts || []), ...(digest.high_pop_days || [])];
  if (!items.length) {
    host.append(el('div', { class: 'callout callout-ok' }, [
      el('p', { text: 'Quiet: no active NWS alerts for CAZ006 and no NWS-forecast day reaches the rain-chance threshold.' })
    ]));
  } else {
    host.append(table(
      [{ label: 'Type' }, { label: 'Entry' }, { label: 'Source' }],
      items.map(it => [
        it.kind === 'nws-alert' ? 'NWS alert' : 'High rain chance',
        el('span', {}, [
          el('strong', { text: it.title || DASH }),
          it.description ? el('div', { class: 'fine', text: it.description }) : null
        ].filter(Boolean)),
        it.link ? linkShort(it.link, 40) : DASH
      ])));
  }
  host.append(el('p', { class: 'fine', text: digest.privacy || '' }));
}

/* ------------------------------------------------------------ verification */

function renderVerify(verify, prov) {
  const box = $('#verify-body');
  if (!box) return;
  if (!verify) {
    box.append(el('p', { class: 'empty', text:
      'No verification ledger was produced in this run (pipeline/verify_claims.py writes ' +
      'data/verify.json).' }));
    return;
  }
  const s = verify.summary || {};
  const banner = el('div', { class: 'callout ' + (s.failed ? 'callout-error' : 'callout-ok') }, [
    el('h3', { text: `${s.passed || 0} of ${s.total || 0} automated checks passed` }),
    el('p', { class: 'fine', text:
      `${s.warnings || 0} warning(s), ${s.failed || 0} failure(s). A failure stops the nightly ` +
      'build, so a number that cannot be re-derived from its source never reaches this page.' }),
    (s.failed ? el('p', { class: 'fine', text: 'Failed: ' + (s.failed_checks || []).join(', ') }) : null),
    ((s.warning_checks || []).length
      ? el('p', { class: 'fine', text: 'Warnings: ' + s.warning_checks.join(', ') }) : null)
  ].filter(Boolean));
  box.append(banner);
  (verify.how_to_read || []).forEach(t => box.append(el('p', { class: 'fine', text: t })));

  box.append(el('h4', { text: 'Automated checks' }));
  box.append(table(
    [{ label: 'Check' }, { label: 'Status' }, { label: 'What it proves' }, { label: 'Detail' }],
    (verify.checks || []).map(c => [
      el('code', { text: c.id }),
      el('span', { class: 'pill pill-' + (c.status === 'pass' ? 'ok' : (c.status === 'warn' ? 'warn' : 'fail')),
        text: c.status }),
      el('span', { class: 'fine', text: c.title }),
      el('span', { class: 'fine', text: c.detail || '' })
    ])));

  box.append(el('h4', { text: 'Claim ledger — every headline number and its source' }));
  box.append(table(
    [{ label: 'Claim' }, { label: 'Value' }, { label: 'Official source' },
     { label: 'Retrieved / SHA-256' }, { label: 'Method' }],
    (verify.claims || []).map(c => {
      const src = c.source || {};
      // A claim value can be a scalar or a record.  Two rules apply either way:
      // a machine ENSO token is rendered as its label, and a unit is only
      // appended to a scalar - appending "deg C" after a record of mixed fields
      // ("season: JJA 2026 · oni_c: 1.8 · phase: … · strength: strong deg C")
      // reads as though the last field carried the unit, which it does not.
      const isRecord = typeof c.value === 'object' && c.value !== null;
      const fmtVal = (k, val) => {
        if (/_phase$|^phase$/.test(k) && typeof val === 'string') return phaseLabel(val);
        if (/^strength$/.test(k) && typeof val === 'string') {
          return { very_strong: 'very strong', strong: 'strong', moderate: 'moderate',
                   weak: 'weak', neutral: 'neutral' }[val] || String(val).replace(/_/g, ' ');
        }
        return val;
      };
      const v = isRecord
        ? Object.entries(c.value).map(([k, val]) => `${k}: ${fmtVal(k, val)}`).join(' \u00b7 ')
        : String(fmtVal('', c.value));
      return [
        el('div', {}, [el('strong', { text: c.id }), el('br'),
          el('span', { class: 'fine', text: c.statement || '' })]),
        el('span', {}, [document.createTextNode(v),
          (!isRecord && c.unit) ? document.createTextNode(' ' + c.unit) : null].filter(Boolean)),
        el('div', {}, [link(src.url, src.label || src.url),
          src.host ? el('div', { class: 'fine', text: src.host }) : null].filter(Boolean)),
        el('div', { class: 'fine' }, [
          document.createTextNode((src.retrieved_utc || DASH) + ' \u00b7 HTTP ' + (src.http_status || DASH) +
            ' \u00b7 ' + (src.bytes ? Number(src.bytes).toLocaleString() + ' bytes' : DASH)),
          src.sha256 ? el('div', { class: 'src-url', text: 'sha256 ' + src.sha256 }) : null
        ].filter(Boolean)),
        el('span', { class: 'fine', text: c.method || DASH })
      ];
    })));

  const irr = (verify.open_irregularities || []);
  if (irr.length) {
    box.append(el('h4', { text: 'Irregularities still open (from the fetch run)' }));
    box.append(table([{ label: 'Severity' }, { label: 'Area' }, { label: 'Message' }],
      irr.map(i => [el('span', { class: 'pill pill-' +
        (i.severity === 'error' ? 'fail' : (i.severity === 'warning' ? 'warn' : 'ok')), text: i.severity }),
        i.area, el('span', { class: 'fine', text: i.message })])));
  }
  box.append(el('p', { class: 'fine' }, [
    'Raw ledgers: ', link('data/verify.json', 'data/verify.json'), ' \u00b7 ',
    link('data/verify_report.txt', 'data/verify_report.txt'), ' \u00b7 ',
    link('data/provenance.json', `data/provenance.json (${(prov.entries || []).length} recorded fetches)`),
    document.createTextNode(' \u00b7 generated ' + (verify.generated_utc || DASH))
  ]));
}

/* ------------------------------------------------------------------- export */

const CSV_FIELDS = [
  ['date', 'Date'], ['weekday', 'Weekday'], ['tier', 'Tier'],
  ['high_f', 'High_F'], ['low_f', 'Low_F'], ['humidity_pct', 'Humidity_pct'],
  ['rain_chance_pct', 'Rain_chance_pct'], ['rain_amount_in', 'Rain_amount_in'],
  ['wind_max_mph', 'Wind_max_mph'], ['gust_max_mph', 'Gust_max_mph'],
  ['hours_covered', 'Hours_from_NWS_grid']
];

function csvCell(v) {
  if (v === null || v === undefined) return '';
  const t = String(v);
  return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
}

function exportCalendarCSV() {
  const cal = state.data.calendar;
  if (!cal || !cal.days) return;
  const lines = [];
  lines.push('# SFWeather - San Francisco 94122 rainy-season scoreboard');
  lines.push('# Generated ' + cal.generated_utc + ' from official NOAA/NWS/NCEI/CPC sources');
  lines.push('# tier=nws means the row is the official NWS forecast; ' +
    'tier=climatology means it is the 1991-2020 observed record for that date, NOT a forecast');
  lines.push('# humidity on climatology rows is derived from NCEI hourly temperature and ' +
    'dew-point normals (Magnus formula); blank means not available');
  lines.push(CSV_FIELDS.map(f => f[1]).join(','));
  cal.days.forEach(d => lines.push(CSV_FIELDS.map(f => csvCell(d[f[0]])).join(',')));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: 'sfweather-94122-oct2026-jan2027.csv' });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function exportCurrentCSV() {
  const cal = state.data.calendar || {};
  const cf = cal.current_forecast || {};
  const days = cf.days || [];
  if (!days.length) return;
  const fields = [['date', 'Date'], ['weekday', 'Weekday'], ['high_f', 'High_F'], ['low_f', 'Low_F'],
    ['humidity_pct', 'Humidity_pct'], ['rain_chance_pct', 'Rain_chance_pct'],
    ['rain_amount_in', 'Rain_amount_in'], ['wind_max_mph', 'Wind_max_mph'],
    ['gust_max_mph', 'Gust_max_mph']];
  const lines = ['# SFWeather - current official NWS forecast for 94122 (real forecast, not climatology)',
    '# Issued ' + (cf.forecast_updated || '') + '; horizon ' + cf.first_day + ' to ' + cf.last_day,
    fields.map(f => f[1]).join(',')];
  days.forEach(d => lines.push(fields.map(f => csvCell(d[f[0]])).join(',')));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: 'sfweather-94122-current-nws-forecast.csv' });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function wireExports() {
  const csv = $('#export-csv');
  if (csv) csv.addEventListener('click', exportCalendarCSV);
  const cur = $('#export-current');
  if (cur) cur.addEventListener('click', exportCurrentCSV);
  const pr = $('#print-page');
  if (pr) pr.addEventListener('click', () => window.print());
}

/* ------------------------------------------------------------------ boot */

function notYetBuilt(title, file, script, extra) {
  return el('div', { class: 'callout callout-info' }, [
    el('h3', { text: 'Not yet built \u2014 ' + title }),
    el('p', { class: 'fine', text:
      'This run did not publish ' + file + ', so this section is empty. It is not ' +
      'showing zero: it is showing that the dataset is absent. ' + script +
      ' produces it, and the nightly workflow runs that script.' }),
    extra ? el('p', { class: 'fine', text: extra }) : null
  ]);
}

/** A pill that says whether something is an official product or model output. */
function officialPill(official) {
  return el('span', {
    class: 'pill ' + (official ? 'pill-ok' : 'pill-fail'),
    text: official ? 'OFFICIAL' : 'NOT OFFICIAL'
  });
}

/** A pill for whether a cited link stands on a recorded fetch. */
function provenancePill(state) {
  if (state === true) return el('span', { class: 'pill pill-ok', text: 'fetch recorded' });
  if (state === false) return el('span', { class: 'pill pill-warn', text: 'no fetch recorded' });
  return el('span', { class: 'pill', text: 'local copy' });
}

/* ------------------------------------- model guidance: a separate, warned tier */

/** Render the model-guidance tier.
 *
 * Two rules are built into this renderer rather than left to the reader:
 * the warning is the first thing appended, before any content, and it is
 * repeated on every item; and nothing here is allowed to touch the scoreboard -
 * the data file states that and pipeline/verify_claims.py checks it
 * (model-guidance-isolation).
 */
function renderModelGuidance() {
  const host = $('#model-guidance-body');
  if (!host) return Promise.resolve();
  return fetch('data/model_guidance.json').then(r => r.ok ? r.json() : null).then(mg => {
    if (!mg) {
      host.append(notYetBuilt('model guidance', 'data/model_guidance.json',
        'pipeline/model_guidance.py',
        'The NMME probability maps and their definitions live on ' +
        'www.cpc.ncep.noaa.gov/products/NMME/ and are archived locally when the ' +
        'script runs.'));
      return;
    }
    host.append(el('div', { class: 'callout callout-warn mg-warning' }, [
      el('h3', { text: 'MODEL GUIDANCE \u2014 NOT AN OFFICIAL FORECAST' }),
      el('p', { class: 'fine', text: mg.warning || '' }),
      el('p', { class: 'fine', text: mg.isolation_rule || '' })
    ]));

    const c = mg.counts || {};
    host.append(el('p', { class: 'fine', text:
      'Retrieved ' + (mg.generated_utc || DASH) + ' \u00b7 ' +
      (c.pages_retrieved || 0) + '/' + (c.pages_requested || 0) + ' pages \u00b7 ' +
      (c.images_archived || 0) + ' map image(s) archived locally \u00b7 ' +
      (c.verbatim_sentences || 0) + ' definition sentence(s) quoted verbatim.' }));

    if (mg.coverage_verbatim) {
      host.append(el('p', {}, [
        el('strong', { text: 'Period NOAA states these maps cover: ' }),
        el('span', { class: 'verbatim', text: '\u201c' + mg.coverage_verbatim + '\u201d' }),
        el('span', { class: 'fine', text: ' \u2014 quoted from NOAA\u2019s own index page. ' +
          'No month range in this section is derived by this project from a filename.' })
      ]));
    }

    const descr = (mg.pages || {}).description || {};
    const sentences = descr.verbatim_sentences || [];
    if (sentences.length) {
      host.append(el('h3', { text: 'What the maps mean \u2014 NOAA\u2019s own words' }));
      host.append(el('p', { class: 'fine', text:
        'Copied verbatim from ' }));
      const list = el('ul', { class: 'verbatim-list' }, sentences.map(t =>
        el('li', {}, [el('span', { class: 'verbatim', text: '\u201c' + t + '\u201d' })])));
      host.append(list);
      host.append(el('p', { class: 'fine' }, [
        document.createTextNode('Source: '),
        link(descr.url, 'NMME probability forecast description'),
        document.createTextNode(' \u00b7 retrieved ' + (descr.retrieved_utc || DASH) +
          ' \u00b7 ' + (descr.bytes || 0) + ' bytes \u00b7 SHA-256 ' +
          String(descr.sha256 || DASH).slice(0, 16) + '\u2026 \u00b7 every sentence above is ' +
          're-checked against the fetched text by the verification ledger.')
      ]));
    }

    const imgs = mg.images || [];
    if (imgs.length) {
      host.append(el('h3', { text: 'Archived NMME probability maps' }));
      host.append(el('p', { class: 'fine', text:
        'Local copies of NOAA\u2019s own images, so the picture cannot change under the ' +
        'reader. Nothing is read out of them: no probability is transcribed, estimated ' +
        'or republished here. Each image is labelled with the variable NOAA names.' }));
      const grid = el('div', { class: 'mg-grid' });
      imgs.forEach(im => {
        grid.append(el('figure', { class: 'mg-figure' }, [
          im.local_path ? el('img', { src: im.local_path, loading: 'lazy',
            alt: 'NMME ' + (im.variable || '') + ' probability map, season ' +
                 (im.season_index == null ? DASH : im.season_index) }) : null,
          el('figcaption', { class: 'fine' }, [
            el('strong', { text: (im.variable || 'Variable not stated') +
              ' \u00b7 season ' + (im.season_index == null ? DASH : im.season_index) }),
            el('div', { text: im.season_mapping_note || '' }),
            el('div', { class: 'mg-warn', text: im.warning || '' }),
            el('div', {}, [link(im.url, 'NOAA page for this image'),
              document.createTextNode(' \u00b7 ' + (im.bytes || 0) + ' bytes \u00b7 SHA-256 ' +
                String(im.sha256 || DASH).slice(0, 16) + '\u2026')]),
            im.local_path ? el('div', { class: 'src-url', text: 'local copy: ' + im.local_path }) : null
          ])
        ]));
      });
      host.append(grid);
    }

    const pageRows = Object.values(mg.pages || {}).map(pg => [
      pg.label || pg.key || DASH,
      officialPill(true),
      pg.ok ? 'HTTP ' + pg.http_status : 'not retrieved',
      pg.ok ? (pg.bytes || 0).toLocaleString() + ' bytes' : (pg.error || DASH),
      pg.url ? linkShort(pg.url) : DASH,
      pg.why || ''
    ]);
    host.append(el('h3', { text: 'Pages retrieved' }));
    host.append(table([{ label: 'NOAA page' }, { label: 'Tier' }, { label: 'Status' },
      { label: 'Size / error' }, { label: 'URL' }, { label: 'Why it is here' }], pageRows));

    const probes = mg.probes || [];
    if (probes.length) {
      host.append(el('h3', { text: 'Raw model output: located, never decoded' }));
      host.append(table([{ label: 'Location' }, { label: 'Status' }, { label: 'Decoded?' },
        { label: 'URL' }, { label: 'Note' }], probes.map(pr => [
        pr.label || pr.key || DASH,
        pr.ok ? 'HTTP ' + pr.http_status : ('not reachable (' + (pr.error || pr.http_status || '?') + ')'),
        pr.decoded === false ? 'no \u2014 nothing read out of it' : String(pr.decoded),
        pr.url ? linkShort(pr.url) : (pr.skipped || DASH),
        pr.note || pr.decoding_note || ''
      ])));
      host.append(el('p', { class: 'fine', text:
        'A location that did not answer is reported as not reachable and is not published ' +
        'as a working link.' }));
    }

    const dont = mg.what_this_tier_does_not_do || [];
    if (dont.length) {
      host.append(el('h3', { text: 'What this tier deliberately does not do' }));
      host.append(el('ul', { class: 'limits' }, dont.map(t => el('li', { text: t }))));
    }
  }).catch(err => {
    host.append(el('p', { class: 'fine', text: 'Could not read model_guidance.json: ' + err.message }));
  });
}

/* ------------------------------------------------ the official product feed */

const FEED_PAGE_SIZE = 60;
const feedState = { filter: '', kind: 'all', shown: FEED_PAGE_SIZE };

function feedKindLabel(k) {
  const m = {
    'nws-forecast': 'NWS forecast issued', 'nws-period': 'NWS forecast period',
    'nws-hourly': 'NWS hourly forecast', 'nws-alerts': 'NWS alerts', 'nws-alert': 'NWS alert',
    'afd': 'NWS discussion', 'afd-quote': 'NWS discussion quote',
    'cpc-outlook': 'CPC outlook', 'cpc-shapefile': 'CPC shapefile', 'cpc-map': 'CPC map',
    'cpc-discussion': 'CPC discussion', 'forecast-snapshot': 'archived snapshot',
    'ncei-archive': 'NCEI archive probe', 'official-fetch': 'recorded fetch',
    'model-guidance': 'MODEL GUIDANCE', 'model-guidance-image': 'MODEL GUIDANCE image'
  };
  return m[k] || k;
}

function renderFeedRows(feed) {
  const host = $('#feed-rows');
  if (!host) return;
  host.textContent = '';
  const all = (feed.entries || []).concat(feed.undated_entries || []);
  const rows = all.filter(e => {
    if (feedState.kind !== 'all' && e.kind !== feedState.kind) return false;
    if (!feedState.filter) return true;
    const hay = [e.title, e.detail, e.kind, e.url, e.date_utc].join(' ').toLowerCase();
    return hay.indexOf(feedState.filter.toLowerCase()) >= 0;
  });
  const shown = rows.slice(0, feedState.shown);
  host.append(table([
    { label: 'Published / retrieved (UTC)' }, { label: 'What it is' }, { label: 'Item' },
    { label: 'Tier' }, { label: 'Traceable to a recorded fetch?' }, { label: 'Link' }
  ], shown.map(e => [
    e.timestamp_utc ? e.timestamp_utc.replace('T', ' ').replace('Z', '')
      : (e.date_utc ? e.date_utc + ' (date only, no time published)' : 'undated by the publisher'),
    feedKindLabel(e.kind),
    el('span', {}, [el('strong', { text: e.title || DASH }),
      e.detail ? el('div', { class: 'fine', text: e.detail }) : null,
      e.provenance_note ? el('div', { class: 'fine src-url', text: e.provenance_note }) : null,
      e.source_file ? el('div', { class: 'fine src-url', text: 'from ' + e.source_file }) : null]),
    officialPill(e.official !== false),
    provenancePill(e.provenance_verified),
    e.url ? linkShort(e.url, 48) : DASH
  ]), { empty: 'No feed entries match that filter.' }));
  const ctl = $('#feed-more');
  if (ctl) {
    ctl.textContent = '';
    ctl.append(el('span', { class: 'fine', text: 'Showing ' + shown.length + ' of ' +
      rows.length + ' matching entries (' + all.length + ' in the feed).' }));
    if (rows.length > shown.length) {
      ctl.append(el('button', { class: 'btn btn-sm', type: 'button', onclick: () => {
        feedState.shown += FEED_PAGE_SIZE;
        renderFeedRows(state.data.feed);
      }, text: 'Show 60 more' }));
    }
  }
}

function renderFeed() {
  const host = $('#feed-body');
  if (!host) return Promise.resolve();
  return fetch('data/feed.json').then(r => r.ok ? r.json() : null).then(feed => {
    if (!feed) {
      host.append(notYetBuilt('the official-product feed', 'data/feed.json',
        'pipeline/build_feed.py'));
      return;
    }
    state.data.feed = feed;
    const c = feed.counts || {};
    host.append(el('p', { class: 'fine', text: feed.warning || '' }));
    const dateOnly = (feed.entries || []).filter(e => e.date_utc && !e.timestamp_utc).length;
    const undated = (feed.undated_entries || []).length;
    host.append(el('p', { class: 'fine', text:
      'Built ' + (feed.generated_utc || DASH) + ' \u00b7 ' + (c.entries || 0) + ' entries, ' +
      'newest first \u00b7 ' + (c.official || 0) + ' official, ' + (c.not_official || 0) +
      ' model-guidance \u00b7 ' + (c.provenance_verified || 0) +
      ' trace to a recorded fetch, ' + (c.provenance_unverified || 0) +
      ' are labelled as pointers only \u00b7 window ' + (feed.earliest_utc || DASH) +
      ' \u2192 ' + (feed.latest_utc || DASH) + '.' }));
    /* Dates the publisher did not give are reported in the header, not buried in
     * a row that may be below the fold: a date-only entry means NOAA printed a
     * date with no clock time, and an undated entry means it printed neither. */
    if (dateOnly || undated) {
      host.append(el('p', { class: 'fine', text:
        dateOnly + ' entry/entries carry a date but no time (the publisher printed a date ' +
        'only, so no clock time is invented here), and ' + undated +
        ' are undated by the publisher and listed at the end.' }));
    }
    if ((feed.sources_missing || []).length) {
      host.append(el('p', { class: 'fine', text: 'Datasets not present when this feed was ' +
        'built (so it covers fewer sources than a complete run): ' +
        feed.sources_missing.join(', ') + '.' }));
    }
    const kinds = Object.keys(c.kinds || {}).sort();
    const controls = el('div', { class: 'filter-bar' }, [
      el('input', { type: 'search', id: 'feed-filter', placeholder: 'Filter the feed\u2026',
        'aria-label': 'Filter the feed', oninput: ev => {
          feedState.filter = ev.target.value; feedState.shown = FEED_PAGE_SIZE;
          renderFeedRows(feed);
        } }),
      el('select', { id: 'feed-kind', 'aria-label': 'Filter by product type',
        onchange: ev => {
          feedState.kind = ev.target.value; feedState.shown = FEED_PAGE_SIZE;
          renderFeedRows(feed);
        } }, [el('option', { value: 'all', text: 'all product types' })].concat(
          kinds.map(k => el('option', { value: k, text: feedKindLabel(k) + ' (' + c.kinds[k] + ')' }))))
    ]);
    host.append(controls);
    host.append(el('div', { id: 'feed-rows' }));
    host.append(el('div', { id: 'feed-more', class: 'feed-more' }));
    renderFeedRows(feed);
  }).catch(err => {
    host.append(el('p', { class: 'fine', text: 'Could not read feed.json: ' + err.message }));
  });
}

/* ------------------------------------------ why the wind archive stops where it does */

async function boot() {
  if (state.booted) return;
  state.booted = true;
  try {
    const [run, calendar, nws, prov, quality, storms, landlord, verify, digest] = await Promise.all([
      loadJSON('run'), loadJSON('calendar'), loadJSON('nws'),
      loadJSON('provenance'), loadJSON('quality'),
      loadJSON('storms').catch(() => null),
      loadJSON('landlord').catch(() => null),
      loadJSON('verify').catch(() => null),
      loadJSON('digest').catch(() => null)
    ]);
    Object.assign(state.data, { run, calendar, nws, prov, quality, storms, landlord, verify, digest });

    const idx = MONTHS.findIndex(m => (calendar.days || []).some(d => d.date.startsWith(m.key) && d.tier === 'nws'));
    state.month = idx >= 0 ? MONTHS[idx].key : MONTHS[0].key;

    renderDataStatus(calendar, quality, prov, verify);
    if (landlord) renderLandlord(landlord, calendar);
    renderReality(calendar);
    renderLocation(run);
    renderSeason(calendar);
    renderNow(nws, calendar);
    renderAfdLanguage(calendar);
    renderDigest(digest);
    renderCalendar(calendar);
    renderDuration(calendar);
    renderWind(calendar, landlord);
    renderStorms(storms, calendar);
    renderSources(prov);
    renderNwsVerification();
    renderCpcBacktest();
    renderModelGuidance();
    renderFeed();
    renderVerify(verify, prov);
    renderPublishedNormals(calendar);
    renderQuality(quality, run);
    renderCaveats(calendar);
    wireExports();

    $('#footer-meta').textContent =
      `Data fetched ${calendar.generated_utc || DASH} \u00b7 ` +
      `${(prov.entries || []).length} verified fetches \u00b7 ` +
      `normals period ${(calendar.normals_period || []).join('\u2013')} \u00b7 ` +
      `rebuilt nightly from official sources. ` +
      (landlord ? `Landlord dashboard ${landlord.generated_utc || ''}.` : '');

    const loading = $('#loading');
    if (loading) loading.remove();
    $('#content').hidden = false;
  } catch (err) {
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
