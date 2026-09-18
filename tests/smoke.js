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
  //     "undefined".  This used to name four sections, which quietly left out
  //     the two the newest cards live in (#now, #location) - so it now walks
  //     every <section> in the document and a future card is covered without
  //     anyone having to remember to extend a list.
  {
    const sections = Array.from(doc.querySelectorAll('section[id]'));
    if (sections.length < 4) {
      problems.push('only ' + sections.length + ' sections found to scan for NaN/undefined');
    }
    sections.forEach(sec => {
      const t = (sec.textContent || '');
      if (/\bundefined\b|\bNaN\b/.test(t)) {
        const m = t.match(/.{0,60}(\bundefined\b|\bNaN\b).{0,40}/);
        problems.push('section #' + sec.id + ' renders "undefined" or "NaN": ' +
          (m ? m[0].replace(/\s+/g, ' ') : ''));
      }
      if (/\[object HTML/.test(t)) {
        problems.push('section #' + sec.id + ' leaked a DOM node as text');
      }
    });
    ['#landlord', '#season', '#calendar', '#wind', '#now', '#location'].forEach(sel => {
      if (!doc.querySelector(sel)) problems.push('expected section ' + sel + ' is missing');
    });
    // A missing value must render as an em dash or a named reason, never as the
    // machine token.  The word "null" does appear legitimately inside an
    // irregularity message ("some hourly fields are null"), so this checks the
    // shape of the leak - an element whose whole content is the token - rather
    // than banning the word.
    Array.from(doc.querySelectorAll('td, th, .value, .stat-value, .fine, span'))
      .forEach(node => {
        const own = (node.textContent || '').trim();
        if (/^(null|undefined|NaN)$/.test(own)) {
          problems.push('a cell renders a bare machine token "' + own + '" (' +
            (node.closest('section[id]') || {}).id + ')');
        }
      });
  }

  // 19. The NWS Area Forecast Discussion card must render the scan the ledger
  //     verified: the sentence count it claims, a quote block for every
  //     published sentence, the scope caveat, and a link to the product.
  //     A card that silently renders nothing would hide the only qualitative
  //     storm language the site publishes.
  {
    const calJson = JSON.parse(fs.readFileSync(path.join(repo, 'data/calendar.json'), 'utf8'));
    const afd = calJson.afd_language || null;
    const card = doc.querySelector('#afd-language');
    if (!card) {
      problems.push('#afd-language card missing from the page');
    } else if (!afd) {
      // Dataset completeness is the ledger's job (afd-language-verbatim fails a
      // build with no block).  What the page owes is an honest sentence, so a
      // future upstream failure cannot leave a card that looks populated.
      const t0 = card.textContent;
      if (!/not present|not scanned/i.test(t0)) {
        problems.push('AFD card is empty instead of saying the scan is absent: ' + t0.slice(0, 90));
      }
      if (/\bundefined\b|\bNaN\b/.test(t0)) problems.push('AFD card renders undefined/NaN');
    } else if (afd.scanned === false) {
      // Honest degradation: the reason must be printed, not swallowed.
      const t0 = card.textContent;
      if (!/not scanned/i.test(t0)) problems.push('AFD card does not say it was not scanned');
      if (!(afd.reason || '').trim() || !t0.includes(String(afd.reason).trim().slice(0, 30))) {
        problems.push('AFD card does not print the recorded reason for not scanning: ' + afd.reason);
      }
      if (afd.source_url && !card.querySelector('a[href^="https://"]')) {
        problems.push('AFD card knows the product URL but prints no link');
      }
      if (/\bundefined\b|\bNaN\b/.test(t0)) problems.push('AFD card renders undefined/NaN');
    } else {
      const t = card.textContent;
      const nSentences = (afd.categories || []).reduce((n, c) => n + (c.sentences || []).length, 0);
      if (t.length < 200) problems.push('AFD card rendered almost nothing: ' + t.slice(0, 120));
      if (/\bundefined\b|\bNaN\b/.test(t)) problems.push('AFD card renders undefined/NaN');
      if (!String(afd.sentences_scanned).length || !t.includes(String(afd.sentences_scanned))) {
        problems.push('AFD card does not state how many sentences were scanned (' +
          afd.sentences_scanned + ')');
      }
      if (!card.querySelector('a[href^="https://"]')) {
        problems.push('AFD card has no link to the NWS product it quotes');
      }
      // Every published sentence must appear on the page, inside a quote block.
      const quotes = Array.from(card.querySelectorAll('.quote')).map(q => q.textContent.trim());
      const missing = (afd.categories || [])
        .flatMap(c => (c.sentences || []).map(s => s.sentence))
        .filter(s => !quotes.some(q => q.includes(s.trim())));
      if (missing.length) {
        problems.push('AFD card omits ' + missing.length + ' of ' + nSentences +
          ' published sentences: ' + missing[0].slice(0, 90));
      }
      if (!quotes.length && nSentences) {
        problems.push('AFD card published no quote blocks although ' + nSentences + ' sentences exist');
      }
      // The caveats are published in the data as strings; the card must render
      // each of them, not merely mention the word "scope".  A renderer that
      // read the wrong key would otherwise look correct.
      ['scope_caveat', 'usage_note', 'verbatim_rule'].forEach(k => {
        const want = (afd[k] || '').trim();
        if (want.length < 20) {
          problems.push('afd_language.' + k + ' is missing or too short in the data');
        } else if (!t.includes(want.slice(0, 60))) {
          problems.push('AFD card does not render afd_language.' + k + ': ' + want.slice(0, 70));
        }
      });
      // The scan is qualitative by contract: a date or a rainfall amount
      // attached to a quotation would be an invention rendered as NWS's words.
      const invented = (afd.categories || []).flatMap(c => (c.sentences || []).flatMap(s =>
        Object.keys(s).filter(k => !['section', 'sentence', 'matched_patterns'].includes(k))));
      if (invented.length) {
        problems.push('an AFD quotation carries a non-quotation key: ' + invented[0]);
      }
    }
  }

  // 20. Every headline number in the day dialog must name the basis it was
  //     computed from.  The ledger enforces this on the data; this enforces it
  //     on what a landlord actually reads.
  {
    const cell = doc.querySelector('.day[data-date]');
    if (cell) {
      cell.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
      const dlg = text('#day-dialog-body');
      const headline = doc.querySelector('#day-dialog-body table.kv');
      const rows = headline ? Array.from(headline.querySelectorAll('tr')) : [];
      const ABSENT = /\u2014|not available|no official/i;
      rows.forEach(tr => {
        const label = ((tr.cells[0] || {}).textContent || '').trim();
        const value = ((tr.cells[1] || {}).textContent || '').trim();
        if (!label || ABSENT.test(value)) return;   // no value, so no basis is owed
        const fine = tr.querySelector('.fine');
        if (!fine || fine.textContent.trim().length < 8) {
          problems.push('day dialog shows "' + label + '" with no basis: ' +
            tr.textContent.replace(/\s+/g, ' ').slice(0, 140));
        }
      });
      // All six headline fields the brief asks for must be present to check.
      const allLabels = rows.map(tr => ((tr.cells[0] || {}).textContent || '')).join('|');
      ['High / low', 'Humidity', 'Chance of rain', 'Rain amount', 'Max wind', 'Max gust']
        .forEach(k => { if (!allLabels.includes(k)) problems.push('day dialog headline table missing row: ' + k); });
      if (!rows.length) problems.push('day dialog rendered no headline rows to check for basis');
      if (!dlg) problems.push('day dialog empty while checking basis');
    }
  }

  // 21. The hour-by-hour wind+rain block: the headline figure must be the one in
  //     the data, the comparison row must not vanish, and an unavailable figure
  //     must say so rather than render as a zero.
  {
    const hwr = ((landlordJson.executive_summary || {}).wind_and_rain_hourly) || {};
    const card = text('#landlord-windrain');
    const board = text('#wind-table');
    if (hwr.available) {
      const mean = (hwr.days_with_a_simultaneous_hour || {}).mean;
      if (mean === undefined) {
        problems.push('hourly block reports available with no days mean in the data');
      } else {
        const want = Number(mean).toFixed(1);
        if (!card.includes('same HOUR') || !card.includes(`mean ${want}`)) {
          problems.push('landlord wind+rain card does not render the hourly mean ' + want);
        }
        if (!board.includes('same HOUR')) {
          problems.push('wind section does not render the hourly figure');
        }
      }
      // The whole-day figure this page published first must still be on the page.
      if (!card.includes('downtown gauge + SFO wind')) {
        problems.push('the whole-day cross-station figure is gone from the card');
      }
      // "At the same time" is an hourly statement: the card must define the hour
      // it counts, not merely print a number.
      const method = (hwr.method || '').trim();
      if (method.length < 20 || !card.includes(method.slice(0, 50))) {
        problems.push('the hourly card does not publish the rule it counted by');
      }
      // Multi-hour accumulations are disclosed in the confidence line.
      const conf = ((landlordJson.executive_summary.bottom_line || [])
        .find(r => r.key === 'wind_and_rain') || {}).confidence || '';
      if (hwr.simultaneous_hours_from_multi_hour_reports > 0
          && !/longer than one hour/.test(conf + ' ' + card)) {
        problems.push('multi-hour precipitation reports are counted but not disclosed');
      }
    } else if (!card.includes('not published')) {
      problems.push('hourly block unavailable but the card does not say so');
    }
  }

  // 22. Archive recency: if the run publishes it, the page must show every
  //     archive with its date, and must flag the stale ones by name.
  {
    let runFile = {};
    try {
      runFile = JSON.parse(fs.readFileSync(path.join(repo, 'data/run.json'), 'utf8'));
    } catch (e) {
      problems.push('data/run.json could not be read for the archive-recency guard');
    }
    const cov = runFile.record_coverage || {};
    const quality = text('#quality-report');
    if ((cov.archives || []).length) {
      cov.archives.forEach(a => {
        if (a.last_date && !quality.includes(a.last_date)) {
          problems.push('archive recency not rendered for ' + a.area + ' (' + a.last_date + ')');
        }
      });
      const flag = text('#quality-stale-flag');
      if (!flag) {
        problems.push('run publishes stale archives but no stale-archive flag is rendered');
      }
      (cov.stale_archives || []).forEach(area => {
        const row = (cov.archives || []).find(a => a.area === area) || {};
        const label = row.label || area;
        if (!flag.includes(label)) {
          problems.push('the stale-archive flag does not name ' + area +
            ' (expected its label "' + label + '" in: ' + flag.slice(0, 120) + ')');
        }
      });
    }
  }

  // 23. The status line must not call an expected absence a failure: the counts
  //     it prints are recomputed here from the provenance manifest itself.
  {
    let prov = { entries: [] };
    try {
      prov = JSON.parse(fs.readFileSync(path.join(repo, 'data/provenance.json'), 'utf8'));
    } catch (e) {
      problems.push('data/provenance.json could not be read for the fetch-count guard');
    }
    const entries = prov.entries || [];
    const realFailures = entries.filter(e => e.ok === false && !e.expected_absent);
    const absences = entries.filter(e => e.ok === false && e.expected_absent);
    const meta = text('#data-status');
    if (entries.length) {
      if (!meta.includes(String(entries.length) + ' recorded source fetches')) {
        problems.push('the status line does not report the manifest size');
      }
      if (!meta.includes(String(realFailures.length) + ' failed fetch')) {
        problems.push('the status line does not report ' + realFailures.length +
          ' real failure(s); it says: ' + meta.slice(0, 200));
      }
      if (absences.length && !/absent by design/.test(meta)) {
        problems.push('the status line hides ' + absences.length +
          ' expected absence(s) instead of publishing them');
      }
    }
  }

  // 24. The Location card's honesty about the Census geography.  The site calls
  //     this point the Sunset District, so the card must either show the Census
  //     evidence for that name or say plainly that the lookup did not run.
  //     The third possibility - printing a district name with no evidence, or
  //     claiming a retrieval that did not happen - is what this guard exists to
  //     catch; it was found by tests/degrade_smoke.py, which broke the fallback
  //     wording and discovered nothing noticed.
  {
    const runJson = JSON.parse(fs.readFileSync(path.join(repo, 'data/run.json'), 'utf8'));
    const g = (((runJson.target || {}).centroid) || {}).census_geographies || null;
    const card = doc.querySelector('#location');
    if (!card) {
      problems.push('#location card missing');
    } else {
      const t = card.textContent;
      const rows = Array.from(card.querySelectorAll('tr'));
      const subRow = rows.find(tr => /County subdivision/i.test((tr.cells[0] || {}).textContent || ''));
      const subVal = subRow ? ((subRow.cells[1] || {}).textContent || '') : '';
      if (!subRow) {
        problems.push('Location card has no "County subdivision (Census)" row');
      } else if (!g) {
        if (!/not retrieved/i.test(subVal)) {
          problems.push('no Census geography in the dataset but the card does not say it was ' +
            'not retrieved: "' + subVal.slice(0, 90) + '"');
        }
        if (/CCD|Census Tract|GEOID/i.test(subVal)) {
          problems.push('the card names a geography it has no evidence for: "' +
            subVal.slice(0, 90) + '"');
        }
      } else {
        const name = g.county_subdivision;
        if (name && !subVal.includes(String(name))) {
          problems.push('Census named "' + name + '" but the card shows "' + subVal.slice(0, 70) + '"');
        }
        if (g.county_subdivision_geoid && !t.includes(String(g.county_subdivision_geoid))) {
          problems.push('the card omits the county-subdivision GEOID ' + g.county_subdivision_geoid);
        }
        if (!/geocoding\.geo\.census\.gov/.test(
              Array.from(card.querySelectorAll('a')).map(a => a.getAttribute('href') || '').join(' '))) {
          problems.push('the card prints no link to the Census geocoder it read');
        }
        const note = (doc.querySelector('#location-note') || {}).textContent || '';
        if ((g.naming_note || '').trim().length > 20 && !note.includes(String(g.naming_note).trim().slice(0, 40))) {
          problems.push('the card omits the published naming_note that says this is a Census ' +
            'subdivision, not a city neighbourhood');
        }
        if ((g.geography_types_returned || []).length &&
            !note.includes(String(g.geography_types_returned[0]))) {
          problems.push('the card omits the geography types the Census actually returned');
        }
      }
    }
  }

  if (problems.length) {
    console.error('SMOKE TEST FAILED');
    problems.forEach(p => console.error(' - ' + p));
    process.exit(1);
  }
  console.log('smoke test passed: all sections rendered, day dialog and CSV export work');
  process.exit(0);
}, 900);
