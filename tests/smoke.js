/* Headless smoke test for the SFWeather site.
 *
 * Loads index.html and assets/js/app.js in jsdom, serves the repository's own
 * data/*.json through a fetch shim, drives the interactive parts (day dialog,
 * CSV export) and fails if anything breaks.
 *
 * It exists because it caught two real bugs on the day it was written:
 * a DOM node rendered as "[object HTMLSpanElement]" in the day dialog, and a
 * `showModal` call with no fallback.  Both would have been live-page defects.
 *
 * Run:  npm install && npm test
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const repo = process.argv[2] || path.join(__dirname, '..');
const html = fs.readFileSync(path.join(repo, 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(repo, 'assets/js/app.js'), 'utf8');

const problems = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => problems.push('jsdomError: ' + (e.message || e)));
vc.on('error', (...a) => problems.push('console.error: ' + a.join(' ')));

const dom = new JSDOM(html, {
  runScripts: 'outside-only',
  virtualConsole: vc,
  url: 'https://buffedlizard55-lab.github.io/SFWeather/',
  pretendToBeVisual: true
});
const { window } = dom;

window.fetch = async (url) => {
  const rel = String(url).replace(/^https?:\/\/[^/]+\//, '').replace(/^\.\//, '');
  const file = path.join(repo, rel);
  if (!fs.existsSync(file)) return { ok: false, status: 404, json: async () => ({}) };
  const body = fs.readFileSync(file, 'utf8');
  return { ok: true, status: 200, json: async () => JSON.parse(body), text: async () => body };
};
window.URL.createObjectURL = () => 'blob:test';
window.URL.revokeObjectURL = () => {};
window.print = () => {};
window.alert = () => {};

try {
  window.eval(appJs);
} catch (e) {
  problems.push('eval error: ' + e.message);
}

const REQUIRED_SECTIONS = [
  '#data-status', '#landlord-stats', '#landlord-cost-drivers', '#landlord-monthly',
  '#landlord-duration', '#landlord-windrain',
  '#landlord-bottom-line', '#landlord-official',
  '#landlord-cpc', '#landlord-actions', '#tier-legend', '#tbl-location', '#tbl-stations',
  '#enso-body', '#cpc-season-table', '#monthly-table', '#enso-strat', '#discussions',
  '#now-current', '#nws-forecast', '#nws-obs', '#nws-alerts', '#calendar-grid',
  '#streak-table', '#streak-chart', '#wind-table', '#gust-table', '#storm-summary',
  '#provenance', '#verify-body', '#quality-report', '#caveats'
];

setTimeout(() => {
  const doc = window.document;
  const text = sel => {
    const n = doc.querySelector(sel);
    return n ? n.textContent.replace(/\s+/g, ' ').trim() : '';
  };

  if (doc.querySelector('#loading')) problems.push('loading spinner was never removed');
  const content = doc.querySelector('#content');
  if (!content || content.hidden) problems.push('#content is still hidden');

  REQUIRED_SECTIONS.forEach(sel => {
    if (text(sel).length < 3) problems.push('section rendered empty: ' + sel);
  });

  // The first real day cell must carry the requested fields.
  const days = Array.from(doc.querySelectorAll('.day:not(.blank)'));
  if (!days.length) problems.push('no calendar day cells rendered');
  else {
    const t = days[0].textContent;
    ['wind', 'gust', 'RH'].forEach(k => {
      if (!t.includes(k)) problems.push('day cell is missing "' + k + '": ' + t);
    });
    // A climatology day must label its amount "mean", never "rain": the number
    // is a 30-year average, and reading it as a forecast for that date would be
    // exactly the confusion this site exists to prevent.
    const isClimo = days[0].classList.contains('day') &&
      !days[0].className.includes('is-forecast');
    if (isClimo) {
      if (!t.includes('mean ')) problems.push('climatology day cell does not label its amount "mean": ' + t);
      if (t.includes('rain ')) problems.push('climatology day cell labels a 30-year mean as "rain": ' + t);
    } else if (!t.includes('rain ')) {
      problems.push('forecast day cell does not label its amount "rain": ' + t);
    }
  }


  // `landlordJson` is already declared further down for the cost-driver
  // check, so this reader of the same file gets its own name.
  const landlordLeadJson = JSON.parse(fs.readFileSync(path.join(repo, 'data/landlord.json'), 'utf8'));

  // 15. The executive bottom line is the block the page leads with.  Every
  //     answer must render its question, its text, its numbers, its basis and
  //     at least one official source link - an unsourced answer is withheld in
  //     the renderer, so finding one here means the withholding failed.
  const blItems = Array.from(doc.querySelectorAll('#landlord-bottom-line .bl-item'));
  if (blItems.length < 6) {
    problems.push('executive bottom line rendered ' + blItems.length + ' answer(s), expected 6');
  }
  blItems.forEach((it, i) => {
    const t = it.textContent.replace(/\s+/g, ' ').trim();
    const tag = 'bottom line #' + (i + 1);
    if (!/\d\./.test(t)) problems.push(tag + ' has no numbered question');
    if (t.includes('withheld')) problems.push(tag + ' rendered an answer with no source link');
    if (!it.querySelector('.bl-basis')) problems.push(tag + ' does not state its basis');
    const links = Array.from(it.querySelectorAll('.bl-source a'));
    if (!links.length) problems.push(tag + ' has no source link');
    links.forEach(a => {
      const href = a.getAttribute('href') || '';
      if (!/^https:\/\/[^/]*\.gov\//.test(href.replace(/^https:\/\/(www\.)?/, 'https://'))) {
        problems.push(tag + ' links to a non-official host: ' + href);
      }
    });
    const numbers = it.querySelectorAll('.bl-numbers tr');
    if (!numbers.length) problems.push(tag + ' has no supporting numbers');
    // The renderer must not silently drop a row whose value is missing: the
    // rendered row count has to match the data, so a blanked figure shows up
    // as an em dash below rather than vanishing.
    const srcItem = (((landlordLeadJson.executive_summary || {}).bottom_line) || [])[i] || {};
    const expectedRows = ((srcItem.numbers) || []).filter(x => x && x.label).length;
    if (expectedRows && numbers.length !== expectedRows) {
      problems.push(tag + ' rendered ' + numbers.length + ' number row(s) but the data has ' +
        expectedRows + ' - a missing value must render as an em dash, not vanish');
    }
    numbers.forEach(tr => {
      const v = tr.querySelector('td');
      const txt = v ? v.textContent.trim() : '';
      if (!txt || txt === '—' || txt === 'undefined' || txt === 'null') {
        problems.push(tag + ' has an empty number cell: ' + tr.textContent);
      }
    });
  });
  // The official-outlook strip must be visibly separate from the observed
  // record and must carry the ENSO state and the CPC tilt count.
  const officialText = text('#landlord-official');
  if (!/Official ENSO state/.test(officialText)) {
    problems.push('#landlord-official does not name the official ENSO state');
  }
  if (!/baseline/.test(officialText)) {
    problems.push('#landlord-official does not mention the CPC climatological baseline');
  }
  if (/undefined|null|NaN/.test(officialText)) {
    problems.push('#landlord-official leaks a data token: ' + officialText.slice(0, 200));
  }

  // 16. A CPC record sitting on the 33% three-way baseline must be labelled in
  //     both CPC tables, so the same value cannot read as a tilt in one place
  //     and as no-tilt in another.  The expectation is derived from CPC's own
  //     Cat/Prob fields rather than from the flag under test - otherwise
  //     deleting the flag would also delete the reason to look for it and the
  //     guard could never fire (which is exactly what the first draft did).
  const calJson = JSON.parse(fs.readFileSync(path.join(repo, 'data/calendar.json'), 'utf8'));
  const cpcRecords = (calJson.cpc && calJson.cpc.records) || [];
  const isDirectional = c => ['ABOVE', 'BELOW', 'A', 'B'].includes(String(c || '').toUpperCase());
  const atBaseline = r => {
    const prob = Number(r && r.prob);
    return Number.isFinite(prob) && Math.abs(prob - (100 / 3)) < 0.5;
  };
  const shouldBeLabelled = cpcRecords.filter(r => r && isDirectional(r.category) && atBaseline(r));
  if (shouldBeLabelled.length) {
    ['#landlord-cpc', '#cpc-season-table'].forEach(sel => {
      if (!/at the 33% baseline/.test(text(sel))) {
        problems.push(sel + ' does not label a CPC record that sits on the 33% baseline (' +
          shouldBeLabelled.length + ' record(s) qualify from the raw Cat/Prob fields)');
      }
    });
  }
  cpcRecords.filter(r => r && r.probability_at_climatological_baseline).forEach(r => {
    if (!(isDirectional(r.category) && atBaseline(r))) {
      problems.push('CPC record flagged as at-baseline but its raw fields are Cat=' +
        r.category + ' Prob=' + r.prob);
    }
  });

  // 17. Severity counters are published once the fetching run has produced
  //     them.  The check keys on the PRESENCE of the field, not on a non-null
  //     mean, so a null mean is caught instead of skipping the guard.
  const sev = (calJson.season_summary || {});
  const windText = text('#wind-table');
  const windRows = Array.from(doc.querySelectorAll('#wind-table tr'));
  [['wind_days_ge_30kt', '30'], ['gust_days_ge_40kt', '40'], ['gust_days_ge_50kt', '50']]
    .forEach(([k, kt]) => {
      if (!(k in sev)) return;
      if (!windText.includes('\u2265 ' + kt + ' kt')) {
        problems.push('#wind-table does not render the ' + k + ' severity counter');
        return;
      }
      const row = windRows.find(tr => tr.textContent.includes('\u2265 ' + kt + ' kt'));
      const cell = row && row.querySelector('td') ? row.querySelector('td').textContent.trim() : '';
      // A counter that is published has a mean by construction (it is the
      // mean of 30 per-season counts), so the page must show a number.  An em
      // dash here means the data was published incomplete and the renderer
      // swallowed it - which is a defect, not a graceful degradation.
      if (!/mean [\d.]+/.test(cell)) {
        problems.push('#wind-table shows "' + cell + '" for ' + k +
          ', a counter that is published with no usable mean');
      }
    });
  if (/undefined|null|NaN/.test(windText)) {
    problems.push('#wind-table leaks a data token: ' + windText.slice(0, 200));
  }
  if (/undefined|null|NaN/.test(text('#storm-summary'))) {
    problems.push('#storm-summary leaks a data token: ' + text('#storm-summary').slice(0, 200));
  }

  // 17b. The counted-vs-published threshold table is the page's own evidence
  //      that the two methods agree, so it has to render every threshold the
  //      pipeline compared, print both columns, and quote the verdict the
  //      pipeline computed rather than a sentence typed into the renderer.
  const sevBlk = ((((landlordLeadJson.executive_summary || {}).severity) || {}));
  const cmpRows = sevBlk.threshold_comparison || [];
  if (cmpRows.length) {
    const stormText = text('#storm-summary');
    cmpRows.forEach(t => {
      const label = '≥ ' + Number(t.threshold_in).toFixed(2) + ' in';
      if (!stormText.includes(label)) {
        problems.push('#storm-summary omits the ' + label + ' threshold row');
      }
      const cells = Array.from(doc.querySelectorAll('#storm-summary td'))
        .map(td => td.textContent.trim());
      const pair = [t.project_mean_days, t.noaa_expected_days]
        .filter(v => v !== null && v !== undefined)
        .map(v => Number(v).toFixed(2));
      pair.forEach(v => {
        if (!cells.includes(v)) {
          problems.push('#storm-summary does not show ' + v + ' for the ' + label +
            ' row (the value is in the data)');
        }
      });
    });
    const verdict = (sevBlk.two_method_agreement || {}).statement;
    if (verdict && !stormText.includes(verdict)) {
      problems.push('#storm-summary does not quote the computed agreement verdict: "' +
        verdict + '"');
    }
    if (!verdict && !/does not carry a computed agreement verdict/.test(stormText)) {
      problems.push('#storm-summary neither quotes an agreement verdict nor says one is missing');
    }
  }

  // 18. The renaming of nws_window.days_covered must not have been half-done:
  //     a stale reader silently reads undefined and prints "0 day(s)".
  const win = calJson.nws_window || {};
  if (win.days_covered !== undefined && win.scoreboard_days_in_horizon === undefined) {
    problems.push('nws_window still uses the old days_covered key');
  }
  const rcCount = text('#rc-count');
  if (/undefined|null|NaN/.test(rcCount)) {
    problems.push('#rc-count leaks a data token: ' + rcCount.slice(0, 200));
  }

  // Day dialog must open and must not leak "[object HTMLSpanElement]".
  const btn = days[0];
  if (btn) {
    btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const dlg = text('#day-dialog-body');
    if (dlg.length < 50) problems.push('day dialog did not render');
    if (dlg.includes('[object HTML')) problems.push('day dialog leaked a DOM node as text');
    ['Humidity', 'Chance of rain', 'Rain amount', 'Max wind', 'Max gust']
      .forEach(k => { if (!dlg.includes(k)) problems.push('day dialog missing row: ' + k); });
  }

  // The day dialog's column count must come from the data.  It read
  // "13 element columns read, including 14 traced to named columns" while the
  // 13 was hard-coded and the file also carries a year-count column.
  {
    const cell = doc.querySelector('.day[data-date]');
    if (cell) {
      cell.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
      const dlg = text('#day-dialog-body');
      const m = dlg.match(/(\d+) column\(s\) of the published file traced/);
      if (dlg.includes('element columns read') && !m) {
        problems.push('day dialog states a hard-coded published-column count: ' +
          dlg.slice(Math.max(0, dlg.indexOf('Source: NCEI') - 120), dlg.indexOf('Source: NCEI') + 60));
      }
      if (m && Number(m[1]) < 10) {
        problems.push('day dialog reports an implausibly small published-column count: ' + m[1]);
      }
    }
  }

  // CSV export path.
  try {
    const csv = doc.querySelector('#export-csv');
    if (!csv) problems.push('#export-csv button missing');
    else csv.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  } catch (e) {
    problems.push('CSV export threw: ' + e.message);
  }

  // ---- content integrity: what the reader actually sees -------------------
  // These are the display-level rules the project promises.  Each one guards a
  // defect that reached the page at least once.
  const body = doc.body.textContent;

  // 1. Official prose must be decoded: no HTML entity text may be rendered.
  const entity = body.match(/&[a-zA-Z]{2,10};|&#\d{1,5};/);
  if (entity) problems.push('rendered page contains un-decoded HTML entity: ' + entity[0]);

  // 2. The ENSO alert status must be shown in full, not truncated.
  const enso = JSON.parse(fs.readFileSync(path.join(repo, 'data/enso.json'), 'utf8'));
  const status = enso.diagnostic_status;
  if (status && status.length > 4 && !text('#enso-body').includes(status)) {
    problems.push('ENSO alert status not shown in full: expected "' + status + '"');
  }

  // 3. The displayed ONI must be the published ONI, not a typed-in number.
  const latest = (enso.official_oni || {}).latest;
  if (latest && latest.oni_c !== undefined) {
    const shown = text('#enso-body');
    if (!shown.includes(String(latest.oni_c))) {
      problems.push('official ONI ' + latest.oni_c + ' is not shown in #enso-body');
    }
  }

  // 4. Climatology days must show the humidity normal when the data has one.
  const cal = JSON.parse(fs.readFileSync(path.join(repo, 'data/calendar.json'), 'utf8'));
  const firstClimo = (cal.days || []).find(d => d.tier === 'climatology' && d.humidity_pct !== null);
  if (firstClimo && !days[0].textContent.includes('RH')) {
    problems.push('climatology day cell shows no humidity');
  }

  // 5. If the committed ledger has failures, the page must show them (a failed
  //    run commits diagnostics only, and the failure has to be visible).
  const ledger = JSON.parse(fs.readFileSync(path.join(repo, 'data/verify.json'), 'utf8'));
  const quality = JSON.parse(fs.readFileSync(path.join(repo, 'data/quality_report.json'), 'utf8'));
  const failed = (ledger.summary || {}).failed || 0;
  const vtext = text('#verify-body');
  const qualityErrors = (quality.counts || {}).errors || 0;
  if ((failed || qualityErrors) && !doc.querySelector('#data-status .callout-error')) {
    problems.push('data status does not surface a verification or quality error');
  }
  if (failed > 0) {
    const id = (ledger.summary.failed_checks || [])[0];
    if (id && !vtext.includes(id)) {
      problems.push('ledger has ' + failed + ' failure(s) but the page does not show ' + id);
    }
  }

  // The verification ledger must be rendered with a verdict.
  if (!/checks passed|checks failed/.test(text('#verify-body'))) {
    problems.push('verification ledger did not render a verdict');
  }

  // ---- defects found by review on 2026-09-17, each now guarded -------------

  // 6. Every source link in the action checklist must show its whole URL.
  //    Slicing the label to 80 chars rendered "...access/USW000", which reads
  //    like a station ID but is not one - on a page whose premise is that a
  //    reader can click through and check the source by hand.
  doc.querySelectorAll('.action-source a').forEach((a, i) => {
    const shown = a.textContent.trim();
    const href = a.getAttribute('href') || '';
    if (!shown) { problems.push('action source link ' + i + ' has no visible text'); return; }
    if (!href.endsWith(shown) && href !== shown) {
      problems.push('action source link ' + i + ' is truncated: shows "' + shown + '" for ' + href);
    }
  });

  // 7. The reality-check sentence must not claim days carry an NWS forecast
  //    when the horizon covers none of them.
  const calWin = (cal.nws_window || {});
  const rcText = text('#rc-count');
  if (/range\.\s+carry a real/i.test(rcText)) {
    problems.push('#rc-count contains the broken fragment "...range. carry a real..."');
  }
  if (!calWin.scoreboard_days_in_horizon && /carry a real NWS forecast/.test(rcText)) {
    problems.push('#rc-count says days carry a real NWS forecast but scoreboard_days_in_horizon is 0');
  }

  // 8. A CPC explanation must describe the category it is attached to.
  //    The note used to be keyed on the variable only, so "Equal chances" got
  //    the wording for "Above median".
  const landlord = JSON.parse(fs.readFileSync(path.join(repo, 'data/landlord.json'), 'utf8'));
  (landlord.action_items || [])
    .filter(a => a.category === 'Official CPC outlook')
    .forEach(a => {
      const m = /^CPC [^:]+: (.+?) \(/.exec(a.title || '');
      const cat = m && m[1];
      if (cat && !String(a.detail || '').includes("'" + cat + "'")) {
        problems.push('CPC note does not explain its own category "' + cat + '": ' + a.title);
      }
    });

  // 9. The monthly rainfall table must say whether each CPC line is rain or
  //    temperature - a bare "Above normal 40%" next to rainfall columns was
  //    the temperature outlook with nothing to say so.
  const monthlyCell = doc.querySelectorAll('#landlord-monthly tbody tr');
  if (!monthlyCell.length) problems.push('#landlord-monthly rendered no rows');
  monthlyCell.forEach((tr, i) => {
    const cells = tr.querySelectorAll('td');
    const cpcCell = cells[cells.length - 1];
    if (!cpcCell) return;
    const t = cpcCell.textContent;
    if (/^EC$/.test(t.trim())) problems.push('monthly CPC cell ' + i + ' shows bare "EC"');
    if (/Rain|Temp|—/.test(t) === false) {
      problems.push('monthly CPC cell ' + i + ' has no Rain/Temp label: ' + t);
    }
    if (/Rain/.test(t) && !cpcCell.querySelector('.cpc-var-prcp')) {
      problems.push('monthly CPC cell ' + i + ' claims Rain with no prcp chip');
    }
  });

  // 10. A labelled source link must point at the endpoint its label names.
  //     These were picked by array position, so inserting the gridpoint source
  //     made "Open on weather.gov" resolve to an api.weather.gov URL.
  const EXPECTED_LINKS = [
    ['Open on weather.gov', /^https:\/\/forecast\.weather\.gov\//],
    ['NWS API endpoint', /^https:\/\/api\.weather\.gov\/gridpoints\//],
    ['gridpoint data', /^https:\/\/api\.weather\.gov\/gridpoints\/[^/]+\/\d+,\d+$/]
  ];
  EXPECTED_LINKS.forEach(([label, re]) => {
    doc.querySelectorAll('a').forEach(a => {
      if (a.textContent.trim() !== label) return;
      const href = a.getAttribute('href') || '';
      if (!re.test(href)) {
        problems.push('link "' + label + '" points at the wrong endpoint: ' + href);
      }
    });
  });

  // 11. Humidity must be displayed rounded - the NWS observation carries ~14
  //     significant figures and rendering them verbatim read like a bug.
  const longFloat = (text('#nws-obs').match(/\d+\.\d{4,}\s*%/) || [])[0];
  if (longFloat) problems.push('#nws-obs shows unrounded humidity: ' + longFloat);

  // 12. Every day in the official forecast window must carry a gust and a rain
  //     amount.  The hourly product returns neither for this grid cell, so both
  //     used to render as em dashes while NWS published them at the same point.
  const cfDays = (cal.current_forecast || {}).days || [];
  if (!cfDays.length) problems.push('current_forecast has no days');
  cfDays.forEach(d => {
    if (d.gust_max_mph === null || d.gust_max_mph === undefined) {
      problems.push('forecast day ' + d.date + ' has no gust');
    }
    if (d.rain_amount_in === null || d.rain_amount_in === undefined) {
      problems.push('forecast day ' + d.date + ' has no rain amount');
    }
    if (d.gust_max_mph !== null && !d.gust_basis) {
      problems.push('forecast day ' + d.date + ' shows a gust with no stated basis');
    }
    if (d.rain_amount_in !== null && !d.rain_amount_basis) {
      problems.push('forecast day ' + d.date + ' shows a rain amount with no stated basis');
    }
  });

  // 13. The maintenance cost-driver block: rendered, sourced, and honest
  //     about which sentence is guidance and which number is data.
  const cdCards = doc.querySelectorAll('#landlord-cost-drivers .cost-driver');
  if (cdCards.length < 4) problems.push('expected >=4 cost drivers, found ' + cdCards.length);
  cdCards.forEach((card, i) => {
    const t = card.textContent;
    if (!/guidance/i.test(t)) problems.push('cost driver ' + i + ' does not label its guidance sentence');
    if (!card.querySelector('.cd-ev th')) problems.push('cost driver ' + i + ' has no evidence table');
    if (!card.querySelector('a[href^="https://"]')) problems.push('cost driver ' + i + ' has no source link');
    if (/NaN|undefined/.test(t)) problems.push('cost driver ' + i + ' shows a raw NaN/undefined');
  });
  // A cost driver must never render without its numbers.
  const landlordJson = JSON.parse(fs.readFileSync(path.join(repo, 'data/landlord.json'), 'utf8'));
  const nExpected = ((landlordJson.executive_summary || {}).cost_drivers || [])
    .filter(d => (d.evidence || []).length).length;
  if (cdCards.length !== nExpected) {
    problems.push('rendered ' + cdCards.length + ' cost drivers but the dataset has ' +
      nExpected + ' with evidence');
  }

  // 14. Raw ENSO data tokens are keys, not phrases: "el_nino" must never be
  //     printed.  Both the summary sentence and the stat card showed it raw.
  const landlordText = text('#landlord');
  if (/\bel_nino\b|\bla_nina\b/.test(landlordText)) {
    problems.push('raw ENSO phase token visible on the landlord dashboard');
  }

  // 15. The ENSO stat card must name the season of the official ONI value
  //     (e.g. "JJA 2026") - an earlier version printed a bare " ONI ·" line.
  const ensoStat = Array.from(doc.querySelectorAll('#landlord-stats .landlord-stat'))
    .find(x => /ENSO/.test(x.textContent));
  if (!ensoStat) problems.push('ENSO stat card missing');
  else {
    const et = ensoStat.textContent;
    if (!/ONI/.test(et)) problems.push('ENSO stat card does not mention ONI: ' + et);
    if (!/[A-Z]{3} 20\d\d/.test(et)) problems.push('ENSO stat card does not name the ONI season: ' + et);
  }

  // 16. Nothing on the whole page may render the machine artefacts NaN or
  //     "undefined".
  ['#landlord', '#season', '#calendar', '#wind'].forEach(sel => {
    const t = text(sel);
    if (/\bundefined\b|\bNaN\b/.test(t)) {
      problems.push('section ' + sel + ' renders "undefined" or "NaN"');
    }
  });

  if (problems.length) {
    console.error('SMOKE TEST FAILED');
    problems.forEach(p => console.error(' - ' + p));
    process.exit(1);
  }
  console.log('smoke test passed: all sections rendered, day dialog and CSV export work');
  process.exit(0);
}, 900);
