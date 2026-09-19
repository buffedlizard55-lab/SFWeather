#!/usr/bin/env python3
"""Offline self-test for the NWS Area Forecast Discussion history.

The failure mode this guards against is prose turning into data: a paraphrase
published as a quote, a heading glued onto a sentence, or a discussion being
read as a numeric forecast.  Also covered: a list endpoint that 404s, a product
that returns no text, and the manifest/irregularity bookkeeping.

Touches no network and writes only into temporary directories.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import afd_history as afd  # noqa: E402

CHECKS = []

AFD_TEXT = """\r
Area Forecast Discussion\r
National Weather Service San Francisco CA\r
323 AM PDT Thu Sep 18 2026\r
\r
.SYNOPSIS...\r
Dry conditions will persist through the weekend as a ridge builds offshore of\r
the California coast.\r
\r
.SHORT TERM... /Today through Friday/...\r
A weak front will bring periods of rain Thursday night into Friday, with\r
rainfall totals of a quarter to a half inch possible across the coastal ranges.\r
Gusty southwest winds of 20 to 30 mph will accompany the front, with gusts to\r
40 mph along the coast Friday morning. Rain and wind arriving together could\r
produce localized ponding on streets that drain poorly.\r
\r
.LONG TERM... /Saturday through Wednesday/...\r
Models keep the pattern dry Saturday and Sunday. Confidence is low for the\r
middle of next week.\r
"""


class _Res:
    def __init__(self, url, ok=True, status=200, body=b'{"productText": "..."}'):
        self.url = url
        self.ok = ok
        self.status = status
        self.body = body if ok else None
        self.error = None if ok else f"HTTP {status}"
        self.content_type = "application/json"
        self.elapsed = 0.0
        self.retrieved_utc = "2026-09-18T04:00:00Z"

    @property
    def size(self):
        return len(self.body) if self.body else 0

    @property
    def sha256(self):
        return hashlib.sha256(self.body).hexdigest() if self.body else None

    def provenance(self, note=None, **extra):
        rec = {"url": self.url, "http_status": self.status, "ok": self.ok,
               "bytes": self.size, "sha256": self.sha256,
               "retrieved_utc": self.retrieved_utc, "note": note}
        rec.update(extra)
        return rec


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


def fake_factory(list_ok=True, products=None, texts=None):
    products = products if products is not None else [
        {"id": "aaa", "@id": "https://api.weather.gov/products/aaa",
         "issuanceTime": "2026-09-18T10:23:00+00:00", "productName": "Area Forecast Discussion"},
        {"id": "bbb", "@id": "https://api.weather.gov/products/bbb",
         "issuanceTime": "2026-09-17T22:11:00+00:00", "productName": "Area Forecast Discussion"},
    ]
    texts = texts if texts is not None else {"aaa": AFD_TEXT, "bbb": AFD_TEXT}

    def fetch_json(url, timeout=120, **kw):
        if url == afd.LIST_URL:
            if not list_ok:
                return None, _Res(url, ok=False, status=404)
            return {"@graph": products}, _Res(url, body=json.dumps({"@graph": products}).encode())
        pid = url.rstrip("/").split("/")[-1]
        if pid not in texts:
            return None, _Res(url, ok=False, status=404)
        body = json.dumps({"productText": texts[pid]}).encode()
        return json.loads(body), _Res(url, body=body)

    return fetch_json


def run():
    CHECKS.clear()

    # ---- quote extraction -------------------------------------------------
    quotes = afd.extract_quotes(AFD_TEXT)
    source = afd.collapse(afd.normalise_lines(AFD_TEXT))
    check("quotes were extracted from a realistic AFD body", len(quotes) >= 3,
          f"n={len(quotes)}: {quotes[:2]}")
    check("every quote is a verbatim substring of the fetched text",
          all(q in source for q in quotes),
          f"first={quotes[0][:80] if quotes else None}")
    check("a paraphrase of a real sentence is never returned",
          "Rain and wind arriving together could produce flooding." not in quotes
          and all(q == afd.collapse(q) for q in quotes),
          f"quotes={quotes}")
    check("the rain+wind-together sentence was captured",
          any("Rain and wind arriving together" in q for q in quotes),
          f"quotes={quotes}")
    check("the gust sentence was captured with a wind keyword",
          any("gusts to 40 mph" in q and "wind" in afd.keyword_hits(q) for q in quotes),
          f"quotes={quotes}")
    check("an all-caps section heading never becomes part of a quote",
          not any(q.startswith(("SHORT TERM", "LONG TERM", "SYNOPSIS"))
                  or "/Today through Friday/" in q for q in quotes),
          f"quotes={[q[:40] for q in quotes]}")
    check("CRLF line wrapping is folded, so a quote is one readable sentence",
          all("\n" not in q and "  " not in q for q in quotes), "whitespace")
    counts = afd.count_keywords(AFD_TEXT)
    check("keyword counts are computed for each topic in the brief",
          counts["rain"] >= 2 and counts["wind"] >= 2 and counts["storm"] >= 1
          and counts["dry"] >= 2 and set(counts) == set(afd.KEYWORDS),
          f"counts={counts}")
    check("the per-product quote limit is honoured",
          len(afd.extract_quotes(AFD_TEXT * 4, limit=2)) == 2, "limit")

    # ---- build: happy path ------------------------------------------------
    out, manifest = afd.build(fetch_json=fake_factory())
    check("the warning states it is prose, not a numeric forecast",
          out["not_a_numeric_forecast"] is True
          and out["merged_into_scoreboard"] is False
          and "not a numeric forecast" in out["warning"].lower(),
          f"warning={out['warning'][:60]}")
    check("both discussions were downloaded and quoted",
          out["counts"]["issuances_listed"] == 2
          and out["counts"]["discussions_downloaded"] == 2
          and out["counts"]["verbatim_quotes"] == 2 * len(quotes),
          f"counts={out['counts']}")
    check("issuance window is taken from the API's own timestamps",
          out["latest_issuance_utc"] == "2026-09-18T10:23:00+00:00"
          and out["earliest_issuance_utc"] == "2026-09-17T22:11:00+00:00",
          f"latest={out['latest_issuance_utc']} earliest={out['earliest_issuance_utc']}")
    check("each quote carries its keywords and each product its official URL",
          all(q["keywords"] for p in out["products"] for q in p["quotes"])
          and all(p["url"] == f"https://api.weather.gov/products/{p['id']}"
                  for p in out["products"]),
          "urls/keywords")
    check("each product records a hash of the text the quotes came from",
          all(p.get("text_sha256") == hashlib.sha256(AFD_TEXT.encode()).hexdigest()
              for p in out["products"]),
          f"sha={[p.get('text_sha256') for p in out['products']][:1]}")
    check("each product keeps the text its quotes came from, hashed",
          all(p.get("text") == AFD_TEXT
              and p.get("text_sha256") == hashlib.sha256(AFD_TEXT.encode()).hexdigest()
              for p in out["products"])
          and all(q["text"] in afd.collapse(afd.normalise_lines(p["text"]))
                  for p in out["products"] for q in p["quotes"]),
          "stored text is the quote evidence")
    check("every fetch in the manifest carries a hash and status",
          len(manifest) == 3 and all(m.get("sha256") and m.get("http_status") == 200
                                     for m in manifest),
          f"manifest={len(manifest)}")
    check("no irregularity is raised on a clean run", out["irregularities"] == [],
          f"{out['irregularities']}")
    check("the total quote cap is enforced across products",
          afd.build(fetch_json=fake_factory(
              texts={str(i): AFD_TEXT for i in range(20)},
              products=[{"id": str(i),
                         "issuanceTime": f"2026-09-{10 + (i % 9):02d}T00:00:00+00:00"}
                        for i in range(20)],
          ), limit=20)[0]["counts"]["verbatim_quotes"] <= afd.MAX_QUOTES_TOTAL,
          "cap")

    # ---- build: list endpoint unavailable ---------------------------------
    out2, man2 = afd.build(fetch_json=fake_factory(list_ok=False))
    check("an unreachable AFD list does not crash the run",
          out2["counts"]["verbatim_quotes"] == 0 and out2["products"] == [],
          f"counts={out2['counts']}")
    check("an unreachable AFD list is flagged as a warning, never an error",
          len(out2["irregularities"]) == 1
          and out2["irregularities"][0]["severity"] == "warning"
          and out2["irregularities"][0]["evidence"]["status"] == 404,
          f"{out2['irregularities']}")
    check("the flag says the forecast numbers are unaffected",
          "unaffected" in out2["irregularities"][0]["message"], "message text")

    # ---- build: product with no text --------------------------------------
    out3, _ = afd.build(fetch_json=fake_factory(texts={"aaa": "   ", "bbb": AFD_TEXT}))
    empty = next(p for p in out3["products"] if p["id"] == "aaa")
    check("a product with no text is marked unusable instead of quoted",
          empty["quotes"] == [] and empty["ok"] is False
          and "no productText" in (empty.get("error") or ""),
          f"{empty.get('error')}")
    check("a product with no text raises a reviewable warning",
          any(i["severity"] == "warning" and "returned no text" in i["message"]
              for i in out3["irregularities"]),
          f"{out3['irregularities']}")
    check("the usable discussion still contributes its quotes",
          out3["counts"]["verbatim_quotes"] == len(quotes),
          f"counts={out3['counts']}")

    # ---- outputs ----------------------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="afd_"))
    (tmp / "quality_report.json").write_text(json.dumps(
        {"generated_utc": "x", "counts": {}, "irregularities": [
            {"severity": "info", "area": "cpc", "message": "kept"}]}))
    path = afd.write_outputs(out2, man2, tmp)
    check("write_outputs wrote the dataset", path.exists(), str(path))
    rep = json.loads((tmp / "quality_report.json").read_text())
    check("irregularities merged under a source tag without dropping others",
          len([i for i in rep["irregularities"] if i.get("source") == "afd_history"]) == 1
          and any(i["message"] == "kept" for i in rep["irregularities"]),
          f"{rep['irregularities']}")
    check("a separate provenance manifest was written for this module",
          (tmp / "afd_history_provenance.json").exists(), "manifest file")
    shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f"  :: {detail}" if not ok else ""))
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} AFD-history self-checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
