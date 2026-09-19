#!/usr/bin/env python3
"""NWS Area Forecast Discussion (AFD) history - what the office has actually said.

The API forecast products on this site are machine-readable numbers.  The Area
Forecast Discussion is the other official product the same forecasters publish:
free text explaining *why*, and it is the only official place where an incoming
storm system is discussed before it has a numeric forecast attached.  For a
landlord asking "how bad does it get, and for how long", that discussion is
worth reading - but it is prose, not data, so this module treats it accordingly:

* quotes are copied verbatim from the product text.  Each one is re-checked as a
  whitespace-collapsed substring of the fetched text, here and again by
  ``pipeline/verify_claims.py``; nothing is paraphrased or summarised in the
  module's own words;
* a discussion is never turned into a number.  No probability, no amount, no
  wind speed is extracted from the prose, and nothing here reaches the
  scoreboard;
* every quote links to the official product it came from so a reader can read
  the surrounding paragraphs;
* only recent discussions are fetched.  The API list endpoint carries the
  office's most recent issues (typically a few weeks); older text is not
  available without a paid archive, so the window is recorded rather than
  padded out.

Host: ``api.weather.gov`` (already vetted in ``ALLOWED_HOSTS``).

Run:  ``python3 pipeline/afd_history.py``       ``python3 pipeline/afd_history.py --selftest``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib_fetch as fetchlib      # noqa: E402
import lib_provenance as provlib  # noqa: E402

OFFICE = "MTR"                     # NWS San Francisco Bay Area / Monterey
LIST_URL = f"https://api.weather.gov/products/types/AFD/locations/{OFFICE}"
PRODUCT_URL = "https://api.weather.gov/products/{id}"

#: How many discussions to download in full.  The list endpoint is fetched
#: regardless, so the issuance timeline is complete even when only a few texts
#: are retrieved.
MAX_TEXTS = 8
#: Cap on quotes per discussion / in total, so the dataset stays readable.
MAX_QUOTES_PER_PRODUCT = 6
MAX_QUOTES_TOTAL = 40

WARNING = (
    "These are verbatim quotations from the National Weather Service Area "
    "Forecast Discussion - forecasters' prose, not a numeric forecast. Nothing "
    "here is converted into a probability, an amount or a wind speed, and "
    "nothing here is merged into the day-by-day scoreboard. Read the quoted "
    "sentence in its original product (linked) before acting on it."
)

#: Words that make a sentence worth quoting for this brief: rain amount, rain
#: duration, wind, wind+rain together, and storm severity.
KEYWORDS = {
    "rain": r"\b(rain|rainfall|precip|precipitation|showers?|downpour|soaking|"
            r"atmospheric river|pineapple express)\b",
    "wind": r"\b(wind|windy|gusts?|gusting|breezy|gales?)\b",
    "storm": r"\b(storm|stormy|front|frontal|low pressure|cyclone|squall)\b",
    "duration": r"\b(days?|multi-day|through the (week|weekend)|extended|"
                r"persistent|lingering|several days|a week)\b",
    "dry": r"\b(dry|ridge|ridging|sunny|no rain|rain-free)\b",
    "fog": r"\b(fog|foggy|marine layer|stratus)\b",
}
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def log(msg=""):
    print(msg, flush=True)


def collapse(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalise_lines(text):
    """AFD text arrives as wrapped, uppercase-headed plain text.

    Headings are all-caps lines like ``.SHORT TERM...``; keeping them inline
    would glue a heading onto the sentence after it, so headings become their own
    sentence boundaries.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^\.([A-Z][A-Z &/\-]{2,})\.\.\.", r"\n\1. ", text)
    return text


def sentences(text):
    plain = normalise_lines(text or "")
    out = []
    for chunk in SENT_SPLIT_RE.split(plain):
        s = collapse(chunk)
        if 40 <= len(s) <= 500:
            out.append(s)
    return out


def keyword_hits(sentence):
    return sorted(k for k, pat in KEYWORDS.items() if re.search(pat, sentence, re.I))


def extract_quotes(text, limit=MAX_QUOTES_PER_PRODUCT):
    """Verbatim sentences that speak to rain, wind, duration or storm severity.

    A sentence is only returned if it is a whitespace-collapsed substring of the
    fetched text, so a quote can never drift from the product it cites.
    """
    source = collapse(normalise_lines(text or ""))
    chosen = []
    if limit <= 0:
        # the running total is already at MAX_QUOTES_TOTAL.  Without this guard
        # the loop below appends one sentence before testing the limit, so every
        # later product would leak one extra quote past the cap.
        return chosen
    for s in sentences(text):
        hits = keyword_hits(s)
        if not hits:
            continue
        if s not in source:                 # guard: never publish a non-verbatim string
            continue
        if s in chosen:
            continue
        chosen.append(s)
        if len(chosen) >= limit:
            break
    return chosen


def count_keywords(text):
    src = collapse(normalise_lines(text or "")).lower()
    return {k: len(re.findall(pat, src, re.I)) for k, pat in KEYWORDS.items()}


def build(datadir=Path("data"), fetch_json=fetchlib.get_json, limit=MAX_TEXTS):
    manifest, irregularities = [], []

    def note(severity, message, evidence=None):
        irregularities.append({"severity": severity, "area": "afd_history",
                               "message": message, "evidence": evidence or {}})

    obj, res = fetch_json(LIST_URL, timeout=120)
    manifest.append(res.provenance(note=f"NWS AFD product list for {OFFICE}"))
    issuances = []
    if obj and isinstance(obj, dict):
        graph = obj.get("@graph") or obj.get("products") or []
        for item in graph:
            if not isinstance(item, dict):
                continue
            pid = item.get("id") or (item.get("@id") or "").rstrip("/").split("/")[-1]
            if not pid:
                continue
            issuances.append({
                "id": pid,
                "issuance_utc": item.get("issuanceTime"),
                "url": item.get("@id") or PRODUCT_URL.format(id=pid),
                "product_name": item.get("productName") or "Area Forecast Discussion",
            })
    elif not res.ok:
        note("warning",
             "The NWS Area Forecast Discussion list could not be retrieved, so no "
             "discussion quotes are published on this run. The forecast numbers are "
             "unaffected: they come from api.weather.gov forecast products fetched by "
             "pipeline/main.py.",
             {"url": LIST_URL, "status": res.status, "error": res.error})
    else:
        note("warning",
             "The NWS AFD list response was not in the expected JSON shape, so no "
             "discussion quotes are published on this run.",
             {"url": LIST_URL, "top_level_keys": sorted(obj.keys())[:8]
              if isinstance(obj, dict) else type(obj).__name__})

    products = []
    total_quotes = 0
    for entry in issuances[:limit]:
        url = PRODUCT_URL.format(id=entry["id"])
        pobj, pres = fetch_json(url, timeout=120)
        manifest.append(pres.provenance(
            note=f"NWS AFD text {entry['id']} issued {entry.get('issuance_utc')}"))
        rec = {**entry, "fetched_utc": pres.retrieved_utc, "http_status": pres.status,
               "ok": bool(pres.ok), "sha256": pres.sha256, "bytes": pres.size,
               "quotes": [], "keyword_counts": None}
        if not pres.ok or not isinstance(pobj, dict):
            rec["error"] = pres.error or f"HTTP {pres.status}"
            note("warning", "One NWS Area Forecast Discussion could not be downloaded.",
                 {"url": url, "status": pres.status})
        else:
            # productText arrives as a JSON string; the only normalisation it
            # needs is dropping any character the source could not represent, so
            # a lost glyph is recorded instead of published as U+FFFD.
            raw, removed, contexts = fetchlib.strip_unrepresentable(
                pobj.get("productText") or "")
            rec["characters_removed"] = removed
            if removed:
                rec["removal_contexts"] = contexts
            if not collapse(raw):
                rec["ok"] = False
                rec["error"] = "product downloaded but carried no productText"
                note("warning",
                     "An NWS Area Forecast Discussion product returned no text, so no "
                     "quotes are published from it.",
                     {"url": url})
            else:
                room = max(0, MAX_QUOTES_TOTAL - total_quotes)
                quotes = extract_quotes(raw, limit=min(MAX_QUOTES_PER_PRODUCT, room))
                source = collapse(normalise_lines(raw))
                quotes = [q for q in quotes if q in source]     # belt and braces
                rec["quotes"] = [{"text": q, "keywords": keyword_hits(q)} for q in quotes]
                rec["keyword_counts"] = count_keywords(raw)
                # hash of the decoded discussion text, so a reviewer can confirm
                # the quotes came from this exact body and not from a re-typed copy
                rec["text_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                rec["text_chars"] = len(raw)
                # the discussion is an official public document and it is the
                # evidence for every quote above, so it is stored with them:
                # verify_claims.py re-checks each quote as a substring of this
                # text without fetching NOAA again.
                rec["text"] = raw
                total_quotes += len(quotes)
        products.append(rec)

    out = {
        "generated_utc": fetchlib.iso_utc(),
        "source": "National Weather Service Area Forecast Discussion (official product)",
        "nws_office": OFFICE,
        "list_url": LIST_URL,
        "warning": WARNING,
        "not_a_numeric_forecast": True,
        "merged_into_scoreboard": False,
        "window_note": (
            "The NWS products API lists the office's recent issues only, so this "
            "history covers the discussions currently published by NOAA - it is not a "
            "multi-year archive, and the gap is recorded rather than filled with "
            "second-hand text."),
        "counts": {
            "issuances_listed": len(issuances),
            "discussions_downloaded": len(products),
            "discussions_with_text": sum(1 for p in products if p.get("quotes") is not None
                                         and p.get("ok") and not p.get("error")),
            "verbatim_quotes": total_quotes,
        },
        "earliest_issuance_utc": next((p.get("issuance_utc") for p in reversed(issuances)
                                       if p.get("issuance_utc")), None),
        "latest_issuance_utc": next((p.get("issuance_utc") for p in issuances
                                     if p.get("issuance_utc")), None),
        "products": products,
        "all_issuances": issuances,
        "irregularities": irregularities,
    }
    return out, manifest


def write_outputs(out, manifest, datadir=Path("data")):
    datadir = Path(datadir)
    datadir.mkdir(parents=True, exist_ok=True)
    (datadir / "afd_history.json").write_text(json.dumps(out, indent=2) + "\n")
    provlib.write_manifest(datadir, "afd_history", manifest, out["generated_utc"],
                           "Fetches made by pipeline/afd_history.py (NWS Area Forecast "
                           "Discussion text; official prose product, not a numeric forecast).")
    provlib.merge_irregularities(datadir, "afd_history", out["irregularities"])
    return datadir / "afd_history.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datadir", default="data")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--limit", type=int, default=MAX_TEXTS)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        import selftest_afd_history
        return selftest_afd_history.run()

    out, manifest = build(datadir=Path(args.datadir), limit=args.limit)
    path = write_outputs(out, manifest, Path(args.outdir or args.datadir))
    c = out["counts"]
    log(f"AFD history: {c['issuances_listed']} issuances listed, "
        f"{c['discussions_downloaded']} downloaded, {c['verbatim_quotes']} verbatim quotes")
    log(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
