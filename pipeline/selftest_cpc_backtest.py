#!/usr/bin/env python3
"""Offline self-test for the CPC back-test: synthetic archive, hand-computed answer.

The back-test's whole value is its arithmetic - tercile cuts, a hit, a miss, an
'EC is not a tilt' rule, an incomplete season that must not be scored.  None of
that can be checked against a live NOAA fetch in a test, and a test that only
checks that the code *runs* would pass even if every number it produced were
wrong.

So this module builds a synthetic CPC issuance archive - a real ESRI shapefile
and DBF, written byte by byte here and read back by the project's own
``lib_shape`` reader - plus a synthetic GHCN-Daily station file whose season
totals are exact by construction, injects them through the same ``fetch`` seam
the real script uses, and asserts the result equals a number computed by hand in
the comments below.

Run: ``python3 pipeline/cpc_backtest.py --selftest``  (or ``import`` from tests).
Writes nothing; touches no network.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib_fetch as fetchlib          # noqa: E402
import cpc_backtest as bt             # noqa: E402

# --------------------------------------------------------------------------
# a minimal ESRI shapefile / DBF writer
# --------------------------------------------------------------------------

PRJ_GEOGRAPHIC = (
    'GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",'
    'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]]'
)


def shp_bytes(polygons):
    """Serialise ``[[ (lon, lat), ... ]]`` as a Polygon (type 5) shapefile."""
    records = []
    for ring in polygons:
        npoints = len(ring)
        nparts = 1
        content = struct.pack("<i", 5)
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        content += struct.pack("<4d", min(xs), min(ys), max(xs), max(ys))
        content += struct.pack("<2i", nparts, npoints)
        content += struct.pack("<i", 0)
        content += struct.pack(f"<{2 * npoints}d",
                               *[c for p in ring for c in (p[0], p[1])])
        records.append(content)

    body = b""
    for i, content in enumerate(records, start=1):
        body += struct.pack(">2i", i, len(content) // 2) + content

    all_x = [p[0] for r in polygons for p in r]
    all_y = [p[1] for r in polygons for p in r]
    header = struct.pack(">i", 9994) + b"\x00" * 20
    header += struct.pack(">i", (100 + len(body)) // 2)
    header += struct.pack("<i", 1000)
    header += struct.pack("<i", 5)
    header += struct.pack("<8d", min(all_x), min(all_y), max(all_x), max(all_y),
                          0.0, 0.0, 0.0, 0.0)
    return header + body


def dbf_bytes(fields, rows):
    """Serialise a dBASE III table.  ``fields`` = ``[(name, type, len, dec)]``."""
    nrec = len(rows)
    hdr_len = 32 + 32 * len(fields) + 1
    rec_len = 1 + sum(f[2] for f in fields)
    out = bytearray()
    out += struct.pack("<BBBB", 0x03, 126, 1, 1)
    out += struct.pack("<IHH", nrec, hdr_len, rec_len)
    out += b"\x00" * 20
    for name, ftype, flen, fdec in fields:
        out += name.encode("ascii")[:11].ljust(11, b"\x00")
        out += ftype.encode("ascii")
        out += b"\x00" * 4
        out += struct.pack("<BB", flen, fdec)
        out += b"\x00" * 14
    out += b"\x0D"
    for row in rows:
        rec = bytearray(b" ")
        for (name, ftype, flen, fdec), value in zip(fields, row):
            if value is None:
                text = ""
            elif ftype in ("N", "F"):
                text = f"{value:.{fdec}f}" if fdec else str(int(value))
            else:
                text = str(value)
            rec += text.encode("ascii", "replace")[:flen].ljust(flen, b" ")
        out += bytes(rec)
    out += b"\x1A"
    return bytes(out)


def cpc_zip_bytes(leads, ring=None):
    """Build a synthetic ``seasprcp_YYYYMM.zip`` in memory.

    ``leads`` is a list of ``(stem, valid_season, category, probability,
    fcst_date)`` tuples - one shapefile bundle each, exactly the layout CPC
    ships (``lead1_OND_prcp.shp`` ... ``lead14_Sep_prcp.shp``).
    """
    ring = ring or [(-125.0, 35.0), (-120.0, 35.0), (-120.0, 40.0),
                    (-125.0, 40.0), (-125.0, 35.0)]
    # Valid_Seas must hold CPC's longest real label ("NDJ 2026-2027", 13 chars);
    # 12 truncated it to "NDJ 2026-202" and the season silently failed to parse.
    fields = [("Fcst_Date", "C", 8, 0), ("Valid_Seas", "C", 16, 0),
              ("Prob", "N", 5, 1), ("Cat", "C", 6, 0)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for stem, valid_season, cat, prob, fcst_date in leads:
            zf.writestr(f"{stem}.shp", shp_bytes([ring]))
            zf.writestr(f"{stem}.dbf",
                        dbf_bytes(fields, [(fcst_date, valid_season, prob, cat)]))
            zf.writestr(f"{stem}.prj", PRJ_GEOGRAPHIC)
            zf.writestr(f"{stem}.shx", b"\x00" * 108)
    return buf.getvalue()


def index_html(months):
    """A stand-in for CPC's seasonal GIS index page, carrying the same hrefs."""
    links = "".join(
        f'<a href="https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/seasprcp_{ym}.zip">'
        f'{ym}</a>'
        f'<a href="https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/seastemp_{ym}.zip">'
        f'{ym}</a>'
        for ym in months)
    return ("<html><body><table>" + links + "</table></body></html>").encode()


# --------------------------------------------------------------------------
# a synthetic GHCN-Daily station file whose season totals are exact
# --------------------------------------------------------------------------

#: 1 inch = 254 tenths of a millimetre, so a day carrying ``total_in * 254``
#: tenths reproduces ``total_in`` exactly when the parser converts back.
TENTHS_MM_PER_INCH = 254


def ghcn_csv(station_id, ond_totals, mam_totals,
             temp_tmax_tenths_c=200, temp_tmin_tenths_c=100,
             first_year=1991, last_year=2026):
    """Wide-format GHCN-Daily CSV.

    All of each season's rain is placed on the first day of the season, so the
    period total is exact and hand-checkable; every other day is 0.
    """
    def put(date_iso, inches):
        rows[date_iso] = int(round(inches * TENTHS_MM_PER_INCH))

    rows = {}
    for year, total in sorted(ond_totals.items()):
        put(f"{year}-10-01", total)
    for year, total in sorted(mam_totals.items()):
        put(f"{year}-03-01", total)

    lines = ['"STATION","DATE","LATITUDE","LONGITUDE","ELEVATION","NAME",'
             '"PRCP","TMAX","TMIN"']
    d = dt.date(first_year, 1, 1)
    end = dt.date(last_year, 12, 31)
    while d <= end:
        iso = d.isoformat()
        lines.append(f'"{station_id}","{iso}","37.7705","-122.4269","45.7",'
                     f'"SYNTHETIC STATION","{rows.get(iso, 0)}",'
                     f'"{temp_tmax_tenths_c}","{temp_tmin_tenths_c}"')
        d += dt.timedelta(days=1)
    return "\n".join(lines) + "\n"


class _Res:
    """A ``lib_fetch.FetchResult``-shaped stub built from bytes."""

    def __init__(self, url, body=None, status=200):
        self.url = url
        self.body = body
        self.ok = body is not None and 200 <= status < 300
        self.status = status if body is not None else 404
        self.error = None if self.ok else (f"HTTP {self.status}")
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


# --------------------------------------------------------------------------
# the self-test itself
# --------------------------------------------------------------------------

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


def run():
    """Build the synthetic world, run the back-test, verify the arithmetic."""
    CHECKS.clear()

    # ---- the synthetic observed record -----------------------------------
    # OND (Oct+Nov+Dec) totals for the 30 base seasons, in inches:
    #   1991 -> 0.5, 1992 -> 1.0, ... 2020 -> 15.0   (0.5 in steps)
    # Sorted, that is [0.5, 1.0, ..., 15.0].  climo.percentile is nearest-rank:
    #   p33.3 -> index round(0.3333*29) = 10 -> the 11th value = 5.5
    #   p66.7 -> index round(0.6667*29) = 19 -> the 20th value = 10.0
    # So: below < 5.5, normal 5.5..10.0, above > 10.0.
    ond_totals = {y: 0.5 * (y - 1991 + 1) for y in range(1991, 2021)}
    # MAM totals: descending, so the tercile cuts are the mirror image and a
    # "Below" call can be made to miss on purpose.
    #   1991 -> 15.0 ... 2020 -> 0.5  => cuts p33.3 = 5.5, p66.7 = 10.0 again.
    mam_totals = {y: 0.5 * (2020 - y + 1) for y in range(1991, 2021)}

    ond_2026_total = 12.0      # > 10.0  -> observed tercile "above"
    mam_2026_total = 11.0      # > 10.0  -> observed tercile "above"

    station = "SYNTH00000001"
    ond_totals[2026] = ond_2026_total
    mam_totals[2026] = mam_2026_total
    csv_bytes = ghcn_csv(station, ond_totals, mam_totals).encode()

    # ---- the synthetic CPC issuances -------------------------------------
    # 202609: lead1 = OND 2026 "Above" 50%  -> observed above  => HIT
    #         lead2 = NDJ 2026-2027 "Above" 45% -> Jan/Feb 2027 unobserved
    #                                             => not-yet-observable
    #         lead3 = DJF 2026-2027 "EC" 33%    => no-tilt (never a miss)
    zip_prate = cpc_zip_bytes([
        ("lead1_OND_prcp", "OND 2026", "Above", 50.0, "20260917"),
        ("lead2_NDJ_prcp", "NDJ 2026-2027", "Above", 45.0, "20260917"),
        ("lead3_DJF_prcp", "DJF 2026-2027", "EC", 33.0, "20260917"),
    ])
    # 202602: lead1 = MAM 2026 "Below" 45% -> observed above => MISS
    zip_early = cpc_zip_bytes([
        ("lead1_MAM_prcp", "MAM 2026", "Below", 45.0, "20260219"),
    ])
    # Temperature: a constant season, so the tercile arithmetic is exercised for
    # the second variable.  TMAX 20.0 C / TMIN 10.0 C -> daily mean 59.0 F for
    # every base season and for OND 2026 alike, so every base value ties and the
    # observed value lands in the middle third.
    zip_temp = cpc_zip_bytes([
        ("lead1_OND_temp", "OND 2026", "Normal", 33.0, "20260917"),
    ])

    files = {
        bt.CPC_SEASONAL_INDEX: index_html(["202609", "202602"]),
        f"{bt.CPC_GIS_BASE}/seasprcp_202609.zip": zip_prate,
        f"{bt.CPC_GIS_BASE}/seasprcp_202602.zip": zip_early,
        f"{bt.CPC_GIS_BASE}/seastemp_202609.zip": zip_temp,
        # 202602 temperature and 202601 anything: deliberately absent (404),
        # which is exactly what CPC's rolling retention window produces.
        f"{bt.GHCN_BASE}/{station}.csv": csv_bytes,
    }

    def fake_fetch(url, timeout=120, **kw):
        body = files.get(url)
        return _Res(url, body, 200 if body is not None else 404)

    # ---- a data directory with a verified centroid -----------------------
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="bt_selftest_"))
    (tmp / "run.json").write_text(json.dumps({
        "generated_utc": "2026-09-18T00:00:00Z",
        "target": {"zip": "94122", "centroid": {"lat": 37.760459,
                                                "lon": -122.483894,
                                                "verified": True}},
    }))
    (tmp / "climatology.json").write_text(json.dumps(
        {"meta": {"precip_station": {"id": station}}}))

    out, manifest = bt.build(datadir=tmp, fetch=fake_fetch,
                             today=dt.date(2026, 9, 18))

    # ---- what must be true -----------------------------------------------
    check("discovery read the two issuance months off the index page",
          out["discovery"].get("months") == ["202602", "202609"],
          f"months={out['discovery'].get('months')}")
    check("both precipitation issuances were sampled",
          out["counts"]["issuances_sampled"] == 3,
          f"sampled={out['counts']['issuances_sampled']} "
          f"(202609 prcp, 202602 prcp, 202609 temp)")
    check("issuances CPC does not serve are recorded as expected absences",
          out["counts"]["issuances_beyond_retention_window"] == 1,
          f"absent={out['counts']['issuances_beyond_retention_window']} "
          "(seastemp_202602)")
    check("no fetch was reported as a hard failure",
          out["counts"]["issuances_failed"] == 0,
          f"failed={out['counts']['issuances_failed']}")

    scored = {r["season"]: r for r in out["scored"] if r["variable"] == "prcp"}
    check("OND 2026 sampled from the synthetic archive",
          "OND 2026" in scored, f"seasons={sorted(scored)}")
    ond = scored.get("OND 2026", {})
    check("OND 2026 observed total is exactly 12.00 in",
          ond.get("observed_value") == 12.0,
          f"observed={ond.get('observed_value')}")
    check("OND 2026 tercile cuts are 5.5 and 10.0 (hand-computed)",
          (ond.get("tercile_low"), ond.get("tercile_high")) == (5.5, 10.0),
          f"cuts={ond.get('tercile_low')}/{ond.get('tercile_high')}")
    check("OND 2026 observed tercile is 'above'",
          ond.get("observed_tercile") == "above",
          f"tercile={ond.get('observed_tercile')}")
    check("OND 2026 'Above' 50% is a HIT", ond.get("hit") is True,
          f"hit={ond.get('hit')} status={ond.get('status')}")
    check("OND 2026 keeps the raw DBF row as evidence",
          (ond.get("used_nearest_polygon") is False) and ond.get("cpc_probability_pct") == 50.0,
          f"prob={ond.get('cpc_probability_pct')}")
    check("OND 2026 probability assigned to the verifying tercile is 50.0",
          ond.get("prob_of_verifying_tercile_pct") == 50.0,
          f"p={ond.get('prob_of_verifying_tercile_pct')}")

    mam = scored.get("MAM 2026", {})
    check("MAM 2026 'Below' 45% is a MISS (observed above)",
          mam.get("hit") is False and mam.get("observed_tercile") == "above",
          f"hit={mam.get('hit')} tercile={mam.get('observed_tercile')}")
    check("a miss records the probability CPC gave the verifying tercile "
          "(100-45)/2 = 27.5",
          mam.get("prob_of_verifying_tercile_pct") == 27.5,
          f"p={mam.get('prob_of_verifying_tercile_pct')}")

    ndj = scored.get("NDJ 2026-2027", {})
    check("NDJ 2026-2027 is not scored because it is not observable yet",
          ndj.get("status") == "not-yet-observable" and ndj.get("hit") is None,
          f"status={ndj.get('status')} reason={ndj.get('reason')}")
    djf = scored.get("DJF 2026-2027", {})
    check("an 'EC' polygon is counted as no-tilt, never as a miss",
          djf.get("status") == "no-tilt" and djf.get("hit") is None,
          f"status={djf.get('status')}")

    overall = (out.get("summary") or {}).get("overall") or {}
    prcp_block = (out["summary"]["by_variable"].get("prcp") or {})
    check("precipitation hit-rate is 1 of 2 = 50.0%",
          prcp_block.get("n_scored") == 2 and prcp_block.get("n_hits") == 1
          and prcp_block.get("hit_rate_pct") == 50.0,
          f"prcp={prcp_block}")
    check("both variables together: 3 scored, 2 hits = 66.7%",
          overall.get("n_scored") == 3 and overall.get("n_hits") == 2
          and overall.get("hit_rate_pct") == 66.7,
          f"overall={overall}")
    check("the baseline published next to the hit-rate is 33.3%",
          overall.get("baseline_pct") == 33.3, f"baseline={overall.get('baseline_pct')}")
    check("status counts: 3 scored, 1 no-tilt, 1 not-yet-observable",
          out["summary"]["by_status"].get("scored") == 3
          and out["summary"]["by_status"].get("no-tilt") == 1
          and out["summary"]["by_status"].get("not-yet-observable") == 1,
          f"by_status={out['summary']['by_status']}")
    check("the 'Below' category block shows 0 hits of 1",
          (out["summary"]["by_category"].get("Below") or {}).get("n_scored") == 1
          and (out["summary"]["by_category"].get("Below") or {}).get("n_hits") == 0,
          f"below={out['summary']['by_category'].get('Below')}")
    check("the tilt-only subset keeps the 50% and 45% calls and drops the 33% EC",
          out["summary"]["tilt_only"]["n_scored"] == 2,
          f"tilt={out['summary']['tilt_only']}")
    check("temperature pairs are scored separately from precipitation",
          (out["summary"]["by_variable"].get("temp") or {}).get("n_scored") == 1,
          f"temp={out['summary']['by_variable'].get('temp')}")
    temp_row = [r for r in out["scored"] if r["variable"] == "temp"]
    check("the temperature season verifies in the middle third (every base "
          "season ties at 59.0 F)",
          bool(temp_row) and temp_row[0].get("observed_tercile") == "normal"
          and temp_row[0].get("hit") is True,
          f"row={temp_row[0] if temp_row else None}")
    check("rainy-season pairs are listed for the Oct-Jan view",
          any(p["season"] == "OND 2026" for p in out["rainy_season_pairs"]),
          f"n={len(out['rainy_season_pairs'])}")
    check("every URL touched is recorded with a status, a size and a hash",
          len(manifest) >= 5 and all(e.get("sha256") for e in manifest if e.get("ok")),
          f"manifest={len(manifest)}")
    check("the point sampled is the verified centroid, not a typed constant",
          out["target"]["lat"] == 37.760459 and out["target"]["lon"] == -122.483894,
          f"target={out['target']}")
    check("the IRI finding is published with its decision",
          out["iri_archive"]["result"] == "sign-in required"
          and "NOT added" in out["iri_archive"]["decision"],
          "iri_archive present")

    # ---- accumulation: a second run with CPC having dropped an issuance ----
    (tmp / "cpc_backtest.json").write_text(json.dumps(out))
    files.pop(f"{bt.CPC_GIS_BASE}/seasprcp_202602.zip")
    out2, _ = bt.build(datadir=tmp, fetch=fake_fetch, today=dt.date(2026, 10, 5))
    carried = [i for i in out2["issuances"] if i.get("carried_from_previous_run")]
    check("an issuance CPC has dropped is carried forward from the previous run",
          len(carried) == 1 and carried[0]["issuance_ym"] == "202602",
          f"carried={[c['issuance_ym'] for c in carried]}")
    check("the carried issuance still contributes its scored pair",
          any(r["season"] == "MAM 2026" for r in out2["scored"]),
          f"seasons={[r['season'] for r in out2['scored']]}")

    # ---- refusing to run without a verified centroid ---------------------
    tmp2 = Path(tempfile.mkdtemp(prefix="bt_selftest2_"))
    (tmp2 / "run.json").write_text(json.dumps({"target": {"zip": "94122"}}))
    out3, _ = bt.build(datadir=tmp2, fetch=fake_fetch, today=dt.date(2026, 9, 18))
    check("with no verified centroid the script samples nothing and says so",
          out3["counts"]["issuances_sampled"] == 0
          and any(i["severity"] == "error" for i in out3["irregularities"]),
          f"irregularities={len(out3['irregularities'])}")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)

    failed = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f"  :: {detail}" if not ok else ""))
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} CPC back-test self-checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
