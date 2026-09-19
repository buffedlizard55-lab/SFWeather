#!/usr/bin/env python3
"""Alert digest for 94122 — RSS + JSON, opt-in, no tracking.

Generates two files from the already-verified datasets (no new fetches):

* ``data/alerts.xml`` — RSS 2.0 feed with one item per trigger:
  - an NWS alert in force for CAZ006 (real alerts only; test messages excluded)
  - a day inside the current NWS horizon with max hourly POP >= POP_THRESHOLD_PCT
* ``data/digest.json`` — the same triggers as JSON, plus the run timestamp and
  the privacy statement.

Privacy story (also published in the feed description and on the site):
* Opt-in: nothing is sent anywhere.  A reader subscribes with their own feed
  reader by adding the feed URL; the project stores no address, sends no email,
  and sets no cookies.
* No personal data is collected, logged, or transmitted by this project.  The
  feed is a static file on GitHub Pages; subscription happens entirely between
  the reader and their feed reader.
* Email delivery is deliberately NOT offered: it would require storing
  addresses and running a sender, which this static project cannot do honestly.

Thresholds are constants below so the ledger and the tests read the same values
the feed was built with.

Run:  python3 pipeline/build_digest.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import xml.sax.saxutils as sax
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

_env_dir = __import__("os").environ.get("SFWEATHER_DATA")
if _env_dir:
    DATA = Path(_env_dir)

POP_THRESHOLD_PCT = 50
SITE_URL = "https://buffedlizard55-lab.github.io/SFWeather/"
FEED_URL = SITE_URL + "data/alerts.xml"

PRIVACY_NOTE = (
    "Opt-in only: subscribe with your own feed reader; this project stores no "
    "address, sends no email, and collects no personal data. The feed is a "
    "static file — subscription happens entirely between you and your reader."
)


def load(name):
    p = DATA / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _rfc822(iso_value):
    """ISO timestamp -> RFC-822 pubDate.  Falls back to now, never raises."""
    try:
        v = (iso_value or "").replace("Z", "+00:00")
        d = dt.datetime.fromisoformat(v)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.strftime("%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        return dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")


def collect_triggers(calendar, nws):
    """Return (alert_items, pop_items) from verified datasets only."""
    cal = calendar or {}
    cf = cal.get("current_forecast") or {}
    alerts_block = cf.get("alerts") or (nws or {}).get("active_alerts") or {}
    alert_items = []
    for ev in alerts_block.get("events") or []:
        if ev.get("is_test"):
            continue  # test messages are never alerts
        alert_items.append({
            "kind": "nws-alert",
            "title": f"NWS {ev.get('event') or 'alert'} — {alerts_block.get('zone') or 'CAZ006'}",
            "link": (nws or {}).get("active_alerts", {}).get("source_url")
                    or "https://api.weather.gov/alerts/active?zone=CAZ006",
            "pubDate": ev.get("effective") or ev.get("expires") or cf.get("forecast_updated"),
            "description": (ev.get("headline") or ev.get("description") or "")[:500],
            "event": ev.get("event"),
            "severity": ev.get("severity"),
        })
    pop_items = []
    for d in cf.get("days") or []:
        pop = d.get("rain_chance_pct")
        if pop is None:
            continue
        if not isinstance(pop, (int, float)) or isinstance(pop, bool):
            raise ValueError(f"current_forecast day {d.get('date')}: rain_chance_pct "
                             f"is not a number ({pop!r}); refusing to guess the digest")
        if pop < POP_THRESHOLD_PCT:
            continue
        pop_items.append({
            "kind": "high-pop-day",
            "title": f"{d.get('date')} enters the NWS window with POP {pop:g}%",
            "link": SITE_URL + "#now",
            "pubDate": cf.get("forecast_updated"),
            "description": (
                f"Official NWS gridded forecast for the 94122 point: max hourly POP "
                f"{pop:g}% on {d.get('date')} ({d.get('weekday')}); "
                f"QPF {d.get('rain_amount_in')} in; "
                f"hours covered {d.get('hours_covered')} of 24."),
            "date": d.get("date"),
            "pop_pct": pop,
        })
    return alert_items, pop_items


def rss_xml(alert_items, pop_items, generated_utc):
    items = list(alert_items) + list(pop_items)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0">', '<channel>',
             f"<title>{sax.escape('SFWeather 94122 — NWS alerts & high-POP days')}</title>",
             f"<link>{sax.escape(SITE_URL)}</link>",
             f"<description>{sax.escape('Opt-in digest: NWS alerts for CAZ006 and days in the 7-day window with POP ≥ %d%%. %s' % (POP_THRESHOLD_PCT, PRIVACY_NOTE))}</description>",
             f"<lastBuildDate>{sax.escape(_rfc822(generated_utc))}</lastBuildDate>",
             f"<generator>{sax.escape('SFWeather pipeline/build_digest.py')}</generator>"]
    for it in items:
        parts += ["<item>",
                  f"<title>{sax.escape(it.get('title') or '')}</title>",
                  f"<link>{sax.escape(it.get('link') or SITE_URL)}</link>",
                  f"<guid isPermaLink=\"false\">{sax.escape((it.get('kind') or '') + ':' + (it.get('title') or ''))}</guid>",
                  f"<pubDate>{sax.escape(_rfc822(it.get('pubDate')))}</pubDate>",
                  f"<description>{sax.escape(it.get('description') or '')}</description>",
                  "</item>"]
    parts += ["</channel>", "</rss>", ""]
    return "\n".join(parts)


def main():
    calendar = load("calendar.json")
    nws = load("nws.json")
    run = load("run.json")
    generated_utc = run.get("generated_utc") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    alert_items, pop_items = collect_triggers(calendar, nws)
    digest = {
        "generated_utc": generated_utc,
        "feed_url": FEED_URL,
        "pop_threshold_pct": POP_THRESHOLD_PCT,
        "privacy": PRIVACY_NOTE,
        "opt_in": ("Subscribe by adding the feed URL to any RSS reader. No signup, "
                   "no email, no tracking."),
        "nws_alerts": alert_items,
        "high_pop_days": pop_items,
        "counts": {"nws_alerts": len(alert_items), "high_pop_days": len(pop_items)},
        "sources": {
            "alerts": "https://api.weather.gov/alerts/active?zone=CAZ006",
            "forecast": "https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly",
        },
    }
    (DATA / "digest.json").write_text(json.dumps(digest, indent=2))
    (DATA / "alerts.xml").write_text(rss_xml(alert_items, pop_items, generated_utc))
    print(f"  digest: {len(alert_items)} alert(s), {len(pop_items)} high-POP day(s) "
          f"(threshold POP ≥ {POP_THRESHOLD_PCT}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
