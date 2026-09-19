"""Shared CPC (Climate Prediction Center) outlook sampling.

This module exists so that the *live* nightly outlook sample and the
*historical back-test* sample run through **exactly the same code path**.  A
hit-rate computed with a second, slightly different sampler would not be a
measurement of the product the site publishes; it would be a measurement of
whatever that second sampler did.

The functions here were lifted verbatim out of ``pipeline/main.py``
(``_sample_one_bundle`` / ``_sample_shapefile_archive``) with two changes:

* the two module-level side effects (``note_irregularity`` and ``record``) are
  now injected callbacks, so the same code can write into the nightly pipeline's
  manifests or into the back-test's own;
* nothing else.  The geometry test, the nearest-polygon fallback and the
  evidence returned are unchanged, so a record produced here is byte-for-byte
  the record the site already publishes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import lib_fetch as fetchlib
import lib_shape as shapelib


def sample_one_bundle(bundle, lat, lon, label, zip_url, note=None):
    """Point-sample a single shapefile bundle at ``(lat, lon)``.

    ``note`` is called as ``note(severity, area, message, evidence)`` for the
    two conditions a reviewer must be able to see: a projected CRS (sampling
    skipped rather than guessed at) and a point that falls in no polygon (the
    nearest polygon is used and flagged).
    """
    def _note(severity, area, message, evidence=None):
        if note:
            note(severity, area, message, evidence or {})

    if not bundle["shp"] or not bundle["dbf"]:
        return {"stem": bundle["stem"], "ok": False,
                "error": "no .shp/.dbf pair for this bundle"}
    prj = shapelib.read_prj(bundle["prj"])
    geographic = shapelib.is_geographic(prj)
    if geographic is False:
        _note("warning", "cpc",
              f"CPC shapefile {bundle['stem']} uses a projected CRS; "
              "point-sampling was skipped rather than guessing at a reprojection.",
              {"url": zip_url, "prj": (prj or "")[:300]})
        return {"stem": bundle["stem"], "ok": False,
                "error": "projected CRS - point sampling skipped", "prj": (prj or "")[:300]}

    _stype, shapes = shapelib.read_shp(Path(bundle["shp"]))
    fields, rows = shapelib.read_dbf(Path(bundle["dbf"]))
    if len(rows) != len(shapes):
        _note("warning", "cpc",
              f"CPC shapefile {bundle['stem']}: .shp has {len(shapes)} records "
              f"but .dbf has {len(rows)}. Attributes matched by index; verify "
              "against the official map before relying on this.",
              {"url": zip_url})

    hits, used_nearest = [], False
    for i, shape in enumerate(shapes):
        if not shape.rings:
            continue
        if not shapelib.bbox_contains(shape.bbox, lon, lat):
            continue
        if shapelib.point_in_polygon(lon, lat, shape.rings):
            hits.append({"index": i, "attrs": rows[i] if i < len(rows) else None,
                         "bbox": [round(v, 4) for v in shape.bbox],
                         "rings": len(shape.rings),
                         "vertices": sum(len(r) for r in shape.rings)})

    if not hits:
        best, bestd = None, None
        for i, shape in enumerate(shapes):
            if not shape.rings or not shape.rings[0]:
                continue
            xs = [pt[0] for pt in shape.rings[0]]
            ys = [pt[1] for pt in shape.rings[0]]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            d = (cx - lon) ** 2 + (cy - lat) ** 2
            if bestd is None or d < bestd:
                bestd, best = d, i
        if best is not None:
            used_nearest = True
            shape = shapes[best]
            hits.append({"index": best, "attrs": rows[best] if best < len(rows) else None,
                         "bbox": [round(v, 4) for v in shape.bbox],
                         "rings": len(shape.rings),
                         "vertices": sum(len(r) for r in shape.rings)})
            _note("warning", "cpc",
                  f"CPC polygon miss: ({lon:.4f}, {lat:.4f}) fell in no polygon of "
                  f"{bundle['stem']} (common for coastal cells). Used the nearest "
                  "polygon instead - flagged for manual review.",
                  {"url": zip_url})

    return {
        "stem": bundle["stem"], "ok": bool(hits), "fields": fields,
        "n_polygons": len(shapes), "n_hits": len(hits),
        "used_nearest_polygon": used_nearest,
        "is_geographic": geographic,
        "hits": hits,
    }


def sample_shapefile_bytes(body, sha256, label, workdir, lat, lon, note=None):
    """Sample an already-downloaded CPC ZIP archive.

    Split out from :func:`sample_shapefile_archive` so the back-test can reuse
    bytes it has already fetched (and recorded in provenance) without a second
    request to NOAA.
    """
    if not body or body[:2] != b"PK":
        return {"label": label, "ok": False, "sha256": sha256,
                "error": "response was not a ZIP archive"}

    tmp = Path(tempfile.mkdtemp(dir=str(workdir)))
    zpath = tmp / "outlook.zip"
    zpath.write_bytes(body)
    try:
        extracted = shapelib.extract_all_shapefiles(zpath, tmp / "shp")
    except Exception as exc:  # noqa: BLE001
        return {"label": label, "ok": False, "sha256": sha256,
                "error": f"zip extract failed: {exc}"}

    bundles = extracted["bundles"]
    if not bundles:
        return {"label": label, "ok": False, "sha256": sha256,
                "error": f"no .shp inside archive; members={extracted['members'][:10]}"}

    sampled = [sample_one_bundle(b, lat, lon, label, "", note=note) for b in bundles]
    ok_count = sum(1 for smp in sampled if smp["ok"])
    if ok_count == 0 and note:
        note("warning", "cpc",
             f"No CPC outlook polygon could be sampled for {label}.",
             {"n_bundles": len(bundles)})

    return {"label": label, "ok": ok_count > 0, "sha256": sha256,
            "n_shapefiles": len(bundles), "n_sampled_ok": ok_count,
            "members": extracted["members"], "sampled": sampled}


def sample_shapefile_archive(zip_url, lat, lon, label, workdir, note=None,
                             record=None, timeout=240):
    """Download a CPC outlook ZIP and point-sample every shapefile inside it.

    ``record`` is called as ``record(fetch_result, note=...)`` and should return
    the provenance entry it wrote, matching ``main.record``.
    """
    res = fetchlib.get(zip_url, timeout=timeout)
    if record:
        record(res, note=f"CPC outlook shapefile archive: {label}")
    out = sample_shapefile_bytes(res.body, res.sha256, label, workdir, lat, lon, note=note)
    out["url"] = zip_url
    out["status"] = res.status
    if not res.ok:
        out["ok"] = False
        out["error"] = out.get("error") or res.error or f"HTTP {res.status}"
    return out
