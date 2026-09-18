// Reviewer tool: render index.html in jsdom against the committed data and dump
// the visible text of the page, section by section, so a human can read what a
// visitor actually sees without opening a browser.
//
// Usage:  node tools/dump_render.js [repoRoot] > render.txt
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.resolve(process.argv[2] || '.');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

function fetchLocal(url) {
  const clean = url.split('?')[0].split('#')[0];
  const p = path.join(root, clean);
  if (!fs.existsSync(p)) return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found' });
  const body = fs.readFileSync(p, 'utf8');
  return Promise.resolve({
    ok: true, status: 200, statusText: 'OK',
    text: () => Promise.resolve(body),
    json: () => Promise.resolve(JSON.parse(body)),
  });
}

const dom = new JSDOM(html, {
  url: 'http://localhost/',
  runScripts: 'dangerously',
  resources: undefined,
  pretendToBeVisual: true,
});
const { window } = dom;
window.fetch = fetchLocal;
window.requestAnimationFrame = (cb) => setTimeout(cb, 0);

// Re-run app.js now that fetch is stubbed.
const app = fs.readFileSync(path.join(root, 'assets/js/app.js'), 'utf8');
const script = window.document.createElement('script');
script.textContent = app;
window.document.body.appendChild(script);

setTimeout(() => {
  const doc = window.document;
  const loading = doc.getElementById('loading');
  if (loading && !loading.hidden) {
    console.error('WARNING: page still shows the loading state');
  }
  const sections = doc.querySelectorAll('main section, header.site-header');
  const out = [];
  sections.forEach((s) => {
    const head = s.querySelector('h1, h2');
    out.push('\n' + '='.repeat(78));
    out.push('SECTION ' + (s.id || s.className) + '  ::  ' + (head ? head.textContent.trim() : ''));
    out.push('='.repeat(78));
    const txt = s.textContent.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n');
    txt.split('\n').map((l) => l.trim()).filter(Boolean).forEach((l) => out.push(l));
    s.querySelectorAll('a[href]').forEach((a) => {
      out.push('  LINK: ' + a.textContent.trim().slice(0, 90) + ' -> ' + a.getAttribute('href').slice(0, 160));
    });
    s.querySelectorAll('table').forEach((t, i) => {
      out.push('  [table ' + (i + 1) + ': ' + t.querySelectorAll('tr').length + ' rows]');
    });
  });
  process.stdout.write(out.join('\n') + '\n');
}, 1500);
