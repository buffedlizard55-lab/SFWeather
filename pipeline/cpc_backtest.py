#!/usr/bin/env python3
"""CPC seasonal back-test for 94122 — how often a CPC tilt actually verified.

Reads historical CPC seasonal precipitation outlook archives
(``seasprcp_YYYYMM.zip``), samples each at the 94122 centroid with the SAME
point-in-polygon code path used for the live outlooks
(:func:`main._sample_shapefile_archive` → :mod:`lib_shape`), then compares the
sampled category (Above median / Below median / Equal chances) against the
observed GHCN-Daily season total assigned to a tercile of the 1991–2020
distribution.

Output: ``data/cpc_backtest.json`` with one row per scored issuance plus an
overall hit-rate summary broken out by category and lead.

Design constraints (standing rules):
* No invented daily values — this scores *period* outlooks against *period*
  observations only.
* Every archive fetch is recorded in the provenance manifest (URL + status +
  bytes + SHA-256): this step runs after main.py wrote the run files, so it
  merges its own manifest + irregularities back into data/provenance.json,
  data/run.json, data/quality_report.json and data/summary.txt
  (:func:`merge_run_manifests`).  Rows without a recorded fetch are not
  published — the ledger's cpc-backtest-sampling-method check enforces it.
* The official CPC archive is the ONLY source.  The IRI Data Library
  (iridl.ldeo.columbia.edu) was considered and REJECTED: it is a Columbia
  academic mirror, not an official NOAA operational product, it serves HTTP
  (this project requires HTTPS), and its SOURCES/.NOAA/.NCEP/.CPC/ tree holds
  monitoring datasets — not the outlook polygons.  See docs/DATA_SOURCES.md.
* When no historical archive is retrievable (the normal case on the live GIS
  server, which keeps only recent months), the module writes a machine-readable
  ``status: pending-backfill`` file rather than guessing a hit-rate.  The site
  renders that honestly.

Run:  python3 pipeline/cpc_backtest.py [--outdir data]
  (also importable: :func:`score_rows` and :func:`assign_tercile` are pure and
  unit-tested offline in tests/test_parsers.py)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import climo as climo_lib  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Official CPC archive locations (both on already-vetted hosts).
# Live GIS (recent months only, ~8 issuances as of Sep 2026):
CPC_GIS_BASE = "https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst"
# Official long-lead archive index (graphics + data from Oct 1995):
CPC_ARCHIVE_INDEX = "https://www.cpc.ncep.noaa.gov/products/archives/long_lead/llarc.ind.php"
# Official verifications (CPC's own, CONUS-wide — not a 94122 score):
CPC_VERIFICATIONS = "https://www.cpc.ncep.noaa.gov/products/predictions/long_range/tools/briefing/seas_veri.grid.php"

# Seasons whose observed totals can be scored at 94122 from GHCN-Daily.
# Each row: (abbrev, months).  OND/NDJ/DJF/JFM all overlap the Oct–Jan window.
TARGET_SEASONS = {
    "OND": (10, 11, 12),
    "NDJ": (11, 12, 1),
    "DJF": (12, 1, 2),
    "JFM": (1, 2, 3),
}

# August issuances carry OND (lead 2), NDJ (lead 3), DJF (lead 4) and JFM
# (lead 5) in a single file, so one August file per year scores four seasons.
# Mid-August is the third-Thursday release whose 0.5-month lead is SON.
BACKTEST_ISSUANCES = [f"{y}08" for y in range(1995, 2021)]


def season_total_prcp_in(ghcn_by_date, year, months):
    """Observed season-total precipitation in inches, or None if incomplete.

    ``year`` is the calendar year of the season's FIRST month (e.g. 2015 for
    OND 2015, for NDJ 2015-16, and for JFM 2015).  A month belongs to ``year``
    when it is at or after the season's first month, else to ``year + 1`` —
    so NDJ 2015 reads Jan 2016 but JFM 2015 reads Jan-Mar 2015.  (A fixed
    "Jan/Feb/Mar are always year+1" rule silently scored every JFM outlook
    against the following year's rain.)  Returns None when any day of the
    season lacks a GHCN value — a partial total is not a total.
    """
    total_tenths_mm = 0.0
    first = months[0]
    for m in months:
        y = year if m >= first else year + 1
        # Days in month.
        if m == 2:
            ndays = 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
        elif m in (4, 6, 9, 11):
            ndays = 30
        else:
            ndays = 31
        for d in range(1, ndays + 1):
            key = f"{y:04d}-{m:02d}-{d:02d}"
            rec = ghcn_by_date.get(key)
            if not rec or rec.get("PRCP") is None:
                return None
            total_tenths_mm += rec["PRCP"]
    return round(total_tenths_mm / 254.0, 3)  # tenths of mm -> inches


def tercile_breaks(values):
    """33rd/66th percentile breaks of a distribution (linear interpolation)."""
    if not values:
        return None, None
    s = sorted(values)
    def _pct(q):
        k = (len(s) - 1) * q
        f = int(k)
        c = min(f + 1, len(s) - 1)
        return s[f] + (s[c] - s[f]) * (k - f)
    return _pct(1 / 3.0), _pct(2 / 3.0)


def assign_tercile(value, low_break, high_break):
    """Above / Below / Near-normal tercile for an observed season total.

    Ties at a break go to the nearer-middle ("Near-normal") rather than being
    forced into a tilt — a boundary observation is not evidence for either side.
    """
    if value is None or low_break is None or high_break is None:
        return None
    if value < low_break:
        return "Below"
    if value > high_break:
        return "Above"
    return "Near-normal"


def cpc_hit(cpc_category, observed_tercile):
    """Hit / miss / n/a for one scored outlook.

    * CPC "Above median" verifies iff observed is "Above"; "Below median" iff
      observed is "Below".
    * CPC "Equal chances" is never a tilt, so it is unscored (None) — counting
      EC as a hit or miss would invent skill the outlook never claimed.
    * Near-normal observations are hits for EC only in a 3-way sense; since EC
      rows are unscored, they are reported as n/a with the observation shown.
    """
    if not cpc_category or not observed_tercile:
        return None
    cat = cpc_category.strip().lower()
    obs = observed_tercile.strip().lower()
    if cat in ("ec", "equal chances", "equal chance"):
        return None
    if cat in ("above", "above median", "above normal", "a"):
        return obs == "above"
    if cat in ("below", "below median", "below normal", "b"):
        return obs == "below"
    if cat in ("near normal", "normal", "n", "near-normal"):
        return obs == "near-normal"
    return None


def score_rows(rows):
    """Summarise scored rows: overall + by CPC category and by lead.

    ``rows``: list of dicts with keys ``category``, ``observed_tercile``,
    ``hit`` (True/False/None), ``lead``.  EC / unscored rows are counted
    separately and never folded into the hit-rate denominator.
    """
    scored = [r for r in rows if r.get("hit") is True or r.get("hit") is False]
    hits = sum(1 for r in scored if r.get("hit") is True)
    summary = {
        "n_issuances_scored": len({r.get("issuance_ym") for r in scored}),
        "n_rows_scored": len(scored),
        "n_rows_unscored_ec": sum(1 for r in rows if r.get("hit") is None),
        "hits": hits,
        "misses": len(scored) - hits,
        "hit_rate_pct": round(100.0 * hits / len(scored), 1) if scored else None,
    }
    by_category = {}
    for r in scored:
        key = r.get("category_label") or r.get("category") or "unknown"
        b = by_category.setdefault(key, {"scored": 0, "hits": 0})
        b["scored"] += 1
        b["hits"] += 1 if r.get("hit") else 0
    for b in by_category.values():
        b["hit_rate_pct"] = round(100.0 * b["hits"] / b["scored"], 1) if b["scored"] else None
    summary["by_category"] = by_category
    by_lead = {}
    for r in scored:
        key = str(r.get("lead"))
        b = by_lead.setdefault(key, {"scored": 0, "hits": 0})
        b["scored"] += 1
        b["hits"] += 1 if r.get("hit") else 0
    for b in by_lead.values():
        b["hit_rate_pct"] = round(100.0 * b["hits"] / b["scored"], 1) if b["scored"] else None
    summary["by_lead"] = by_lead
    return summary


def issuance_urls(ym):
    """Candidate official URLs for one historical issuance (precip only)."""
    return [
        f"{CPC_GIS_BASE}/seasprcp_{ym}.zip",
        # Some older issuances were retained under the www tree.
        f"https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasprcp_{ym}.zip",
    ]


def merge_run_manifests(outdir, pipeline_main, fetchlib):
    """Fold this step's fetches + irregularities back into the run's files.

    cpc_backtest runs as its own workflow step, AFTER main.py wrote
    data/provenance.json, data/run.json, data/quality_report.json and
    data/summary.txt.  Its record()/note_irregularity() calls would otherwise
    die with this process, leaving scored rows with no recorded fetch (which
    the ledger rightly fails) and fetch counts that no longer recount.

    Merging keeps every invariant the ledger checks: provenance-record-count,
    fetch-counts-recompute, and cpc-backtest-sampling-method's per-row
    fetch_ok.  Never raises — a merge failure is printed and the step still
    exits 0, so the ledger (not a crash) reports whatever is inconsistent.
    """
    try:
        new_entries = list(pipeline_main.MANIFEST or [])
        new_irregs = list(pipeline_main.IRREGULARITIES or [])
        prov_path = outdir / "provenance.json"
        if prov_path.exists():
            prov = json.loads(prov_path.read_text())
            merged = list(prov.get("entries") or []) + new_entries
        else:
            prov = {"note": "Every value in this repository comes from one of the URLs below.",
                    "entries": []}
            merged = new_entries
        prov["entries"] = merged
        prov["generated_utc"] = fetchlib.iso_utc()
        prov_path.write_text(json.dumps(prov, indent=2))
        counts = pipeline_main.count_fetches(merged)

        run_path = outdir / "run.json"
        if run_path.exists():
            run = json.loads(run_path.read_text())
            run.setdefault("counts", {}).update(counts)

        qual_path = outdir / "quality_report.json"
        if qual_path.exists():
            qual = json.loads(qual_path.read_text())
            qual_irregs = list(qual.get("irregularities") or []) + new_irregs
            qual["irregularities"] = qual_irregs
            qual["counts"] = {
                "total": len(qual_irregs),
                "errors": sum(1 for i in qual_irregs if i.get("severity") == "error"),
                "warnings": sum(1 for i in qual_irregs if i.get("severity") == "warning"),
                "info": sum(1 for i in qual_irregs if i.get("severity") == "info"),
            }
            qual["generated_utc"] = fetchlib.iso_utc()
            qual_path.write_text(json.dumps(qual, indent=2))
            if run_path.exists():
                run["counts"]["irregularities"] = len(qual_irregs)

        if run_path.exists():
            run_path.write_text(json.dumps(run, indent=2))

        # Keep the human-readable summary consistent with the recomputed counts.
        sum_path = outdir / "summary.txt"
        if sum_path.exists():
            lines = sum_path.read_text().splitlines()
            for idx, line in enumerate(lines):
                if line.startswith("FETCHES:"):
                    lines[idx] = (
                        f"FETCHES: {counts['successful_fetches']} ok / "
                        f"{counts['failed_fetches']} failed / "
                        f"{counts['expected_absences']} absent by design "
                        f"(includes the CPC back-test's archive attempts)")
                    break
            for idx, line in enumerate(lines):
                if line.startswith("IRREGULARITIES:"):
                    try:
                        old_n = int(line.split(":")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        old_n = 0
                    lines[idx] = f"IRREGULARITIES: {old_n + len(new_irregs)}"
                    break
            for i in new_irregs:
                lines.append(f"  [{i.get('severity')}] {i.get('area')}: {i.get('message')}")
            sum_path.write_text("\n".join(lines) + "\n")
        print(f"  cpc back-test: merged {len(new_entries)} fetch(es) and "
              f"{len(new_irregs)} irregularitie(s) into the run files")
    except Exception as exc:  # noqa: BLE001 - merge must not fail the step
        print(f"  cpc back-test manifest merge warning: {exc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--max-issuances", type=int, default=26,
                    help="Cap on historical archives to attempt (default: 26 August files 1995-2020)")
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Lazy imports: main.py owns the fetch manifest + sampler; importing it is
    # heavy but guarantees the SAME code path as the live outlooks.
    import lib_fetch as fetchlib  # noqa: E402
    import main as pipeline_main  # noqa: E402

    ghcn_probe = {}
    ghcn_path = outdir / "ghcn_probe.json"
    # The full GHCN series lives in the pipeline's memory, not on disk; the
    # back-test re-reads the station file's parsed form from climatology inputs.
    # If the pipeline just ran, re-parse from the recorded URL is wasteful, so
    # instead rebuild season totals from climatology.json season_by_year?  No:
    # those are Oct-Jan totals, not OND/NDJ/DJF/JFM.  Fetch the GHCN file once
    # (recorded in the manifest) and parse it — the honest, traceable path.
    ghcn_url = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv"
    res = fetchlib.get(ghcn_url, timeout=600)
    pipeline_main.record(res, note="NCEI GHCN-Daily USW00023272 (CPC back-test season totals)")
    if not (res.ok and res.body):
        payload = {
            "generated_utc": fetchlib.iso_utc(),
            "status": "pending-backfill",
            "reason": f"GHCN-Daily station file unavailable (status {res.status}); no observed tercile can be computed.",
            "archive_index": CPC_ARCHIVE_INDEX,
            "verifications": CPC_VERIFICATIONS,
            "issuances_attempted": [],
            "rows": [],
            "summary": score_rows([]),
            "note": ("CPC outlooks are probabilities for a 3-month period. The back-test scores "
                     "each historical August issuance at the 94122 point against the observed "
                     "OND/NDJ/DJF/JFM precipitation tercile. EC outlooks are never tilts and are unscored."),
        }
        (outdir / "cpc_backtest.json").write_text(json.dumps(payload, indent=2))
        merge_run_manifests(outdir, pipeline_main, fetchlib)
        print("  cpc back-test: GHCN unavailable; wrote pending-backfill")
        return 0

    ghcn_by_date, _fmt = climo_lib.parse_ghcn_daily(res.text())

    # Tercile breaks per target season over the 1991–2020 normals period.
    breaks = {}
    for abbrev, months in TARGET_SEASONS.items():
        vals = []
        for y in range(1991, 2021):
            t = season_total_prcp_in(ghcn_by_date, y, months)
            if t is not None:
                vals.append(t)
        lo, hi = tercile_breaks(vals)
        breaks[abbrev] = {"low_in": lo, "high_in": hi, "n_seasons": len(vals)}

    # Centroid for sampling.
    run_path = outdir / "run.json"
    lat, lon = 37.760459, -122.483894
    if run_path.exists():
        try:
            run = json.loads(run_path.read_text())
            lat = float(run["target"]["centroid"]["lat"])
            lon = float(run["target"]["centroid"]["lon"])
        except Exception:
            pass

    rows = []
    attempted = []
    workdir = Path(tempfile.mkdtemp(prefix="cpc_backtest_"))
    try:
        for ym in BACKTEST_ISSUANCES[: args.max_issuances]:
            got = None
            for url in issuance_urls(ym):
                # Historical GIS issuances are routinely absent (the live server
                # keeps recent months only), so a 404 here is recorded by the
                # sampler and reclassified below — it must not count as a real
                # fetch failure that masks an outage elsewhere.
                out = pipeline_main._sample_shapefile_archive(
                    url, lat, lon, f"CPC back-test issuance {ym}", workdir)
                if not out.get("ok") and pipeline_main.MANIFEST:
                    last = pipeline_main.MANIFEST[-1]
                    if last.get("url") == url and not last.get("ok"):
                        last["expected_absent"] = "historical-archive-not-retained"
                attempted.append({"issuance_ym": ym, "url": url,
                                  "ok": bool(out.get("ok")),
                                  "status": out.get("status"),
                                  "error": out.get("error")})
                if out.get("ok"):
                    got = (url, out)
                    break
            if not got:
                continue
            url, out = got
            year = int(ym[:4])
            for smp in out.get("sampled", []):
                if not smp.get("ok") or not smp.get("hits"):
                    continue
                stem = smp.get("stem") or ""
                # Precipitation bundles only for the rain back-test.
                if "prcp" not in stem.lower():
                    continue
                for hit in smp["hits"]:
                    a = hit.get("attrs") or {}
                    valid_seas = (a.get("Valid_Seas") or "").strip()
                    parts = valid_seas.split()
                    if len(parts) != 2:
                        continue
                    abbrev = parts[0].upper()
                    if abbrev not in TARGET_SEASONS:
                        continue
                    try:
                        season_year = int(parts[1])
                    except ValueError:
                        continue
                    # Only score seasons fully inside the observed record and
                    # fully outside the normals-fitting window edge effects: any
                    # completed season with a GHCN total qualifies.
                    obs_total = season_total_prcp_in(
                        ghcn_by_date, season_year, TARGET_SEASONS[abbrev])
                    br = breaks.get(abbrev, {})
                    tercile = assign_tercile(obs_total, br.get("low_in"), br.get("high_in"))
                    cat = str(a.get("Cat") or "").strip()
                    try:
                        prob = float(a.get("Prob")) if a.get("Prob") is not None else None
                    except (TypeError, ValueError):
                        prob = None
                    import re as _re
                    m = _re.match(r"lead(\d+)_", stem, _re.I)
                    lead = int(m.group(1)) if m else None
                    rows.append({
                        "issuance_ym": ym,
                        "season": valid_seas,
                        "abbrev": abbrev,
                        "season_year": season_year,
                        "lead": lead,
                        "stem": stem,
                        "category": cat,
                        "category_label": {
                            "EC": "Equal chances",
                            "Above": "Above median",
                            "Below": "Below median",
                        }.get(cat, cat),
                        "probability": prob,
                        "observed_total_in": obs_total,
                        "observed_tercile": tercile,
                        "tercile_breaks_in": {"low": br.get("low_in"), "high": br.get("high_in")},
                        "hit": cpc_hit(cat, tercile) if obs_total is not None else None,
                        "polygon_index": hit.get("index"),
                        "polygon_bbox_lon_lat": hit.get("bbox"),
                        "used_nearest_polygon": bool(smp.get("used_nearest_polygon")),
                        "raw_dbf_row": {k: v for k, v in a.items()},
                        "url": url,
                        "sampling": "lib_shape.point_in_polygon at the 94122 centroid (same code path as live CPC outlooks)",
                    })
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    summary = score_rows(rows)
    n_ok = sum(1 for a in attempted if a.get("ok"))
    payload = {
        "generated_utc": fetchlib.iso_utc(),
        "status": "scored" if rows else "pending-backfill",
        "reason": (None if rows else
                   "No historical seasprcp_YYYYMM.zip was retrievable from the official CPC hosts "
                   "this run (the live GIS server keeps only recent months). The official graphics/data "
                   "archive from Oct 1995 is linked below for manual review; no hit-rate is published "
                   "until an archive file is actually fetched and sampled."),
        "archive_index": CPC_ARCHIVE_INDEX,
        "verifications": CPC_VERIFICATIONS,
        "method": ("Sample each historical August seasprcp issuance at the 94122 centroid; "
                   "compare the sampled Above/Below/EC category against the observed GHCN-Daily "
                   "OND/NDJ/DJF/JFM total assigned to a tercile of its own 1991–2020 distribution. "
                   "EC outlooks are unscored (None), never counted as hits or misses."),
        "normals_period": [1991, 2020],
        "station_id": "USW00023272",
        "station_url": ghcn_url,
        "tercile_breaks_in": breaks,
        "issuances_attempted": attempted,
        "n_archives_retrieved": n_ok,
        "rows": rows,
        "summary": summary,
        "note": ("Hit-rate is over scored (non-EC) rows only. CPC outlooks are regional "
                 "probabilities for a 3-month period, never daily values; the polygon index "
                 "and bounding box are published per row so each sample can be checked against "
                 "the official map."),
    }
    (outdir / "cpc_backtest.json").write_text(json.dumps(payload, indent=2))
    merge_run_manifests(outdir, pipeline_main, fetchlib)
    print(f"  cpc back-test: {len(rows)} row(s) scored from {n_ok} archive(s); "
          f"hit-rate {summary.get('hit_rate_pct')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
