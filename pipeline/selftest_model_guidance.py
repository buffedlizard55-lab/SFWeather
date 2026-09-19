#!/usr/bin/env python3
"""Offline self-test for the model-guidance tier.

The tier's risks are specific: a model image being read as an official forecast,
a month range being invented from a filename, a quote being paraphrased instead
of copied, and a broken link being published because a probe 404'd.  Each of
those is asserted here against synthetic NOAA-shaped pages, including a page
served in CP1252 so the decoding path is exercised too.

Writes only into temporary directories; touches no network.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model_guidance as mg  # noqa: E402

CHECKS = []
PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

DESCRIPTION_HTML = """<html><body>
<p>NMME ensemble contains 79 members, all weighted equally.</p>
<p>A/B/N [Above/Below/Neutral] are terciles.</p>
<p>* A and B contours show when one class has &gt;38% of ensemble members, and the
opposite class is below 33%.</p>
<p>* White areas show where no one class is dominant: either all terciles are under
38%, or both A and B are over 38%.</p>
<p>The tercile limits were determined separately for each model using the NMME
hindcasts (1982-2010). For precipitation, thresholds were determined by ranking
all hindcasts and taking the \u201c66th and 33rd percentiles.\u201d</p>
</body></html>"""

INDEX_HTML = """<html><body>
<h3>For: October 2026 - April 2027</h3>
<a href="https://www.cpc.ncep.noaa.gov/products/NMME/prob/usPROBprate.S.html">Precipitation Rate</a>
</body></html>"""

PRATE_HTML = """<html><body><table>
<td><a href="https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/prob_ensemble_prate_us_season1.png">season 1</a>
<a href="https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/th.prob_ensemble_prate_us_season1.png"><img></a></td>
<td><a href="https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/prob_ensemble_prate_us_season2.png">season 2</a></td>
</table></body></html>"""

TEMP_HTML = PRATE_HTML.replace("prate", "tmp2m")

ARCHIVE_HTML = """<html><body><table>
<a href="https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800">September 2026 to March 2027</a>
<a href="https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026070800">August 2026 to February 2027</a>
</table></body></html>"""


class _Res:
    def __init__(self, url, body=None, status=200):
        self.url = url
        self.body = body
        self.ok = body is not None and 200 <= status < 300
        self.status = status if body is not None else 404
        self.error = None if self.ok else f"HTTP {self.status}"
        self.content_type = None
        self.elapsed = 0.0
        self.retrieved_utc = "2026-09-18T00:00:00Z"

    @property
    def size(self):
        return len(self.body) if self.body else 0

    @property
    def sha256(self):
        import hashlib
        return hashlib.sha256(self.body).hexdigest() if self.body else None

    def text(self, encoding="utf-8", errors="replace"):
        return self.body.decode(encoding, errors) if self.body else ""

    def provenance(self, note=None, **extra):
        rec = {"url": self.url, "http_status": self.status, "ok": self.ok,
               "bytes": self.size, "sha256": self.sha256,
               "retrieved_utc": self.retrieved_utc, "note": note}
        rec.update(extra)
        return rec


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


def run():
    CHECKS.clear()
    files = {
        f"{mg.CPC}/probindex.shtml": INDEX_HTML.encode(),
        # served in CP1252 on purpose: the real page carries typographic quotes
        f"{mg.CPC}/NMME_PROB_descr.html": DESCRIPTION_HTML.encode("cp1252"),
        f"{mg.CPC}/prob/usPROBprate.S.html": PRATE_HTML.encode(),
        f"{mg.CPC}/prob/usPROBtmp2m.S.html": TEMP_HTML.encode(),
        f"{mg.CPC}/prob/rpss.probindex.html": b"<html>skill</html>",
        f"{mg.CPC}/verif/index.html": b"<html>verification</html>",
        "https://ftp.cpc.ncep.noaa.gov/NMME/archive/": ARCHIVE_HTML.encode(),
        "https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800":
            b"<html><a href='a.nc'>a.nc</a></html>",
        "https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/"
        "prob_ensemble_prate_us_season1.png": PNG,
        "https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/"
        "prob_ensemble_prate_us_season2.png": PNG,
        "https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/"
        "prob_ensemble_tmp2m_us_season1.png": PNG,
        "https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/"
        "prob_ensemble_tmp2m_us_season2.png": PNG,
        # NOMADS deliberately absent -> the probe must report it, not link it
    }

    def fake_fetch(url, timeout=120, **kw):
        return _Res(url, files.get(url), 200 if url in files else 404)

    tmp_assets = Path(tempfile.mkdtemp(prefix="mg_assets_"))
    tmp_data = Path(tempfile.mkdtemp(prefix="mg_data_"))
    out, manifest = mg.build(assetsdir=tmp_assets, datadir=tmp_data, fetch=fake_fetch)

    check("the top-level warning is present and says it is not an official forecast",
          "NOT AN OFFICIAL FORECAST" in out["warning"]
          and out["not_an_official_forecast"] is True,
          f"warning={out['warning'][:60]}")
    check("the file states it is not merged into the scoreboard, and names the check",
          out["merged_into_scoreboard"] is False
          and "model-guidance-isolation" in out["isolation_rule"],
          f"rule={out['isolation_rule'][:60]}")
    check("NOAA's own coverage range is quoted verbatim, not truncated at the first year",
          out["coverage_verbatim"] == "October 2026 - April 2027"
          and out["pages"]["prob_index"]["coverage_form"] == "range",
          f"coverage={out['coverage_verbatim']}")
    check("a single-month coverage line is also matched",
          mg.COVERAGE_MONTH_RE.search("For: October 2026").group(1) == "October 2026"
          and mg.COVERAGE_RANGE_RE.search("For: October 2026") is None,
          "single-month form")
    check("the CP1252 description page decoded with its own encoding",
          out["pages"]["description"]["text_encoding"] == "cp1252",
          f"encoding={out['pages']['description']['text_encoding']}")
    check("no character was lost in decoding (no U+FFFD published)",
          out["pages"]["description"]["characters_removed"] == 0
          and "\ufffd" not in json.dumps(out),
          f"removed={out['pages']['description']['characters_removed']}")
    sentences = out["pages"]["description"]["verbatim_sentences"]
    plain = mg.html_text_only(DESCRIPTION_HTML)
    check("definition sentences were extracted", len(sentences) >= 4,
          f"n={len(sentences)}")
    check("every extracted sentence is a verbatim substring of the fetched page",
          all(mg.collapse(s) in mg.collapse(plain) for s in sentences),
          f"first={sentences[0][:70] if sentences else None}")
    check("the tercile-definition sentence is among them",
          any("are terciles" in s for s in sentences),
          f"sentences={sentences}")
    check("the hindcast/tercile-limit sentence is among them",
          any("tercile limits were determined" in s for s in sentences),
          "present")
    check("four seasonal images were archived with a hash and a local path",
          out["counts"]["images_archived"] == 4
          and all(Path(i["local_path"]).exists() for i in out["images"]
                  if i.get("local_path")),
          f"n={out['counts']['images_archived']}")
    check("thumbnails are not archived twice alongside the full image",
          not any("/images/th." in (i.get("url") or "") for i in out["images"]),
          f"urls={[i['url'].split('/')[-1] for i in out['images']]}")
    check("every image carries its own warning",
          all("not an official forecast" in (i.get("warning") or "").lower()
              for i in out["images"]),
          "per-item warning")
    check("no image asserts a month range derived from its filename",
          all("does not re-derive it from the filename" in (i.get("season_mapping_note") or "")
              for i in out["images"]),
          "season mapping note")
    check("an unreachable probe is reported and not published as a working link",
          any(p["key"] == "nomads_cfs_prod" and p["ok"] is False
              and p.get("http_status") == 404 for p in out["probes"])
          and any("not reachable" in i["message"] for i in out["irregularities"]),
          f"probes={[(p['key'], p['ok']) for p in out['probes']]}")
    check("the archive probe records that nothing was decoded",
          all(p.get("decoded") is False for p in out["probes"]),
          "decoded flag")
    check("the newest archived run is resolved from the archive page itself",
          any(p["key"] == "nmme_archive_latest"
              and p.get("url") == "https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800"
              for p in out["probes"]),
          f"urls={[p.get('url') for p in out['probes']]}")
    check("the archived run's coverage label is NOAA's own text",
          (out["pages"]["archive"]["archived_runs"][0]["coverage_label"]
           == "September 2026 to March 2027"),
          f"label={out['pages']['archive']['archived_runs'][0]['coverage_label']}")
    check("every successful fetch in the manifest carries a hash and a size",
          all(e.get("sha256") and e.get("bytes") for e in manifest if e.get("ok")),
          f"manifest={len(manifest)}")
    check("the quoted pages keep their full fetched text so the ledger can re-check quotes",
          all(mg.collapse(sent) in mg.collapse(out["pages"]["description"]["plain_text"])
              for sent in sentences)
          and (out["coverage_verbatim"]
               in out["pages"]["prob_index"]["plain_text"]),
          "plain_text evidence")
    check("the tier lists what it refuses to do",
          len(out["what_this_tier_does_not_do"]) >= 4, "list present")

    # writing must produce the manifest and merge irregularities idempotently
    (tmp_data / "quality_report.json").write_text(json.dumps(
        {"generated_utc": "x", "counts": {}, "irregularities": [
            {"severity": "info", "area": "nws", "message": "unrelated"}]}))
    path = mg.write_outputs(out, manifest, tmp_data)
    check("write_outputs produced the dataset file", path.exists(), str(path))
    rep = json.loads((tmp_data / "quality_report.json").read_text())
    tagged = [i for i in rep["irregularities"] if i.get("source") == "model_guidance"]
    check("irregularities merged into the quality report under a tag",
          len(tagged) == len(out["irregularities"])
          and any(i["message"] == "unrelated" for i in rep["irregularities"]),
          f"tagged={len(tagged)}")
    mg.write_outputs(out, manifest, tmp_data)
    rep2 = json.loads((tmp_data / "quality_report.json").read_text())
    check("merging twice does not double-count a finding",
          len([i for i in rep2["irregularities"] if i.get("source") == "model_guidance"])
          == len(tagged),
          f"n={len(rep2['irregularities'])}")
    check("quality-report counts are recomputed from the entries",
          rep2["counts"]["total"] == len(rep2["irregularities"]),
          f"counts={rep2['counts']}")

    # ---- markup shapes NOAA actually serves --------------------------------
    # The first live run fetched every page with HTTP 200 and still archived
    # zero maps and zero run directories, because the patterns required an
    # absolute href in double quotes with the label sitting bare between ">" and
    # "<".  Each shape below is one the live pages can present; all must parse.
    PRATE_PAGE = "https://www.cpc.ncep.noaa.gov/products/NMME/prob/usPROBprate.S.html"
    ARCHIVE_PAGE = "https://ftp.cpc.ncep.noaa.gov/NMME/archive/"
    shapes = {
        "relative hrefs": (
            """<td><a href="images/prob_ensemble_prate_us_season1.png">season 1</a>"""
            """<a href="images/th.prob_ensemble_prate_us_season1.png"><img></a></td>""",
            """<a href="2026080800/">September 2026 to March 2027</a>"""),
        "single-quoted attributes": (
            """<td><a href='https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/"""
            """prob_ensemble_prate_us_season1.png'>season 1</a></td>""",
            """<a href='https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800'>"""
            """September 2026 to March 2027</a>"""),
        "unquoted attributes": (
            """<td><a href=https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/"""
            """prob_ensemble_prate_us_season1.png>season 1</a></td>""",
            """<a href=https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800>"""
            """September 2026 to March 2027</a>"""),
        "labels wrapped in nested tags": (
            """<td><a href="images/prob_ensemble_prate_us_season1.png">"""
            """<font face="Arial"><b>season 1</b></font></a></td>""",
            """<a href="https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800">"""
            """<font face="Arial" size="2">September 2026 to March 2027</font></a>"""),
    }
    for shape, (prate_body, archive_body) in shapes.items():
        files3 = dict(files)
        files3[PRATE_PAGE] = ("<html><body><table>" + prate_body + "</table></body></html>"
                              ).encode()
        files3[ARCHIVE_PAGE] = ("<html><body><table>" + archive_body
                                + "</table></body></html>").encode()
        # The probe must fetch the directory URL exactly as NOAA's listing links
        # it - this project publishes NOAA's own link, not a normalised guess -
        # so the fixture serves both the slashed and the unslashed form.
        for run_url in ("https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800",
                        "https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800/"):
            files3[run_url] = b"<html><a href='a.nc'>a.nc</a></html>"

        def fake_fetch3(url, timeout=120, **kw):
            return _Res(url, files3.get(url), 200 if url in files3 else 404)

        tmp_assets3 = Path(tempfile.mkdtemp(prefix="mg_assets3_"))
        tmp_data3 = Path(tempfile.mkdtemp(prefix="mg_data3_"))
        out3, _m3 = mg.build(assetsdir=tmp_assets3, datadir=tmp_data3, fetch=fake_fetch3)
        seen = out3["pages"]["seasonal_prcp"].get("image_urls") or []
        prate_imgs = [u for u in seen if "/images/th." not in u
                      and u.endswith("prob_ensemble_prate_us_season1.png")]
        check(f"{shape}: a relative or differently quoted map link is still recognised",
              len(prate_imgs) == 1
              and prate_imgs[0] == ("https://www.cpc.ncep.noaa.gov/products/NMME/prob/"
                                    "images/prob_ensemble_prate_us_season1.png"),
              f"image_urls={seen}")
        check(f"{shape}: only the full map is archived, never its thumbnail",
              not [i for i in out3["images"] if "/images/th." in (i.get("url") or "")],
              f"urls={[i.get('url') for i in out3['images']]}")
        check(f"{shape}: the map was actually archived and hashed",
              any(i.get("variable_key") == "prate" and i.get("season_index") == 1
                  and i.get("ok") is True and i.get("sha256") and i.get("local_path")
                  for i in out3["images"]),
              f"images={[(i.get('variable_key'), i.get('season_index'), i.get('ok')) for i in out3['images']]}")
        runs3 = out3["pages"]["archive"].get("archived_runs") or []
        check(f"{shape}: an archive run directory is recognised and its label kept",
              len(runs3) == 1 and runs3[0]["run_id"] == "2026080800"
              and runs3[0]["coverage_label"] == "September 2026 to March 2027",
              f"runs={runs3}")
        check(f"{shape}: the newest archived run is probed from the listing",
              any(p["key"] == "nmme_archive_latest" and p.get("ok") is True
                  and (p.get("url") or "").rstrip("/").endswith("2026080800")
                  for p in out3["probes"]),
              f"probes={[(p['key'], p.get('ok'), p.get('url')) for p in out3['probes']]}")
        shutil.rmtree(tmp_assets3, ignore_errors=True)
        shutil.rmtree(tmp_data3, ignore_errors=True)

    # ---- a page that yields nothing must be diagnosable from the data -------
    files4 = dict(files)
    files4["https://ftp.cpc.ncep.noaa.gov/NMME/archive/"] = (
        b"<html><body><p> NOAA has moved this index. </p></body></html>")

    def fake_fetch4(url, timeout=120, **kw):
        return _Res(url, files4.get(url), 200 if url in files4 else 404)

    tmp_assets4 = Path(tempfile.mkdtemp(prefix="mg_assets4_"))
    tmp_data4 = Path(tempfile.mkdtemp(prefix="mg_data4_"))
    out4, _m4 = mg.build(assetsdir=tmp_assets4, datadir=tmp_data4, fetch=fake_fetch4)
    arch4 = out4["pages"]["archive"]
    check("a page that parses to nothing keeps a bounded markup excerpt for diagnosis",
          arch4.get("n_archived_runs_listed") == 0 and bool(arch4.get("markup_excerpt"))
          and len(arch4["markup_excerpt"]) <= 700,
          f"excerpt={str(arch4.get('markup_excerpt'))[:80]}")
    check("a page that parses to nothing says so as an irregularity, not as silence",
          any(i["area"] == "model_guidance" and "no run directory was recognised" in i["message"]
              for i in out4["irregularities"]),
          f"irregularities={[i['message'][:60] for i in out4['irregularities']][:3]}")
    shutil.rmtree(tmp_assets4, ignore_errors=True)
    shutil.rmtree(tmp_data4, ignore_errors=True)

    # ---- the failure the first live CI run found ---------------------------
    # On 19 Sep 2026 the nightly run published a raw-archive probe with
    # ok=false and *no* error field, because the archive page had listed no run
    # directories.  The ledger failed the build (model-guidance-links-fetched:
    # "1 guidance item(s) that failed to fetch publish no error").  A probe that
    # could not run must say why, and must distinguish "NOAA was unreachable"
    # from "this project stopped understanding NOAA's page".
    for label, archive_body, expect_fragment in (
            ("lists no run directories", b"<html><body><table></table></body></html>",
             "listed no run directories"),
            ("is unreachable", None, "could not be retrieved")):
        files2 = dict(files)
        if archive_body is None:
            files2.pop("https://ftp.cpc.ncep.noaa.gov/NMME/archive/", None)
        else:
            files2["https://ftp.cpc.ncep.noaa.gov/NMME/archive/"] = archive_body

        def fake_fetch2(url, timeout=120, **kw):
            return _Res(url, files2.get(url), 200 if url in files2 else 404)

        tmp_assets2 = Path(tempfile.mkdtemp(prefix="mg_assets2_"))
        tmp_data2 = Path(tempfile.mkdtemp(prefix="mg_data2_"))
        out2, _m2 = mg.build(assetsdir=tmp_assets2, datadir=tmp_data2, fetch=fake_fetch2)
        skipped = [pr for pr in out2["probes"]
                   if pr["key"] == "nmme_archive_latest" and pr.get("ok") is False]
        check(f"a raw-archive probe skipped because the page {label} publishes its reason",
              len(skipped) == 1 and bool(skipped[0].get("error"))
              and expect_fragment in skipped[0]["error"],
              f"error={str(skipped[0].get('error'))[:120] if skipped else 'no skipped probe'}")
        check(f"an archive probe skipped because the page {label} raises an irregularity",
              any(i["area"] == "model_guidance" and "not probed" in i["message"]
                  for i in out2["irregularities"]),
              f"irregularities={[i['message'][:60] for i in out2['irregularities']][:3]}")
        check(f"no guidance item is ok=false without an error ({label})",
              not [i for i in ([pg for pg in out2["pages"].values() if isinstance(pg, dict)]
                               + list(out2["images"]) + list(out2["probes"]))
                   if i.get("ok") is False and not i.get("error")],
              "every undisclosed failure is the ledger's model-guidance-links-fetched case")
        shutil.rmtree(tmp_assets2, ignore_errors=True)
        shutil.rmtree(tmp_data2, ignore_errors=True)

    shutil.rmtree(tmp_assets, ignore_errors=True)
    shutil.rmtree(tmp_data, ignore_errors=True)

    failed = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f"  :: {detail}" if not ok else ""))
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} model-guidance self-checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
