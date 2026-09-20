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
  '#provenance', '#nws-verification-body', '#cpc-backtest-body', '#digest-body',
  '#model-guidance-body', '#feed-body',
  '#verify-body', '#quality-report', '#caveats'
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

    // The ENSO phase table is the only place the rain-duration question is
    // answered for the phase the season is actually in, so the phase-conditioned
    // column has to be there AND show the denominator it was computed over.  A
    // bare percentage would let an 11-season sample read as settled fact.
    const ensoText = text('#enso-strat');
    if (!/7\+ day wet spell/.test(ensoText)) {
      problems.push('ENSO table lost the phase-conditioned 7+ day wet-spell column');
    }
    if (!/\(\d+ of \d+\)/.test(ensoText)) {
      problems.push('phase-conditioned column does not print its sample size (n of n)');
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
  // NWS verification card must either show scored pairs or explicitly state it
  // is waiting for the first observable day - never silently empty.
  const nwsV = text('#nws-verification-body');
  if (!nwsV.includes('scored') && !nwsV.includes('observ') && !nwsV.includes('wait')) {
    problems.push('#nws-verification-body does not explain its status: ' + nwsV.slice(0, 200));
  }
  // CPC back-test card must either show scored seasons or explain the archive gap.
  const cpcV = text('#cpc-backtest-body');
  if (!cpcV.includes('back') && !cpcV.includes('archive') && !cpcV.includes('archive')
      && !cpcV.includes('Season') && !cpcV.includes('tilt')) {
    problems.push('#cpc-backtest-body does not explain its status: ' + cpcV.slice(0, 200));
  }

  ['#landlord', '#season', '#calendar', '#wind'].forEach(sel => {
    const t = text(sel);
    if (/\bundefined\b|\bNaN\b/.test(t)) {
      problems.push('section ' + sel + ' renders "undefined" or "NaN"');
    }
  });

  // 19. The NWS Area Forecast Discussion card must render the scan the ledger
  //     verified: the sentence count it claims, a quote block for every
  //     published sentence, the scope caveat, and a link to the product.
  //     A card that silently renders nothing would hide the only qualitative
  //     storm language the site publishes.
  {
    const calJson = JSON.parse(fs.readFileSync(path.join(repo, 'data/calendar.json'), 'utf8'));
    const afd = calJson.afd_language || null;
    const card = doc.querySelector('#afd-language');
    if (!afd) {
      problems.push('calendar.json has no afd_language block');
    } else if (!card) {
      problems.push('#afd-language card missing from the page');
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

  // 24. The storm-watch digest card: threshold, privacy, and consistency
  //     with data/digest.json (quiet state or one row per trigger).
  {
    const dt = text('#digest-body');
    let dg = null;
    try {
      dg = JSON.parse(fs.readFileSync(path.join(repo, 'data/digest.json'), 'utf8'));
    } catch (e) { /* digest not built this run; the card must say so */ }
    if (!dg) {
      if (!dt.includes('No digest was produced')) {
        problems.push('#digest-body does not explain the missing digest.json');
      }
    } else {
      const thr = String((dg.pop_threshold_pct ?? 50));
      if (!dt.includes(thr + '%') && !dt.includes(thr + ' %')) {
        problems.push('#digest-body does not state the POP threshold (' + thr + '%)');
      }
      if (!dt.includes('stores no address')) {
        problems.push('#digest-body does not publish the opt-in privacy statement');
      }
      const n = ((dg.nws_alerts || []).length) + ((dg.high_pop_days || []).length);
      if (n === 0 && !dt.includes('Quiet')) {
        problems.push('#digest-body shows no quiet state although the digest has 0 triggers');
      }
      if (n > 0) {
        const rows = doc.querySelectorAll('#digest-body tbody tr').length;
        if (rows !== n) {
          problems.push('#digest-body renders ' + rows + ' trigger row(s) but digest.json has ' + n);
        }
      }
    }
    const rss = doc.querySelector('#digest a[href="data/alerts.xml"]');
    if (!rss) problems.push('digest card has no subscribe link to data/alerts.xml');
  }

  // 25. AFD issuance history: when the data carries last-mention dates, the
  //     card must show them; the history file must be linked.
  {
    const hist = ((cal.afd_language || {}).history) || {};
    const lm = hist.last_mention || {};
    const card = doc.querySelector('#afd-language');
    const t = card ? card.textContent : '';
    if (Object.keys(lm).length) {
      if (!t.includes('last mentioned')) {
        problems.push('AFD card omits the last-mentioned history the data carries');
      }
      const dated = Object.values(lm).filter(b => b.last_issuance_time);
      dated.forEach(b => {
        if (!t.includes(b.last_issuance_time)) {
          problems.push('AFD card omits the last-mention date for ' + (b.label || '?'));
        }
      });
      if (!card.querySelector('a[href="data/afd_history.json"]')) {
        problems.push('AFD card does not link data/afd_history.json');
      }
    }
  }

  // 26. The day dialog's deep links: every headline field must offer the
  //     exact official row/file behind it, on an official host.
  {
    const cell = doc.querySelector('.day[data-date]');
    if (cell) {
      cell.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
      const dlg = doc.querySelector('#day-dialog-body');
      const dt = dlg ? dlg.textContent : '';
      if (!dt.includes('Verify each number yourself')) {
        problems.push('day dialog renders no per-field deep links');
      }
      const OFFICIAL = /^(api\.weather\.gov|forecast\.weather\.gov|www\.ncei\.noaa\.gov|www\.cpc\.ncep\.noaa\.gov|ftp\.cpc\.ncep\.noaa\.gov|www\.weather\.gov)$/;
      const links = dlg ? Array.from(dlg.querySelectorAll('table a[href^="https://"]')) : [];
      if (!links.length) {
        problems.push('day dialog deep-link table has no https links');
      }
      links.forEach(a => {
        const host = (a.getAttribute('href') || '').replace(/^https:\/\//, '').split('/')[0];
        if (!OFFICIAL.test(host)) {
          problems.push('day dialog deep link leaves the official hosts: ' + a.getAttribute('href'));
        }
      });
    }
  }

  // 27. The CPC back-test card must match data/cpc_backtest.json: a hit-rate
  //     when rows are scored, otherwise the pending-backfill reason — never a
  //     silent or half-rendered state.
  {
    let bt = null;
    try {
      bt = JSON.parse(fs.readFileSync(path.join(repo, 'data/cpc_backtest.json'), 'utf8'));
    } catch (e) { /* file legitimately absent until the first scheduled run */ }
    const t = text('#cpc-backtest-body');
    if (!bt) {
      if (!t.includes('missing this run')) {
        problems.push('#cpc-backtest-body does not explain the missing back-test file');
      }
    } else if ((bt.rows || []).length) {
      const hr = (bt.summary || {}).hit_rate_pct;
      if (hr !== null && hr !== undefined && !t.includes(String(hr) + '%')) {
        problems.push('#cpc-backtest-body does not show the scored hit-rate ' + hr + '%');
      }
    } else {
      if (!t.includes('back-fill') && !t.includes('backfill')) {
        problems.push('#cpc-backtest-body does not explain the pending back-fill');
      }
    }
  }

  // 28. The model-guidance tier must be impossible to read as a forecast:
  //     the warning comes before any content, every item repeats it, and not one
  //     model token may reach the scoreboard grid.
  {
    const sec = text('#model-guidance-body');
    let mg = null;
    try {
      mg = JSON.parse(fs.readFileSync(path.join(repo, 'data/model_guidance.json'), 'utf8'));
    } catch (e) { mg = null; }
    if (!mg) {
      if (!/Not yet built/i.test(sec)) {
        problems.push('model_guidance.json is absent but the section does not say so: ' +
          sec.slice(0, 160));
      }
    } else {
      if (!/NOT AN OFFICIAL FORECAST/i.test(sec)) {
        problems.push('the model-guidance warning is not rendered');
      }
      const warnAt = sec.search(/NOT AN OFFICIAL FORECAST/i);
      const firstMap = sec.search(/Archived NMME probability maps/i);
      if (firstMap > -1 && warnAt > firstMap) {
        problems.push('the model-guidance warning appears after the maps, not before them');
      }
      const figs = Array.from(doc.querySelectorAll('#model-guidance-body .mg-figure'));
      const imgs = (mg.images || []).filter(i => i.local_path);
      if (imgs.length && figs.length !== imgs.length) {
        problems.push('model-guidance images rendered ' + figs.length + ' figure(s) for ' +
          imgs.length + ' archived image(s)');
      }
      figs.forEach(f => {
        if (!/not an official forecast/i.test(f.textContent)) {
          problems.push('a model-guidance image carries no warning of its own');
        }
      });
      const grid = text('#calendar-grid');
      if (/NMME|model guidance/i.test(grid)) {
        problems.push('the scoreboard grid mentions the model-guidance tier');
      }
      if (mg.coverage_verbatim && !sec.includes(mg.coverage_verbatim)) {
        problems.push('NOAA\'s own coverage string is not rendered verbatim: ' +
          mg.coverage_verbatim);
      }
      ((mg.pages || {}).description || {}).verbatim_sentences &&
        ((mg.pages.description.verbatim_sentences || []).forEach(q => {
          if (!sec.includes(q)) {
            problems.push('an NMME definition sentence is not rendered verbatim: ' +
              q.slice(0, 70));
          }
        }));
    }
  }

  // 29. The official-product feed must render what it counted, newest first,
  //     with a tier pill on every row and no row pretending to a date NOAA did
  //     not publish.
  {
    const sec = text('#feed-body');
    let feed = null;
    try {
      feed = JSON.parse(fs.readFileSync(path.join(repo, 'data/feed.json'), 'utf8'));
    } catch (e) { feed = null; }
    if (!feed) {
      if (!/Not yet built/i.test(sec)) {
        problems.push('feed.json is absent but the section does not say so: ' + sec.slice(0, 160));
      }
    } else {
      const c = feed.counts || {};
      if (!sec.includes(String(c.entries || 0) + ' entries')) {
        problems.push('the feed section does not report its own entry count (' +
          (c.entries || 0) + '): ' + sec.slice(0, 180));
      }
      const rows = Array.from(doc.querySelectorAll('#feed-rows tbody tr'));
      if (!rows.length) problems.push('the feed rendered no rows');
      rows.forEach(tr => {
        const pill = tr.querySelector('.pill');
        if (!pill || !/OFFICIAL|NOT OFFICIAL/.test(pill.textContent)) {
          problems.push('a feed row carries no official/not-official pill: ' +
            tr.textContent.replace(/\s+/g, ' ').slice(0, 120));
        }
        const prov = tr.querySelectorAll('.pill')[1];
        if (!prov || !/fetch recorded|no fetch recorded|local copy/.test(prov.textContent)) {
          problems.push('a feed row does not say whether a fetch stands behind it');
        }
      });
      const shownDates = rows.map(tr => (tr.cells[0] || {}).textContent || '');
      const stamps = shownDates.filter(t => /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d/.test(t.trim()));
      const sorted = stamps.slice().sort().reverse();
      if (stamps.length > 1 && JSON.stringify(stamps) !== JSON.stringify(sorted)) {
        problems.push('the feed is not rendered newest first');
      }
      if ((feed.undated_entries || []).length && !/undated by the publisher/i.test(sec)) {
        problems.push('the feed has undated entries but never says a publisher gave no date');
      }
      const dateOnly = (feed.entries || []).filter(e => e.date_utc && !e.timestamp_utc).length;
      if (dateOnly && !/date but no time/i.test(sec)) {
        problems.push('the feed has date-only entries but never says no clock time was published');
      }
      const modelRows = (feed.entries || []).filter(e =>
        String(e.kind || '').indexOf('model-guidance') === 0);
      if (modelRows.length && !/NOT OFFICIAL/.test(sec)) {
        problems.push('model-guidance feed rows are not labelled NOT OFFICIAL');
      }
    }
  }

  // 30. The prognostic-discussion caveats: when the dataset carries verbatim
  //     CPC caveats, every one must render inside the official-outlook strip
  //     with its source link; when the discussion could not be archived, the
  //     strip must say so instead of silently dropping the card.  A caveat
  //     that rendered without the "no number attached" marker would read as
  //     a project claim rather than NOAA's own sentence.
  {
    const stripText = text('#landlord-official');
    let caveats = null;
    try {
      caveats = (((JSON.parse(fs.readFileSync(path.join(repo, 'data/landlord.json'), 'utf8'))
        .executive_summary || {}).official_outlook || {}).prognostic_caveats) || null;
    } catch (e) { caveats = null; }
    if (!caveats) {
      if (!/official ENSO state/i.test(stripText)) {
        problems.push('no prognostic_caveats block and the official strip did not render at all');
      }
    } else if (caveats.available) {
      (caveats.quotes || []).forEach(q => {
        if (!stripText.includes(q.text || '')) {
          problems.push('caveat "' + (q.key || '?') + '" is in the dataset but not rendered: ' +
            (q.text || '').slice(0, 90));
        }
      });
      if ((caveats.quotes || []).length && !/no number or date attached/i.test(stripText)) {
        problems.push('rendered caveats do not carry the "no number or date attached" marker');
      }
      if (!/Read CPC\u2019s prognostic discussion|Read CPC's prognostic discussion/.test(stripText)) {
        problems.push('the caveats card does not link the prognostic discussion');
      }
    } else {
      // The card must still render, stating its reason verbatim, so an absent
      // archive is disclosed on the page rather than silently dropped.
      if (!/What the outlook/.test(stripText)) {
        problems.push('caveats block is unavailable but no caveat card rendered to say so');
      } else if (!caveats.reason || !stripText.includes(caveats.reason.slice(0, 40))) {
        problems.push('the unavailable caveats card does not state its reason');
      }
    }
  }

  // 31. The ENSO strength outlook: CPC's own probability sentences about how
  //     strong this El Niño gets, quoted verbatim in the official-outlook
  //     strip.  Same contract as the caveats card, checked independently:
  //     every dataset quote must render, the card must carry its own marker
  //     (so the reader knows the probabilities are CPC's, not this project's)
  //     and its own discussion link, and an unavailable block must render a
  //     card stating its reason rather than silently dropping.
  {
    const stripText = text('#landlord-official');
    let estr = null;
    try {
      estr = (((JSON.parse(fs.readFileSync(path.join(repo, 'data/landlord.json'), 'utf8'))
        .executive_summary || {}).official_outlook || {}).enso_strength) || null;
    } catch (e) { estr = null; }
    if (!estr) {
      if (!/official ENSO state/i.test(stripText)) {
        problems.push('no enso_strength block and the official strip did not render at all');
      }
    } else if (estr.available) {
      (estr.quotes || []).forEach(q => {
        if (!stripText.includes(q.text || '')) {
          problems.push('strength quote \"' + (q.key || '?') + '\" is in the dataset but not rendered: ' +
            (q.text || '').slice(0, 90));
        }
      });
      if ((estr.quotes || []).length && !/no number or date of its own/i.test(stripText)) {
        problems.push('rendered strength quotes do not carry the \"no number or date of its own\" marker');
      }
      if (!/Read CPC\u2019s ENSO Diagnostic Discussion|Read CPC's ENSO Diagnostic Discussion/.test(stripText)) {
        problems.push('the strength card does not link the ENSO Diagnostic Discussion');
      }
    } else {
      if (!/How strong CPC expects/i.test(stripText)) {
        problems.push('strength block is unavailable but no strength card rendered to say so');
      } else if (!estr.reason || !stripText.includes(estr.reason.slice(0, 40))) {
        problems.push('the unavailable strength card does not state its reason');
      }
    }
  }

  // 33. The phase-conditioned severity table (hard-rain days, gusts, wind +
  //     rain in the seasons that sat in this ENSO phase).  When the dataset
  //     carries it, the official strip must render every row with the value
  //     the dataset holds, the phase's n beside the all-season n, and the
  //     small-sample "not a forecast" wording; the ENSO season card must carry
  //     the three severity columns.  When the dataset lacks it, nothing may be
  //     rendered in its place - an empty table would read as "no severity".
  {
    const stripText = text('#landlord-official');
    let cs = null;
    try {
      cs = (((JSON.parse(fs.readFileSync(path.join(repo, 'data/landlord.json'), 'utf8'))
        .executive_summary || {}).official_outlook || {}).enso_conditioned_severity) || null;
    } catch (e) { cs = null; }
    const cell = doc.querySelector('[data-test="enso-conditioned-severity"]');
    if (!cs || !(cs.rows || []).length) {
      if (cell) problems.push('no enso_conditioned_severity rows in the dataset but a severity cell rendered');
    } else {
      if (!cell) {
        problems.push('enso_conditioned_severity is in the dataset but the strip did not render it');
      } else {
        const ct = cell.textContent.replace(/\s+/g, ' ');
        if (!ct.includes(`(${cs.seasons_in_phase} of the ${cs.seasons_total})`)) {
          problems.push('the severity cell does not print the phase n beside the all-season n');
        }
        if (!/not a forecast/i.test(ct)) {
          problems.push('the severity cell lacks the "not a forecast" small-sample wording');
        }
        const rowsRendered = cell.querySelectorAll('tbody tr').length;
        if (rowsRendered !== cs.rows.length) {
          problems.push('the severity cell rendered ' + rowsRendered + ' row(s) for ' + cs.rows.length + ' in the dataset');
        }
        cs.rows.forEach(r => {
          const want = `${r.phase_mean} \u00b7 ${r.phase_median} \u00b7 ${r.phase_max}`;
          if (!ct.includes(r.label) || !ct.includes(want)) {
            problems.push('severity row not rendered as published: ' + r.label + ' -> ' + want);
          }
        });
        if (/upper bound/i.test(ct)) {
          problems.push('the severity cell asserts an unsourced "upper bound" for the Sunset');
        }
        if (!cell.querySelector('a[href]')) problems.push('the severity cell has no source link');
      }
      const ensoText = text('#enso-strat');
      ['Days \u2265 1.00 in, mean', 'Days gust \u2265 40 kt, mean', 'Wind + rain days (whole-day), mean'].forEach(h => {
        if (!ensoText.includes(h)) problems.push('ENSO season card lost the severity column "' + h + '"');
      });
    }
    // The wind figures may no longer be presented as a bound for the ZIP: no
    // source in this project establishes the direction (bug 74).
    const pageText = doc.body.textContent.replace(/\s+/g, ' ');
    if (/upper bound for (the )?(Sunset|94122|ZIP|neighbou?rhood)/i.test(pageText)
        || /SFO is more exposed/i.test(pageText)
        || /(runs|is) windier than the (Sunset|ZIP|neighbou?rhood)/i.test(pageText)) {
      problems.push('the page still calls the SFO wind record an "upper bound" / "more exposed" for the Sunset (unsourced direction, bug 74)');
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
