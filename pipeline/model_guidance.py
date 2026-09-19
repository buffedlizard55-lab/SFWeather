#!/usr/bin/env python3
"""Model guidance tier: NMME / CFSv2 material, kept strictly apart from the forecast.

This is the tier the brief asked for and the one most likely to do harm if it is
built carelessly.  A model ensemble is **not an official forecast**.  CPC's
official seasonal outlook - the shapefile product already sampled and published
on this site - is a human-adjusted, verified product; the raw multi-model
ensemble behind it is neither.  So:

* everything this script publishes lives in its own file
  (``data/model_guidance.json``), its own site section and its own navigation
  entry, with the warning rendered *before* the content and repeated on every
  item;
* no number it produces is ever merged into ``data/calendar.json``.  The claim
  ledger enforces that separation rather than trusting this comment
  (``model-guidance-isolation``);
* no value is read out of a model image.  The images are archived so a reader
  can look at NOAA's own picture; the probability rules that explain what the
  contours mean are quoted verbatim from NOAA's description page, and every
  quote is re-checked as a substring of the fetched text on every run;
* raw model output (GRIB2 / netCDF) is **not decoded**.  Decoding would need a
  third-party library this project does not take, and a decoded field re-gridded
  to a ZIP code would be a new forecast this project cannot verify against a
  published official product.  What the archive holds, and where, is recorded
  instead so the limitation is documented rather than hidden.

Sources are all on hosts this project has already vetted:
``www.cpc.ncep.noaa.gov``, ``ftp.cpc.ncep.noaa.gov`` and (probed, not decoded)
``nomads.ncep.noaa.gov``.

Run:  ``python3 pipeline/model_guidance.py [--assetsdir assets/model_guidance]``
      ``python3 pipeline/model_guidance.py --selftest``   (offline)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib_fetch as fetchlib      # noqa: E402
import lib_provenance as provlib  # noqa: E402

CPC = "https://www.cpc.ncep.noaa.gov/products/NMME"

#: The warning is data, not decoration: it is written into the file, rendered
#: before every item on the page, and required by the claim ledger.
WARNING = (
    "MODEL GUIDANCE - NOT AN OFFICIAL FORECAST. These are raw multi-model "
    "ensemble products (NMME, and CFSv2 where listed). They are not the "
    "National Weather Service forecast, they are not CPC's official seasonal "
    "outlook, and no value from this section is used anywhere else on this site "
    "or merged into the day-by-day scoreboard. Treat it as background on what "
    "the models say, and read the official outlook - which is a verified NWS "
    "product - in the CPC section above."
)

ITEM_WARNING = (
    "Model guidance, not an official forecast. Not merged into the scoreboard."
)

#: Pages to read.  Each is fetched and its status recorded; a page that does not
#: resolve is published as unavailable rather than linked anyway.
PAGES = [
    {"key": "prob_index", "label": "NMME probability forecasts (index)",
     "url": f"{CPC}/probindex.shtml",
     "why": "carries NOAA's own statement of the period the model maps cover"},
    {"key": "description", "label": "Description of the NMME probability forecasts",
     "url": f"{CPC}/NMME_PROB_descr.html",
     "why": "defines what the contours mean, so the maps cannot be misread"},
    {"key": "seasonal_prcp", "label": "NMME seasonal precipitation-rate probability (North America)",
     "url": f"{CPC}/prob/usPROBprate.S.html",
     "why": "the seasonal precipitation probability maps themselves"},
    {"key": "seasonal_temp", "label": "NMME seasonal 2m-temperature probability (North America)",
     "url": f"{CPC}/prob/usPROBtmp2m.S.html",
     "why": "the seasonal temperature probability maps themselves"},
    {"key": "skill", "label": "NMME Ranked Probability Skill Score maps",
     "url": f"{CPC}/prob/rpss.probindex.html",
     "why": "how much skill the ensemble has actually had - published next to the "
            "maps so they are not read as better than they are"},
    {"key": "verification", "label": "NMME real-time verification (preliminary)",
     "url": f"{CPC}/verif/index.html",
     "why": "NOAA's own running verification of these model forecasts"},
    {"key": "archive", "label": "NMME real-time forecast archive",
     "url": "https://ftp.cpc.ncep.noaa.gov/NMME/archive/",
     "why": "the raw archived model runs; recorded, not decoded"},
]

#: Raw model output locations that are *probed* (status recorded) and never
#: published as a working link unless the probe succeeds.
PROBES = [
    {"key": "nomads_cfs_prod", "label": "NOMADS CFSv2 production directory",
     "url": "https://nomads.ncep.noaa.gov/pub/data/nccf/com/cfs/prod/",
     "note": ("CFSv2 GRIB2 output. Probed for availability only: this project "
              "takes no GRIB2 decoder, so nothing is read out of these files.")},
    {"key": "nmme_archive_latest", "label": "Latest NMME archived run directory",
     "url": None,      # filled in from the archive page at runtime
     "note": ("The newest archived real-time NMME run. Recorded with NOAA's own "
              "coverage label; the netCDF/GRIB inside is not decoded.")},
]

# Matched against a *resolved* URL, never against raw markup: NOAA's pages mix
# absolute and relative links and both quote styles, and a pattern that assumes
# one of them silently finds nothing.  That is not hypothetical - the first live
# run of this tier archived zero maps because the pattern required an absolute
# href in double quotes.
IMAGE_URL_RE = re.compile(
    r"/images/(?:th\.)?prob_ensemble_(prate|tmp2m)_us_season(\d+)\.png$", re.I)
# An anchor's href, in double quotes, single quotes, or no quotes at all.
HREF_RE = re.compile(r"""(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
# NOAA writes the coverage as a range ("For: October 2026 - April 2027") and
# sometimes as a single month.  A non-greedy "anything up to a year" pattern
# captured only the first half of the range, so the two forms are matched
# explicitly, longest first, and the form that matched is published with it.
COVERAGE_RANGE_RE = re.compile(
    r"For:\s*([A-Z][a-z]+\.?\s+\d{4}\s*[-\u2013\u2014]\s*[A-Z][a-z]+\.?\s+\d{4})")
COVERAGE_MONTH_RE = re.compile(r"For:\s*([A-Z][a-z]+\.?\s+\d{4})")
# Matched against a resolved URL as well.  The old form also required the label
# to sit between ">" and "<" with no tag in between, so a listing that wraps its
# text in <font> (as CPC pages often do) matched nothing at all.
ARCHIVE_RUN_RE = re.compile(r"/NMME/archive/(\d{10})/?$", re.I)


def log(msg=""):
    print(msg, flush=True)


def clean_text(body):
    """Decode with the publisher's own encoding and disclose any lost glyph."""
    text, encoding = fetchlib.decode_text(body)
    text, removed, contexts = fetchlib.strip_unrepresentable(text)
    return text, encoding, removed, contexts


def html_text_only(html):
    """Strip tags so quote extraction works on words, not markup."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#8217;", "'"), ("&#8220;", '"'),
                 ("&#8221;", '"'), ("&#8211;", "-")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def collapse(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _attr_url(match):
    """The first quoted (or bare) value of an href/src attribute, or None."""
    for group in match.groups()[1:] if match.lastindex and match.lastindex > 1 else match.groups():
        if group:
            return group.strip()
    return None


def extract_links(markup, base_url):
    """Every href/src on a page, resolved against the page's own URL.

    Relative links, single-quoted attributes and unquoted attributes all yield
    the same absolute URL here, so a pattern can be matched against the result
    instead of against markup whose quoting style this project does not control.
    """
    out = []
    for m in HREF_RE.finditer(markup or ""):
        raw = next((g for g in m.groups() if g), None)
        if not raw:
            continue
        raw = raw.strip()
        if not raw or raw.startswith(("#", "javascript:", "mailto:")):
            continue
        out.append(urljoin(base_url, raw))
    return out


def extract_anchors(markup, base_url):
    """``(absolute_url, label)`` for every anchor, in document order.

    The label is the anchor's text with any nested tags stripped and whitespace
    collapsed, because CPC wraps its coverage labels in markup of their own
    choosing.  Order matters: the archive listing is newest first, and this
    project publishes the newest run rather than guessing which is newest.
    """
    out = []
    for attrs, inner in ANCHOR_RE.findall(markup or ""):
        hm = re.search(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", attrs, re.I)
        if not hm:
            continue
        raw = next((g for g in hm.groups() if g), None)
        if not raw or not raw.strip():
            continue
        label = collapse(html_text_only(inner))
        out.append((urljoin(base_url, raw.strip()), label))
    return out


def markup_excerpt(markup, limit=700):
    """A bounded slice of raw markup, kept only when extraction found nothing.

    Without it, "the page fetched fine but this project understood nothing on
    it" is undiagnosable from the committed data - which is exactly what
    happened on the first live run, when the pages were 200 OK and the parsed
    lists were empty.
    """
    text = (markup or "").strip()
    i = text.lower().find("<a")
    start = i if i >= 0 else 0
    return collapse(text[start:start + limit])


def key_sentences(plain, limit=8):
    """Verbatim sentences that define what the model maps mean.

    Every returned string is a whitespace-collapsed substring of the fetched
    page text, which the claim ledger re-checks; a sentence that is not found in
    the source fails the build.
    """
    wanted = (r"ensemble contains", r"are terciles", r"contours show",
              r"White areas show", r"tercile limits were determined",
              r"thresholds were determined", r"hindcast")
    out = []
    for chunk in re.split(r"(?<=[.;])\s+", plain):
        c = collapse(chunk)
        if len(c) < 25 or len(c) > 400:
            continue
        if any(re.search(w, c, re.I) for w in wanted):
            if c not in out:
                out.append(c)
        if len(out) >= limit:
            break
    return out


def build(assetsdir=Path("assets/model_guidance"), datadir=Path("data"),
          fetch=fetchlib.get, today=None):
    """Fetch, archive and package the model-guidance tier."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    assetsdir = Path(assetsdir)
    manifest, irregularities, pages, images = [], [], {}, []

    def note(severity, message, evidence=None):
        irregularities.append({"severity": severity, "area": "model_guidance",
                               "message": message, "evidence": evidence or {}})

    for page in PAGES:
        res = fetch(page["url"], timeout=180)
        manifest.append(res.provenance(note=f"NMME model-guidance page: {page['label']}"))
        entry = {**page, "http_status": res.status, "ok": bool(res.ok),
                 "bytes": res.size, "sha256": res.sha256,
                 "retrieved_utc": res.retrieved_utc, "warning": ITEM_WARNING}
        if res.ok and res.body:
            raw, encoding, removed, contexts = clean_text(res.body)
            entry["text_encoding"] = encoding
            entry["characters_removed"] = removed
            if removed:
                entry["removal_contexts"] = contexts
            plain_page = html_text_only(raw)
            entry["plain_text_excerpt"] = plain_page[:1500]
            if page["key"] in ("description", "prob_index"):
                # the full text of the pages this project quotes, so the ledger
                # can re-check every quoted sentence against the fetched wording
                # without fetching again (verify_claims.py:
                # model-guidance-quotes-verbatim)
                entry["plain_text"] = plain_page
            if page["key"] == "description":
                entry["verbatim_sentences"] = key_sentences(plain_page)
            if page["key"] == "prob_index":
                m = COVERAGE_RANGE_RE.search(plain_page)
                entry["coverage_form"] = "range" if m else None
                if not m:
                    m = COVERAGE_MONTH_RE.search(plain_page)
                    entry["coverage_form"] = "single month" if m else None
                entry["coverage_verbatim"] = collapse(m.group(1)) if m else None
                if not m:
                    note("warning",
                         "The NMME probability index page did not state the period its "
                         "maps cover, so no coverage string is published. Nothing is "
                         "inferred from the season numbers in the image filenames.",
                         {"url": page["url"]})
            if page["key"] in ("seasonal_prcp", "seasonal_temp"):
                markup = res.text()
                links = extract_links(markup, page["url"])
                entry["image_urls"] = sorted({u for u in links if IMAGE_URL_RE.search(u)})
                entry["n_links_seen"] = len(links)
                if not entry["image_urls"]:
                    # The page answered; this project understood nothing on it.
                    # Say so, and keep enough raw markup to diagnose it from the
                    # committed dataset instead of guessing.
                    entry["markup_excerpt"] = markup_excerpt(markup)
                    note("warning",
                         f"The {page['label']} page was retrieved "
                         f"({res.size} bytes) but no NMME probability map was "
                         f"recognised on it, so no map is archived this run. The "
                         f"markup excerpt in data/model_guidance.json shows what the "
                         f"page actually contains.",
                         {"url": page["url"], "links_seen": len(links)})
            if page["key"] == "archive":
                markup = res.text()
                anchors = extract_anchors(markup, page["url"])
                runs = []
                for url_found, label in anchors:
                    m = ARCHIVE_RUN_RE.search(url_found)
                    if not m:
                        continue
                    rid = m.group(1)
                    runs.append({"url": url_found, "run_id": rid,
                                 "coverage_label": label or rid})
                entry["archived_runs"] = runs[:14]
                entry["n_archived_runs_listed"] = len(runs)
                entry["n_links_seen"] = len(anchors)
                if not runs:
                    entry["markup_excerpt"] = markup_excerpt(markup)
                    note("warning",
                         f"The NMME archive index was retrieved ({res.size} bytes) "
                         f"but no run directory was recognised on it, so the newest "
                         f"archived run is not published this run. The markup excerpt "
                         f"in data/model_guidance.json shows what the page contains.",
                         {"url": page["url"], "anchors_seen": len(anchors)})
        else:
            entry["error"] = res.error or f"HTTP {res.status}"
            note("warning",
                 f"A model-guidance page could not be retrieved: {page['label']}",
                 {"url": page["url"], "status": res.status})
        pages[page["key"]] = entry

    # ---- archive the map images themselves (local copies, never hot-linked)
    assetsdir.mkdir(parents=True, exist_ok=True)
    seen = set()
    for key in ("seasonal_prcp", "seasonal_temp"):
        for url in pages.get(key, {}).get("image_urls") or []:
            if url in seen:
                continue
            seen.add(url)
            m = re.search(r"prob_ensemble_(prate|tmp2m)_us_season(\d+)\.png$", url, re.I)
            if not m:
                continue
            variable, season_no = m.group(1).lower(), int(m.group(2))
            if url.lower().endswith(".png") and "/images/th." in url.lower():
                continue                      # thumbnails: the full image is enough
            res = fetch(url, timeout=240)
            manifest.append(res.provenance(
                note=f"NMME model-guidance image: {variable} season {season_no}"))
            item = {"variable": "precipitation rate" if variable == "prate"
                    else "2m temperature",
                    "variable_key": variable,
                    "season_index": season_no,
                    "url": url, "http_status": res.status, "ok": bool(res.ok),
                    "warning": ITEM_WARNING,
                    "season_mapping_note": (
                        "The month range each 'season N' image covers is printed inside "
                        "the image by NOAA. This project does not re-derive it from the "
                        "filename, so no month range is asserted here.")}
            if res.ok and res.body and res.body[:8].startswith(b"\x89PNG"):
                slug = f"nmme_{variable}_us_season{season_no}.png"
                sha = fetchlib.save_bytes(assetsdir / slug, res.body)
                item.update({"local_path": f"{assetsdir}/{slug}".replace("\\", "/"),
                             "bytes": res.size, "sha256": sha})
            else:
                item["ok"] = False
                item["error"] = (res.error or f"HTTP {res.status}"
                                 if not res.ok else "response was not a PNG image")
                note("warning",
                     f"A NMME model-guidance image could not be archived: {url}",
                     {"status": res.status})
            images.append(item)
    images.sort(key=lambda i: (i["variable_key"], i["season_index"]))

    # ---- probes (availability only, never decoded)
    probes = []
    for probe in PROBES:
        url = probe["url"]
        if url is None:
            arch = pages.get("archive") or {}
            runs = arch.get("archived_runs") or []
            if not runs:
                # A probe that could not run must say why on the page, not merely
                # sit there with ok=false: the ledger treats an undisclosed
                # failure as a defect (model-guidance-links-fetched), and a reader
                # deserves to know whether NOAA was unreachable or whether this
                # project stopped understanding their page.
                if arch.get("ok"):
                    reason = ("the archive page was retrieved but listed no run "
                              "directories on this pass, so there was nothing to "
                              "probe - if NOAA changed the layout of that page, "
                              "the archive-listing parser needs updating, and the "
                              "markup excerpt published with the archive page shows "
                              "what it now contains")
                else:
                    reason = (f"the archive page could not be retrieved "
                              f"({arch.get('error') or 'HTTP ' + str(arch.get('http_status'))}), "
                              f"so no run directory was available to probe")
                probes.append({**probe, "url": None, "ok": False,
                               "error": reason,
                               "note": probe["note"],
                               "skipped": "the archive page listed no runs on this pass"})
                note("warning",
                     f"The raw model archive was not probed: {reason}",
                     {"archive_url": arch.get("url"),
                      "runs_listed": arch.get("n_archived_runs_listed")})
                continue
            url = runs[0]["url"]
        res = fetch(url, timeout=180)
        manifest.append(res.provenance(note=f"model-guidance availability probe: {probe['label']}"))
        entry = {**probe, "url": url, "http_status": res.status, "ok": bool(res.ok),
                 "bytes": res.size, "sha256": res.sha256,
                 "retrieved_utc": res.retrieved_utc,
                 "decoded": False,
                 "decoding_note": ("Nothing was read out of this location. Availability "
                                   "is recorded so the reader knows the raw model output "
                                   "is public, and so the reason this tier publishes no "
                                   "model numbers is on the record.")}
        if not res.ok:
            entry["error"] = res.error or f"HTTP {res.status}"
            note("info",
                 f"A model-guidance location was not reachable and is not published as a "
                 f"link: {probe['label']}",
                 {"url": url, "status": res.status})
        probes.append(entry)

    out = {
        "generated_utc": fetchlib.iso_utc(),
        "tier": "model-guidance",
        "not_an_official_forecast": True,
        "merged_into_scoreboard": False,
        "warning": WARNING,
        "isolation_rule": ("No value in this file may appear in data/calendar.json, "
                           "data/landlord.json or any day cell. pipeline/verify_claims.py "
                           "checks that (model-guidance-isolation) and fails the run if a "
                           "model value ever reaches the scoreboard."),
        "coverage_verbatim": (pages.get("prob_index") or {}).get("coverage_verbatim"),
        "pages": pages,
        "images": images,
        "probes": probes,
        "counts": {"pages_requested": len(PAGES),
                   "pages_retrieved": sum(1 for p in pages.values() if p.get("ok")),
                   "images_archived": sum(1 for i in images if i.get("local_path")),
                   "verbatim_sentences":
                       len((pages.get("description") or {}).get("verbatim_sentences") or []),
                   "probes_ok": sum(1 for p in probes if p.get("ok"))},
        "what_this_tier_does_not_do": [
            "It does not convert a model ensemble into a probability for one ZIP code.",
            "It does not read a value out of an image or a GRIB2/netCDF file.",
            "It does not blend model output with the official CPC outlook.",
            "It does not publish a month range for a 'season N' image that NOAA did not "
            "state in text.",
        ],
        "irregularities": irregularities,
    }
    return out, manifest


def write_outputs(out, manifest, datadir=Path("data")):
    datadir = Path(datadir)
    datadir.mkdir(parents=True, exist_ok=True)
    (datadir / "model_guidance.json").write_text(json.dumps(out, indent=2) + "\n")
    provlib.write_manifest(datadir, "model_guidance", manifest, out["generated_utc"],
                           "Fetches made by pipeline/model_guidance.py (model-guidance "
                           "tier; not an official forecast).")
    provlib.merge_irregularities(datadir, "model_guidance", out["irregularities"])
    return datadir / "model_guidance.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datadir", default="data")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--assetsdir", default="assets/model_guidance")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        import selftest_model_guidance
        return selftest_model_guidance.run()

    out, manifest = build(assetsdir=Path(args.assetsdir), datadir=Path(args.datadir))
    path = write_outputs(out, manifest, Path(args.outdir or args.datadir))
    c = out["counts"]
    log(f"model guidance: {c['pages_retrieved']}/{c['pages_requested']} pages, "
        f"{c['images_archived']} images archived, "
        f"{c['verbatim_sentences']} verbatim definition sentences")
    log(f"  coverage (verbatim): {out['coverage_verbatim']}")
    log(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
