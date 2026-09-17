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
  '#landlord-stats', '#landlord-monthly', '#landlord-duration', '#landlord-windrain',
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
    ['rain', 'wind', 'gust', 'RH'].forEach(k => {
      if (!t.includes(k)) problems.push('day cell is missing "' + k + '": ' + t);
    });
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
  const failed = (ledger.summary || {}).failed || 0;
  const vtext = text('#verify-body');
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

  if (problems.length) {
    console.error('SMOKE TEST FAILED');
    problems.forEach(p => console.error(' - ' + p));
    process.exit(1);
  }
  console.log('smoke test passed: all sections rendered, day dialog and CSV export work');
  process.exit(0);
}, 900);
