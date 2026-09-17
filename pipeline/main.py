#!/usr/bin/env python3
"""SFWeather data pipeline.

Fetches weather and climate information for San Francisco ZIP code 94122 from
public, free, official sources only, computes the rainy-season climatology that
underpins the Oct 2026 - Jan 2027 scoreboard, and writes everything to ``data/``
together with a provenance manifest and a data-quality report.

Run:  python3 pipeline/main.py [--outdir data]

Every number produced downstream is traceable to a URL recorded in
``data/provenance.json``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib_fetch as fetchlib          # noqa: E402
import lib_shape as shapelib          # noqa: E402
import climo                          # noqa: E402

# --------------------------------------------------------------------------
# Configuration - everything here is a documented choice, not a guess.
# --------------------------------------------------------------------------

TARGET = {
    "zip": "94122",
    "label": "San Francisco, CA 94122 (Inner Sunset / Outer Sunset)",
    "fallback_lat": 37.7599,      # replaced by the Census ZCTA centroid below
    "fallback_lon": -122.4849,
}

SEASON = {"start": "2026-10-01", "end": "2027-01-31"}
NORMALS_PERIOD = (1991, 2020)

# Candidate official stations, in preference order.  The first one that returns
# data from NCEI is used; the choice is recorded in the manifest.
GHCN_CANDIDATES = [
    ("USW00023272", "SAN FRANCISCO DOWNTOWN, CA US"),
    ("USW00023234", "SAN FRANCISCO INTL AP, CA US"),
    ("USC00047899", "SAN FRANCISCO, CA US"),
]
GSOD_STATIONS = [
    ("72494023234", "SAN FRANCISCO INTERNATIONAL AIRPORT (KSFO)"),
    ("72494023272", "SAN FRANCISCO DOWNTOWN (KSFO alt id)"),
]

CPC_GIS_BASE = "https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst"
CPC_WWW_BASE = "https://www.cpc.ncep.noaa.gov"

MANIFEST: list[dict] = []
IRREGULARITIES: list[dict] = []

# The pipeline mirrors everything it prints into <outdir>/pipeline.log.  That
# file is committed by the workflow, which is the only way to inspect a run
# from a machine that cannot reach GitHub's log blob storage.
_LOG_PATH: Path | None = None


def log(msg=""):
    print(msg, flush=True)
    if _LOG_PATH:
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(str(msg) + "\n")
        except Exception:  # noqa: BLE001 - never let logging break the run
            pass


def note_irregularity(severity, area, message, evidence=None):
    IRREGULARITIES.append({
        "severity": severity,      # "error" | "warning" | "info"
        "area": area,
        "message": message,
        "evidence": evidence or {},
    })


def record(res, **kwargs):
    MANIFEST.append(res.provenance(**kwargs))
    return res


# ------------------------------------------------------------------ helpers

def html_to_text(html):
    """Very small HTML->text conversion (enough for NOAA's static pages)."""
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&#39;", "'").replace("&quot;", '"'))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False, default=str))
    print(f"  wrote {path} ({path.stat().st_size:,} bytes)")


# ==========================================================================
# 1.  ZIP code centroid - U.S. Census Bureau Gazetteer (official)
# ==========================================================================

def fetch_zip_centroid():
    url = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip"
    res = fetchlib.get(url, timeout=300)
    record(res, note="U.S. Census Bureau 2024 Gazetteer - ZCTA5 centroids (source of the 94122 lat/lon)")
    if not res.ok:
        # previous release year
        url2 = url.replace("2024_Gazetteer/2024_Gaz", "2023_Gazetteer/2023_Gaz")
        res2 = fetchlib.get(url2, timeout=300)
        record(res2, note="Fallback: U.S. Census Bureau 2023 Gazetteer - ZCTA5 centroids")
        if not res2.ok:
            note_irregularity("warning", "geography",
                              "Could not retrieve the Census ZCTA Gazetteer; using the "
                              "hard-coded fallback centroid and flagging it for review.",
                              {"urls": [url, url2],
                               "status": [res.status, res2.status],
                               "fallback": [TARGET["fallback_lat"], TARGET["fallback_lon"]]})
            return {"lat": TARGET["fallback_lat"], "lon": TARGET["fallback_lon"],
                    "source": "fallback (not verified against Census)",
                    "verified": False, "url": url}
        res, url = res2, url2

    import zipfile, io, csv
    with zipfile.ZipFile(io.BytesIO(res.body)) as zf:
        name = next((n for n in zf.namelist() if n.lower().endswith(".txt")), zf.namelist()[0])
        raw = zf.read(name).decode("utf-8-sig", "replace")

    # The Census Gazetteer files are tab-delimited with CRLF endings, so header
    # names and values must be stripped (the last column otherwise arrives as
    # "INTPTLONG\r").  Column lookup is done case-insensitively.
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
    raw_fields = reader.fieldnames or []
    fields = {f.strip().upper(): f for f in raw_fields}

    def col(*names):
        for n in names:
            if n in fields:
                return fields[n]
        return None

    c_geo = col("GEOID")
    c_lat = col("INTPTLAT", "INTPTLATITUDE", "LAT", "LATITUDE")
    c_lon = col("INTPTLONG", "INTPTLONGITUDE", "LON", "LONG", "LONGITUDE")

    if not (c_geo and c_lat and c_lon):
        note_irregularity("error", "geography",
                          "The Census Gazetteer file did not expose GEOID / INTPTLAT / "
                          "INTPTLONG columns; the 94122 centroid could not be verified.",
                          {"url": url, "file_in_archive": name,
                           "header": raw_fields[:20]})
        return {"lat": TARGET["fallback_lat"], "lon": TARGET["fallback_lon"],
                "source": "fallback (unexpected Gazetteer columns)",
                "verified": False, "url": url, "header": raw_fields[:20]}

    for row in reader:
        if ((row.get(c_geo) or "").strip() == TARGET["zip"]):
            try:
                lat = float((row.get(c_lat) or "").strip())
                lon = float((row.get(c_lon) or "").strip())
            except ValueError:
                note_irregularity("error", "geography",
                                  "Census Gazetteer row for 94122 had un-parseable "
                                  "coordinates.", {"url": url, "row": dict(row)})
                break
            return {
                "zip": TARGET["zip"],
                "lat": lat, "lon": lon,
                "land_area_sqmi": float(row[col("ALAND_SQMI")]) if col("ALAND_SQMI") and row.get(col("ALAND_SQMI")) else None,
                "water_area_sqmi": float(row[col("AWATER_SQMI")]) if col("AWATER_SQMI") and row.get(col("AWATER_SQMI")) else None,
                "source": "U.S. Census Bureau Gazetteer file (internal point / centroid)",
                "verified": True,
                "url": url,
                "file_in_archive": name,
                "gazetteer_year": (re.search(r"(\d{4})_Gaz", url) or [None, None])[1],
                # The Gazetteer's last column (INTPTLONG) is space-padded to the
                # full record width; trim before reporting so the manifest is
                # readable rather than a wall of trailing blanks.
                "column_names_used": {"geoid": (c_geo or "").strip(),
                                      "lat": (c_lat or "").strip(),
                                      "lon": (c_lon or "").strip()},
            }

    note_irregularity("warning", "geography",
                      f"ZIP {TARGET['zip']} not found in the Census Gazetteer file; "
                      "falling back to the hard-coded centroid.",
                      {"url": url})
    return {"lat": TARGET["fallback_lat"], "lon": TARGET["fallback_lon"],
            "source": "fallback (ZIP not present in Gazetteer)", "verified": False, "url": url}


# ==========================================================================
# 2.  National Weather Service (NOAA/NWS) - api.weather.gov
# ==========================================================================

def fetch_nws(lat, lon):
    nws = {}
    base = "https://api.weather.gov"

    # -- point metadata ---------------------------------------------------
    pt_url = f"{base}/points/{lat:.4f},{lon:.4f}"
    pt, res = fetchlib.get_json(pt_url)
    record(res, note="NWS point metadata -> forecast grid, zone, county, radar")
    if pt is None:
        note_irregularity("error", "nws", "NWS point metadata request failed; all "
                          "NWS products are unavailable for this run.",
                          {"url": pt_url, "status": res.status, "error": res.error})
        return {"error": res.error, "point_url": pt_url}

    props = pt["properties"]
    nws["point"] = {
        "grid_id": props["gridId"], "grid_x": props["gridX"], "grid_y": props["gridY"],
        "forecast_office": props["forecastOffice"],
        "cwa": props.get("cwa"),
        "timezone": props["timeZone"],
        "radar_station": props.get("radarStation"),
        "forecast_zone": props.get("forecastZone"),
        "county_zone": props.get("county"),
        "relative_location": props.get("relativeLocation", {}).get("properties", {}),
        "source_url": pt_url,
    }
    grid = f"{props['gridId']}/{props['gridX']},{props['gridY']}"

    # -- 7-day narrative forecast ----------------------------------------
    fc_url = f"{base}/gridpoints/{grid}/forecast"
    fc, res = fetchlib.get_json(fc_url)
    record(res, note="Official NWS 7-day forecast (text + numeric per period)")
    if fc:
        nws["forecast_daily"] = {
            "updated": fc["properties"].get("updated") or fc["properties"].get("updateTime"),
            "generated_at": fc["properties"].get("generatedAt"),
            "valid_times": fc["properties"].get("validTimes"),
            "elevation_m": fc["properties"].get("elevation", {}).get("value"),
            "periods": [
                {
                    "number": p["number"], "name": p["name"],
                    "start_time": p["startTime"], "end_time": p["endTime"],
                    "is_daytime": p["isDaytime"],
                    "temperature_f": p["temperature"], "temperature_unit": p["temperatureUnit"],
                    "wind_speed": p["windSpeed"], "wind_direction": p["windDirection"],
                    "icon": p.get("icon"),
                    "short_forecast": p["shortForecast"],
                    "detailed_forecast": p["detailedForecast"],
                    "pop_pct": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                    "dewpoint_f": ((p.get("dewpoint") or {}).get("value")),
                    "relative_humidity_pct": ((p.get("relativeHumidity") or {}).get("value")),
                }
                for p in fc["properties"]["periods"]
            ],
            "source_url": fc_url,
            "human_url": f"https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}&unit=0&lg=english&FcstType=text&TextType=1",
        }

    # -- hourly forecast (drives the per-day scoreboard numbers) ----------
    fh_url = f"{base}/gridpoints/{grid}/forecast/hourly"
    fh, res = fetchlib.get_json(fh_url)
    record(res, note="Official NWS hourly gridded forecast (temp, dewpoint, RH, wind, gust, POP, QPF)")
    if fh:
        periods = []
        for p in fh["properties"]["periods"]:
            periods.append({
                "start_time": p["startTime"],
                "end_time": p.get("endTime"),
                "temperature_f": p["temperature"],
                "dewpoint_f": (p.get("dewpoint") or {}).get("value"),
                "rh_pct": (p.get("relativeHumidity") or {}).get("value"),
                "wind_speed": p["windSpeed"],
                "wind_gust": p.get("windGust"),
                "wind_direction": p.get("windDirection"),
                "pop_pct": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                "qpf_mm": (p.get("quantitativePrecipitation") or {}).get("value"),
                "short_forecast": p.get("shortForecast"),
            })
        nws["forecast_hourly"] = {
            "updated": fh["properties"].get("updated") or fh["properties"].get("updateTime"),
            "generated_at": fh["properties"].get("generatedAt"),
            "elevation_m": fh["properties"].get("elevation", {}).get("value"),
            "periods": periods,
            "source_url": fh_url,
        }
        missing_fields = defaultdict(int)
        for p in periods:
            for k in ("temperature_f", "rh_pct", "wind_speed", "pop_pct", "qpf_mm"):
                if p.get(k) is None:
                    missing_fields[k] += 1
        if missing_fields:
            note_irregularity("info", "nws",
                              "Some hourly forecast fields are null in the NWS gridded "
                              "forecast for this grid cell.", {"missing_counts": dict(missing_fields),
                                                               "hours": len(periods)})

    # -- raw gridpoint values ---------------------------------------------
    gd_url = f"{base}/gridpoints/{grid}"
    gd, res = fetchlib.get_json(gd_url)
    record(res, note="NWS raw gridpoint element values (authoritative gridded fields)")
    if gd:
        keep = ["temperature", "dewpoint", "relativeHumidity", "apparentTemperature",
                "windSpeed", "windGust", "windDirection", "probabilityOfPrecipitation",
                "quantitativePrecipitation", "skyCover", "weather", "hazards"]
        gprops = gd["properties"]
        trimmed = {}
        for key in keep:
            if key in gprops:
                trimmed[key] = gprops[key]
        nws["gridpoint_raw"] = {
            "updated": gprops.get("updated") or gprops.get("updateTime"),
            "generated_at": gprops.get("generatedAt"),
            "elevation_m": (gprops.get("elevation") or {}).get("value"),
            "values": trimmed,
            "available_keys": sorted(gprops.keys()),
            "source_url": gd_url,
        }

    # -- observation stations + latest observations -----------------------
    st_url = f"{base}/gridpoints/{grid}/stations"
    st, res = fetchlib.get_json(st_url)
    record(res, note="NWS observation stations for the grid cell")
    stations = []
    if st:
        for f in st.get("features", [])[:6]:
            sp = f["properties"]
            sid = sp.get("stationIdentifier")
            if not sid:
                continue
            obs_url = f"{base}/stations/{sid}/observations/latest"
            obs, ores = fetchlib.get_json(obs_url)
            record(ores, note=f"Latest official observation from station {sid}")
            entry = {
                "station_id": sid,
                "name": sp.get("name"),
                "elevation_m": (sp.get("elevation") or {}).get("value"),
                "distance_m": (sp.get("distance") or {}).get("value"),
                "observation": None,
                "observation_url": obs_url,
            }
            if obs and obs.get("properties"):
                op = obs["properties"]
                entry["observation"] = {
                    "timestamp": op.get("timestamp"),
                    "temperature_c": (op.get("temperature") or {}).get("value"),
                    "dewpoint_c": (op.get("dewpoint") or {}).get("value"),
                    "relative_humidity_pct": (op.get("relativeHumidity") or {}).get("value"),
                    "wind_speed_kmh": (op.get("windSpeed") or {}).get("value"),
                    "wind_gust_kmh": (op.get("windGust") or {}).get("value"),
                    "wind_direction_deg": (op.get("windDirection") or {}).get("value"),
                    "barometric_pressure_pa": (op.get("barometricPressure") or {}).get("value"),
                    "precipitation_last_hour_mm": (op.get("precipitationLastHour") or {}).get("value"),
                    "precipitation_last_3_hours_mm": (op.get("precipitationLast3Hours") or {}).get("value"),
                    "text_description": op.get("textDescription"),
                }
            stations.append(entry)
    nws["stations"] = stations

    # -- active alerts ----------------------------------------------------
    zone = (props.get("forecastZone") or "").rsplit("/", 1)[-1]
    if zone:
        al_url = f"{base}/alerts/active?zone={zone}"
        al, res = fetchlib.get_json(al_url)
        record(res, note=f"Active NWS alerts/warnings for zone {zone}")
        if al:
            feats = al.get("features", [])

            def _is_test(props_):
                blob = " ".join(str(props_.get(k) or "") for k in
                                ("event", "headline", "description")).upper()
                return ("TEST" in blob and
                        ("THIS MESSAGE IS FOR TEST" in blob or "TEST TSUNAMI" in blob
                         or "TEST WARNING" in blob or "DRILL" in blob))

            events = []
            n_test = 0
            for f in feats:
                p = f["properties"]
                test = _is_test(p)
                if test:
                    n_test += 1
                events.append({
                    "event": p.get("event"),
                    "severity": p.get("severity"),
                    "urgency": p.get("urgency"),
                    "certainty": p.get("certainty"),
                    "effective": p.get("effective"),
                    "expires": p.get("expires"),
                    "headline": p.get("headline"),
                    "description": (p.get("description") or "")[:1200],
                    "id": p.get("id"),
                    "is_test": test,
                })
            nws["active_alerts"] = {
                # Count only alerts that are NOT test messages, so a scheduled
                # NOAA test (e.g. the annual tsunami test) can never be shown to
                # a landlord as a real warning.  Tests are kept, flagging them.
                "zone": zone, "count": len(feats) - n_test,
                "test_count": n_test,
                "count_including_tests": len(feats),
                "updated": al.get("updated"),
                "events": events,
                "source_url": al_url,
                "human_url": f"https://www.weather.gov/{props.get('cwa','').lower()}",
            }

    # -- official narrative products --------------------------------------
    products = {}
    office = props.get("cwa") or "MTR"
    for ptype, label in (("AFD", "Area Forecast Discussion"),
                         ("HWO", "Hazardous Weather Outlook")):
        lst_url = f"{base}/products/types/{ptype}/locations/{office}"
        lst, res = fetchlib.get_json(lst_url)
        record(res, note=f"NWS {ptype} ({label}) product list for {office}")
        if not lst:
            continue
        # The NWS products endpoint is JSON-LD: the newest product is the first
        # entry of "@graph", and its URL lives in "@id" ("id" is only a UUID).
        feats = lst.get("@graph") or lst.get("features") or []
        if not feats:
            note_irregularity("warning", "nws",
                              f"No {ptype} products returned for office {office}.",
                              {"url": lst_url})
            continue
        p_url = None
        for f in feats:
            cand = f.get("@id") or f.get("id")
            if isinstance(cand, str) and cand.startswith("http"):
                p_url = cand
                break
        if not p_url:
            note_irregularity("warning", "nws",
                              f"{ptype} product list for {office} contained no usable "
                              "product URL (expected a JSON-LD '@id').",
                              {"url": lst_url,
                               "keys": sorted(feats[0].keys()) if feats else []})
            continue
        p, pres = fetchlib.get_json(p_url)
        record(pres, note=f"NWS {ptype} ({label}) full text")
        if p:
            products[ptype] = {
                "label": label,
                "id": p.get("id"),
                "issuance_time": p.get("issuanceTime"),
                "product_name": p.get("productName"),
                "wmo_collective_id": p.get("wmoCollectiveId"),
                "text": p.get("productText") or "",
                "source_url": p_url,
            }
    nws["products"] = products

    return nws


# ==========================================================================
# 3.  Climate Prediction Center (NOAA/NWS/NCEP) outlooks
# ==========================================================================

def _sample_one_bundle(bundle, lat, lon, label, zip_url):
    """Point-sample a single shapefile bundle at (lat, lon)."""
    if not bundle["shp"] or not bundle["dbf"]:
        return {"stem": bundle["stem"], "ok": False,
                "error": "no .shp/.dbf pair for this bundle"}
    prj = shapelib.read_prj(bundle["prj"])
    geographic = shapelib.is_geographic(prj)
    if geographic is False:
        note_irregularity("warning", "cpc",
                          f"CPC shapefile {bundle['stem']} uses a projected CRS; "
                          "point-sampling was skipped rather than guessing at a reprojection.",
                          {"url": zip_url, "prj": (prj or "")[:300]})
        return {"stem": bundle["stem"], "ok": False,
                "error": "projected CRS - point sampling skipped", "prj": (prj or "")[:300]}

    _stype, shapes = shapelib.read_shp(Path(bundle["shp"]))
    fields, rows = shapelib.read_dbf(Path(bundle["dbf"]))
    if len(rows) != len(shapes):
        note_irregularity("warning", "cpc",
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
            note_irregularity("warning", "cpc",
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


def _sample_shapefile_archive(zip_url, lat, lon, label, workdir):
    """Download a CPC outlook ZIP and point-sample every shapefile inside it."""
    res = fetchlib.get(zip_url, timeout=240)
    prov = record(res, note=f"CPC outlook shapefile archive: {label}")
    if not res.ok or not res.body or res.body[:2] != b"PK":
        return {"label": label, "ok": False, "status": res.status, "url": zip_url,
                "error": res.error or "response was not a ZIP archive"}

    tmp = Path(tempfile.mkdtemp(dir=workdir))
    zpath = tmp / "outlook.zip"
    zpath.write_bytes(res.body)
    try:
        extracted = shapelib.extract_all_shapefiles(zpath, tmp / "shp")
    except Exception as exc:  # noqa: BLE001
        return {"label": label, "ok": False, "status": res.status, "url": zip_url,
                "error": f"zip extract failed: {exc}"}

    bundles = extracted["bundles"]
    if not bundles:
        return {"label": label, "ok": False, "status": res.status, "url": zip_url,
                "error": f"no .shp inside archive; members={extracted['members'][:10]}"}

    sampled = [_sample_one_bundle(b, lat, lon, label, zip_url) for b in bundles]
    ok_count = sum(1 for smp in sampled if smp["ok"])
    if ok_count == 0:
        note_irregularity("warning", "cpc",
                          f"No CPC outlook polygon could be sampled for {label}.",
                          {"url": zip_url, "n_bundles": len(bundles)})

    return {"label": label, "ok": ok_count > 0, "url": zip_url, "sha256": res.sha256,
            "n_shapefiles": len(bundles), "n_sampled_ok": ok_count,
            "members": extracted["members"], "sampled": sampled}


CPC_SHORTRANGE = [
    ("610temp_latest.zip", "6-10 Day Temperature Outlook"),
    ("610prcp_latest.zip", "6-10 Day Precipitation Outlook"),
    ("814temp_latest.zip", "8-14 Day Temperature Outlook"),
    ("814prcp_latest.zip", "8-14 Day Precipitation Outlook"),
    ("wk34temp_latest.zip", "Week 3-4 Temperature Outlook"),
    ("wk34prcp_latest.zip", "Week 3-4 Precipitation Outlook"),
]

CPC_MAP_IMAGES = [
    ("6-10 Day Temperature", "610day_temp", [
        "https://www.cpc.ncep.noaa.gov/products/predictions/610day/610temp.new.gif",
    ]),
    ("6-10 Day Precipitation", "610day_prcp", [
        "https://www.cpc.ncep.noaa.gov/products/predictions/610day/610prcp.new.gif",
    ]),
    ("8-14 Day Temperature", "814day_temp", [
        "https://www.cpc.ncep.noaa.gov/products/predictions/814day/814temp.new.gif",
    ]),
    ("8-14 Day Precipitation", "814day_prcp", [
        "https://www.cpc.ncep.noaa.gov/products/predictions/814day/814prcp.new.gif",
    ]),
    ("Week 3-4 Temperature", "wk34_temp", [
        "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/gifs/WK34temp.gif",
    ]),
    ("Week 3-4 Precipitation", "wk34_prcp", [
        "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/gifs/WK34prcp.gif",
    ]),
    ("30-Day (official updated) Temperature", "30day_temp", [
        "https://www.cpc.ncep.noaa.gov/products/predictions/30day/off15_temp.gif",
        "https://www.cpc.ncep.noaa.gov/products/predictions/30day/lead01_temp.gif",
    ]),
    ("30-Day (official updated) Precipitation", "30day_prcp", [
        "https://www.cpc.ncep.noaa.gov/products/predictions/30day/off15_prcp.gif",
        "https://www.cpc.ncep.noaa.gov/products/predictions/30day/lead01_prcp.gif",
    ]),
]

CPC_DISCUSSIONS = [
    ("6-10 & 8-14 Day Prognostic Discussion",
     "https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html",
     "https://www.cpc.ncep.noaa.gov/products/predictions/610day/"),
    ("30-Day Outlook Discussion",
     "https://www.cpc.ncep.noaa.gov/products/predictions/30day/fxus05.html",
     "https://www.cpc.ncep.noaa.gov/products/predictions/30day/"),
    ("90-Day (3-month) Outlook Discussion",
     "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html",
     "https://www.cpc.ncep.noaa.gov/products/predictions/90day/"),
    ("Week 3-4 Outlook Discussion",
     "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/texts/week34fcst.txt",
     "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/"),
]


def fetch_cpc(lat, lon, assets_dir: Path, today: dt.date):
    cpc = {"shapefiles": [], "maps": [], "discussions": []}
    workdir = Path(tempfile.mkdtemp(prefix="cpc_"))
    try:
        for fname, label in CPC_SHORTRANGE:
            url = f"{CPC_GIS_BASE}/{fname}"
            cpc["shapefiles"].append(_sample_shapefile_archive(url, lat, lon, label, workdir))

        # Monthly & seasonal long-lead outlooks, keyed by issuance year-month.
        for ym in [today.strftime("%Y%m"),
                   (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")]:
            for kind, label in (("seasprcp", "Monthly & Seasonal Precipitation Outlook"),
                                ("seastemp", "Monthly & Seasonal Temperature Outlook")):
                url = f"{CPC_GIS_BASE}/{kind}_{ym}.zip"
                out = _sample_shapefile_archive(url, lat, lon, f"{label} (issued {ym})", workdir)
                out["issuance_ym"] = ym
                cpc["shapefiles"].append(out)

        # Latest monthly update (end-of-month release)
        for kind, label in (("monthupd_prcp", "Latest Monthly Update - Precipitation"),
                            ("monthupd_temp", "Latest Monthly Update - Temperature")):
            url = f"{CPC_GIS_BASE}/monthlyupdate/{kind}_latest.zip"
            cpc["shapefiles"].append(_sample_shapefile_archive(url, lat, lon, label, workdir))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # official maps (archived copies so the site never hot-links live assets)
    assets_dir.mkdir(parents=True, exist_ok=True)
    for label, slug, candidates in CPC_MAP_IMAGES:
        chosen, res = None, None
        for url in candidates:
            attempt = fetchlib.get(url, timeout=120)
            record(attempt, note=f"CPC official outlook map (candidate): {label}")
            if attempt.ok and attempt.body and attempt.size > 500 and attempt.body[:3] == b"GIF":
                chosen, res = url, attempt
                break
            res = res or attempt
        entry = {"label": label, "slug": slug, "candidates": candidates,
                 "url": chosen, "sha256": (res.sha256 if res else None),
                 "bytes": (res.size if res else 0),
                 "retrieved_utc": (res.retrieved_utc if res else None),
                 "ok": bool(chosen)}
        if chosen:
            sha = fetchlib.save_bytes(assets_dir / f"{slug}.gif", res.body)
            entry["local_path"] = f"assets/cpc/{slug}.gif"
            entry["sha256"] = sha
        else:
            entry["status"] = res.status if res else None
            note_irregularity("warning", "cpc",
                              f"No CPC map image could be archived for: {label}",
                              {"candidates": candidates})
        cpc["maps"].append(entry)

    # official discussion text
    for label, url, human in CPC_DISCUSSIONS:
        text, res = fetchlib.get_text(url, timeout=120)
        record(res, note=f"CPC outlook discussion: {label}")
        if res.ok:
            plain = html_to_text(text)
            entry = {
                "label": label, "url": url, "human_url": human,
                "ok": True, "sha256": res.sha256,
                "retrieved_utc": res.retrieved_utc,
                "characters": len(plain),
                "text": plain[:20000],
            }
            # Staleness guard: an official outlook page must reference the
            # current year.  A page that does not is treated as stale and its
            # text is NOT published (CPC still serves some long-dead pages).
            year_hits = plain.count(str(today.year))
            entry["current_year_mentions"] = year_hits
            if year_hits == 0:
                entry["stale"] = True
                entry["text"] = ""
                note_irregularity("warning", "cpc",
                                  f"CPC discussion '{label}' never mentions {today.year}; "
                                  "treated as a stale page and its text was discarded.",
                                  {"url": url})
            cpc["discussions"].append(entry)
        else:
            cpc["discussions"].append({"label": label, "url": url, "human_url": human,
                                       "ok": False, "status": res.status, "error": res.error})
            note_irregularity("warning", "cpc",
                              f"CPC discussion could not be retrieved: {label}",
                              {"url": url, "status": res.status})

    # valid-period strings scraped from the 6-10/8-14 landing pages
    for url, key in (("https://www.cpc.ncep.noaa.gov/products/predictions/610day/", "610day"),
                     ("https://www.cpc.ncep.noaa.gov/products/predictions/814day/", "814day"),
                     ("https://www.cpc.ncep.noaa.gov/products/predictions/30day/", "30day"),
                     ("https://www.cpc.ncep.noaa.gov/products/predictions/90day/", "90day")):
        text, res = fetchlib.get_text(url, timeout=120)
        record(res, note=f"CPC landing page (valid period metadata): {key}")
        if not res.ok:
            continue
        plain = html_to_text(text)
        m_valid = re.search(r"Valid:\s*([^\n<]{4,80})", plain)
        m_upd = re.search(r"(?:Updated|Issued):\s*([^\n<]{4,80})", plain)
        cpc.setdefault("valid_periods", {})[key] = {
            "valid": m_valid.group(1).strip() if m_valid else None,
            "issued": m_upd.group(1).strip() if m_upd else None,
            "url": url,
        }
    return cpc


# ==========================================================================
# 4.  ENSO (official CPC Niño 3.4 table + diagnostic discussion)
# ==========================================================================

def extract_key_sentences(text, limit=14):
    """Pull the verbatim official sentences that carry the numbers we quote.

    Nothing is paraphrased: each returned item is an exact substring of the
    official product, so a reviewer can Ctrl-F it in the source page.  Sentences
    are selected on keywords that matter to this project (ENSO strength, the
    odds of a strong event, and the seasonal temperature/precipitation tilt).
    """
    flat = re.sub(r"\s+", " ", text or " ")
    sentences = re.split(r"(?<=[.;])\s+", flat)
    keys = ("nino", "niño", "el niño", "el nino", "la niña", "oni", "chance",
            "percent", "%", "above normal", "below normal", "above median",
            "precipitation", "temperature outlook", "wetter", "drier", "historic")
    picked, seen = [], set()
    for s in sentences:
        s = s.strip(" |")
        low = s.lower()
        if len(s) < 30 or len(s) > 420:
            continue
        if not any(k in low for k in keys):
            continue
        if re.match(r"^(http|www)", low):
            continue
        key = s[:80]
        if key in seen:
            continue
        seen.add(key)
        picked.append(s)
        if len(picked) >= limit:
            break
    return picked


def fetch_enso():
    out = {}
    # ------------------------------------------------------------------
    # 1. NOAA's *published* ONI product.  The site shows this directly so the
    #    number a reader sees is the number NOAA publishes (season-labelled).
    # ------------------------------------------------------------------
    oni_url = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
    oni_text, oni_res = fetchlib.get_text(oni_url, timeout=120)
    record(oni_res, note="CPC official Oceanic Nino Index (ONI) product, season-labelled")
    official_rows = []
    if oni_res.ok and oni_text:
        official_rows = climo.parse_oni_seasons(oni_text)
        out["official_oni"] = {
            "url": oni_url,
            "sha256": oni_res.sha256,
            "retrieved_utc": oni_res.retrieved_utc,
            "definition": ("ONI = 3-month running mean of ERSSTv5 sea-surface temperature "
                           "anomalies in the Nino 3.4 region; NOAA declares El Nino at "
                           ">= +0.5 C and La Nina at <= -0.5 C."),
            "seasons": official_rows[-14:],
            "latest": None,
        }
        if official_rows:
            last = official_rows[-1]
            out["official_oni"]["latest"] = {
                "label": last["label"],
                "season": last["season"],
                "year": last["year"],
                "oni_c": last["anomaly_c"],
                "phase": climo.enso_phase(last["anomaly_c"]),
                "strength": climo.enso_strength(last["anomaly_c"]),
            }
    else:
        note_irregularity("error", "enso",
                          "The official CPC ONI product could not be retrieved; the site "
                          "falls back to the project's own 3-month running mean and says so.",
                          {"url": oni_url, "status": oni_res.status})

    # ------------------------------------------------------------------
    # 2. Cross-check: this project used to derive ONI from the detrended
    #    monthly Nino 3.4 table.  That derivation is kept as an independent
    #    check on the published product - if the two disagree, the difference
    #    is published instead of being hidden.
    # ------------------------------------------------------------------
    url = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt"
    text, res = fetchlib.get_text(url, timeout=120)
    record(res, note="CPC Nino 3.4 (ERSSTv5, detrended) monthly anomaly table")
    if not res.ok:
        note_irregularity("error", "enso", "Could not retrieve the CPC Nino 3.4 table.",
                          {"url": url, "status": res.status})
    else:
        nino = climo.parse_nino34(text)
        # ONI = 3-month running mean (NOAA CPC definition)
        oni = {}
        for (y, m), _a in sorted(nino.items()):
            trio = []
            for k in (-1, 0, 1):
                mm, yy = m + k, y
                while mm < 1:
                    mm += 12
                    yy -= 1
                while mm > 12:
                    mm -= 12
                    yy += 1
                if (yy, mm) in nino:
                    trio.append(nino[(yy, mm)])
            if len(trio) == 3:
                oni[(y, m)] = sum(trio) / 3.0

        latest = sorted(oni)[-6:]
        out["oni_table_url"] = url
        out["oni_table_sha256"] = res.sha256
        out["oni_definition"] = ("ONI = 3-month running mean of ERSSTv5 Nino 3.4 SST anomalies "
                                 "(NOAA CPC). El Nino >= +0.5, La Nina <= -0.5.")
        out["derived_oni_note"] = (
            "3-month running mean computed by this project from the detrended monthly "
            "Nino 3.4 table, labelled by the middle month. Used only as a cross-check on "
            "the official season-labelled ONI product.")
        out["recent_oni_derived"] = [
            {"year_month": f"{y:04d}-{m:02d}", "oni_c": round(oni[(y, m)], 2),
             "phase": climo.enso_phase(oni[(y, m)])}
            for (y, m) in latest
        ]
        out["oni_series"] = {f"{y:04d}-{m:02d}": round(v, 3) for (y, m), v in sorted(oni.items())}
        out["nino34_raw_last12"] = [
            {"year_month": f"{y:04d}-{m:02d}", "anomaly_c": v}
            for (y, m), v in sorted(nino.items())[-12:]
        ]
        if latest:
            last = oni[latest[-1]]
            out["latest_oni_derived"] = {
                "year_month": f"{latest[-1][0]:04d}-{latest[-1][1]:02d}",
                "oni_c": round(last, 2), "phase": climo.enso_phase(last)}

        # Compare the derived centred mean with the official season that covers
        # the same three months, and publish the difference.
        cross = {"checked": False}
        if official_rows and latest:
            y, m = latest[-1]
            trio_months = []
            for k in (-1, 0, 1):
                mm, yy = m + k, y
                while mm < 1:
                    mm += 12
                    yy -= 1
                while mm > 12:
                    mm -= 12
                    yy += 1
                trio_months.append((yy, mm))
            for row in official_rows:
                if [tuple(x) for x in row["months"]] == trio_months:
                    derived = oni[(y, m)]
                    cross = {
                        "checked": True,
                        "months": f"{trio_months[0][0]}-{trio_months[0][1]:02d} .. "
                                  f"{trio_months[-1][0]}-{trio_months[-1][1]:02d}",
                        "season_label": row["label"],
                        "derived_oni_c": round(derived, 2),
                        "official_oni_c": row["anomaly_c"],
                        "difference_c": round(derived - row["anomaly_c"], 2),
                    }
                    if abs(derived - row["anomaly_c"]) > 0.15:
                        note_irregularity(
                            "warning", "enso",
                            "The 3-month mean computed here from the detrended monthly table "
                            f"differs from NOAA's published ONI for {row['label']} by "
                            f"{cross['difference_c']} C. The published ONI is what the site "
                            "displays; the difference is likely a revision between the two "
                            "products.",
                            cross)
                    break
        out["oni_cross_check"] = cross

    # ------------------------------------------------------------------
    # 3. The current ENSO statement, taken verbatim from the official sources.
    #    The ENSO Diagnostic Discussion is the authoritative monthly status
    #    (it carries the Alert System Status), so it is checked first; the
    #    long-lead discussion is stored as well because it is the seasonal
    #    outlook a landlord actually cares about.
    # ------------------------------------------------------------------
    disc_candidates = [
        ("https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
         "html", "CPC ENSO Diagnostic Discussion (monthly status + Alert System Status)"),
        ("https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html",
         "html", "CPC long-lead (monthly/seasonal) outlook discussion"),
        ("https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/lanina/enso_evolution-status-fcsts-web.pdf",
         "pdf", "CPC ENSO evolution / status / forecast (PDF)"),
        ("https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php",
         "html", "CPC ONI_v5 page (interactive; not machine-readable)"),
    ]
    rejected = []
    year_now = dt.date.today().year
    for durl, kind, label in disc_candidates:
        dtext, dres = fetchlib.get_text(durl, timeout=120)
        record(dres, note=f"CPC ENSO / long-lead source candidate: {label}")
        if not (dres.ok and dres.body and dres.size > 400):
            rejected.append({"url": durl, "label": label,
                             "reason": f"fetch failed (status {dres.status})"})
            continue
        if kind == "pdf":
            rejected.append({"url": durl, "label": label,
                             "reason": "PDF - linked for manual review, text not parsed"})
            out.setdefault("reference_links", []).append({"label": label, "url": durl})
            continue
        plain = html_to_text(dtext)
        current = str(year_now) in plain
        entry = {
            "label": label, "url": durl, "sha256": dres.sha256,
            "retrieved_utc": dres.retrieved_utc, "characters": len(plain),
            "mentions_current_year": current,
        }
        if not current:
            # Two different situations look the same from the outside: a page
            # that is genuinely stale, and a page whose content is rendered by
            # client-side JavaScript.  Say which, and never quote it.
            entry["usable_as_current_source"] = False
            entry["reason"] = ("page text does not mention " + str(year_now) +
                               "; it is either stale or client-rendered, so it is not "
                               "used as evidence of current conditions")
            rejected.append({"url": durl, "label": label, "reason": entry["reason"]})
            out.setdefault("unusable_pages", []).append(entry)
            continue
        entry["usable_as_current_source"] = True
        entry["text"] = plain[:24000]
        # Keep the exact sentences that carry the numbers a reader will see.
        entry["key_sentences"] = extract_key_sentences(plain)
        # \w keeps accented letters ("El Niño Advisory"); the earlier [A-Za-z ]
        # class silently truncated it to "El Ni".
        status = re.search(r"ENSO Alert System Status:\s*([\w .\u2013-]{3,60})", plain)
        if status:
            entry["alert_status"] = re.sub(r"\s+", " ", status.group(1)).strip()
        syn = re.search(r"Synopsis:\s*(.{0,900}?)(?:El Ni|La Ni|$)", plain, re.S)
        if syn:
            entry["synopsis"] = re.sub(r"\s+", " ", syn.group(1)).strip()[:600]
        issued = re.search(r"(\d{1,2} [A-Z][a-z]+ \d{4})", plain)
        if issued:
            entry["issued"] = issued.group(1)
        out.setdefault("sources", []).append(entry)
        if "ensodisc" in durl:
            out["diagnostic_url"] = durl
            out["diagnostic_sha256"] = dres.sha256
            out["diagnostic_status"] = entry.get("alert_status")
            out["diagnostic_synopsis"] = entry.get("synopsis")
            out["diagnostic_key_sentences"] = entry["key_sentences"]
    out["discarded_enso_urls"] = rejected

    return out

# ==========================================================================
# 5.  NCEI archives - climate normals, GHCN-Daily, GSOD, Storm Events
# ==========================================================================

def fetch_ghcn(outdir: Path):
    """Download a GHCN-Daily station file and parse it.

    A short head of the raw file is always written to
    ``<outdir>/ghcn_probe.json`` so the exact format NCEI served can be
    reviewed line by line instead of assumed.
    """
    probe = {"candidates": []}
    for sid, name in GHCN_CANDIDATES:
        url = f"https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/{sid}.csv"
        res = fetchlib.get(url, timeout=600)
        record(res, note=f"NCEI GHCN-Daily station file: {sid} ({name})")
        if not (res.ok and res.body):
            probe["candidates"].append({"sid": sid, "ok": False, "status": res.status})
            continue
        text = res.text()
        parsed, fmt = climo.parse_ghcn_daily(text)
        lines = text.splitlines()
        keys = sorted(parsed)
        probe["candidates"].append({
            "sid": sid, "ok": True, "status": res.status, "bytes": res.size,
            "format": fmt, "n_lines": len(lines), "n_parsed_days": len(parsed),
            "date_range": [keys[0], keys[-1]] if keys else None,
            "first_lines_raw": [ln[:160] for ln in lines[:3]],
            "sample_parsed": {k: parsed[k] for k in keys[len(keys) // 2:len(keys) // 2 + 1]},
        })
        write_json(outdir / "ghcn_probe.json", probe)
        if parsed:
            return {"station_id": sid, "name": name, "url": url,
                    "sha256": res.sha256, "bytes": res.size, "format": fmt,
                    "data": parsed}
    write_json(outdir / "ghcn_probe.json", probe)
    note_irregularity("error", "ncei", "No GHCN-Daily station file could be retrieved.",
                      {"candidates": [c[0] for c in GHCN_CANDIDATES]})
    return None


def fetch_gsod(years):
    # Fetch the official GSOD README first: it is the authority for the unit
    # convention and the UTC-day caveat used by climo.parse_gsod.
    readme, rres = fetchlib.get_text(climo.GSOD_README_URL, timeout=120)
    record(rres, note="NCEI GSOD README - authoritative element units and missing-value flags")
    if not rres.ok:
        note_irregularity("warning", "ncei",
                          "GSOD README could not be retrieved; unit convention was "
                          "verified manually against the published documentation.",
                          {"url": climo.GSOD_README_URL, "status": rres.status})

    for sid, name in GSOD_STATIONS:
        rows_by_date = {}
        statuses = []
        for year in years:
            url = (f"https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/"
                   f"{year}/{sid}.csv")
            res = fetchlib.get(url, timeout=300)
            record(res, note=f"NCEI GSOD {year}: {sid}")
            statuses.append({"year": year, "status": res.status, "ok": res.ok})
            if res.ok and res.body:
                for r in climo.parse_gsod(res.text()):
                    rows_by_date[r["date"]] = r
        if rows_by_date:
            return {"station_id": sid, "name": name,
                    "base_url": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/",
                    "years_requested": [years[0], years[-1]],
                    "per_year": statuses, "days": len(rows_by_date),
                    "data": rows_by_date}
    note_irregularity("error", "ncei", "No GSOD station data could be retrieved.",
                      {"stations": [s[0] for s in GSOD_STATIONS]})
    return None


def fetch_daily_normals():
    """NCEI 1991-2020 U.S. Climate Normals (daily), if the path is available."""
    for sid, name in GHCN_CANDIDATES:
        url = f"https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/{sid}.csv"
        res = fetchlib.get(url, timeout=300)
        record(res, note=f"NCEI 1991-2020 Daily Climate Normals: {sid}")
        if res.ok and res.body:
            return {"station_id": sid, "url": url, "sha256": res.sha256,
                    "text": res.text()[:200000]}
    return None


def fetch_monthly_normals():
    """NCEI 1991-2020 *monthly* normals - an independent official cross-check.

    The project computes its own monthly rainfall means from GHCN-Daily.  This
    fetches NOAA's own published monthly normals for the same station so the two
    can be compared line by line, with any difference published rather than
    smoothed over.
    """
    for sid, name in GHCN_CANDIDATES:
        url = f"https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/{sid}.csv"
        res = fetchlib.get(url, timeout=300)
        record(res, note=f"NCEI 1991-2020 Monthly Climate Normals: {sid}")
        if not (res.ok and res.body):
            continue
        text = res.text()
        try:
            summary = climo.monthly_normals_summary(text)
        except Exception as exc:  # noqa: BLE001 - layout changes must not break the run
            note_irregularity("warning", "normals",
                              "The NCEI monthly-normals file could not be parsed; the "
                              "published cross-check is unavailable this run.",
                              {"url": url, "error": f"{type(exc).__name__}: {exc}",
                               "first_400_chars": text[:400]})
            continue
        summary.update({
            "station_id": sid,
            "station_name": name,
            "url": url,
            "sha256": res.sha256,
            "retrieved_utc": res.retrieved_utc,
            "source": "NOAA NCEI U.S. Climate Normals 1991-2020 (monthly, by station)",
        })
        return summary
    return None


def fetch_humidity_normals():
    """NCEI 1991-2020 hourly normals -> typical relative humidity by month.

    Relative humidity is not published as a normal, but NCEI publishes hourly
    temperature and dew-point normals; humidity is derived from those two with
    the standard Magnus formula and labelled as a derivation on the site.  If the
    file layout is not what the reader expects, the layout is recorded and no
    humidity value is produced - the project does not estimate.
    """
    for sid, name in GHCN_CANDIDATES:
        url = f"https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/{sid}.csv"
        res = fetchlib.get(url, timeout=300)
        record(res, note=f"NCEI 1991-2020 Hourly Climate Normals: {sid}")
        if not (res.ok and res.body):
            continue
        text = res.text()
        try:
            rows, info = climo.hourly_normals_rh_inputs(text)
        except Exception as exc:  # noqa: BLE001
            note_irregularity("warning", "normals",
                              f"Hourly normals for {sid} could not be parsed; daily "
                              "climatology days will not carry a humidity value.",
                              {"url": url, "error": f"{type(exc).__name__}: {exc}",
                               "first_400_chars": text[:400]})
            continue
        month_rh = climo.humidity_normals_from_hourly(rows) if rows else {}
        date_rh = climo.humidity_normals_by_date(rows) if rows else {}
        entry = {
            "station_id": sid,
            "station_name": name,
            "url": url,
            "sha256": res.sha256,
            "retrieved_utc": res.retrieved_utc,
            "source": "NOAA NCEI U.S. Climate Normals 1991-2020 (hourly, by station)",
            "method": ("mean of hourly relative humidity computed from the official hourly "
                       "temperature and dew-point normals with the Magnus formula"),
            "month_rh_pct": {str(k): v for k, v in month_rh.items()},
            # Preferred: one value per calendar date, if the file has a day column.
            "date_rh_pct": date_rh,
            "rows_used": len(rows),
            "layout": info,
        }
        if not month_rh:
            note_irregularity(
                "warning", "normals",
                "Hourly normals were downloaded but produced no humidity values; the "
                "column layout was recorded in data/humidity_normals.json for review. "
                "No humidity value is shown for climatology days rather than inventing one.",
                {"url": url, "layout": info})
        return entry
    note_irregularity("info", "normals",
                      "NCEI hourly normals were not reachable at the documented path; "
                      "climatology days carry no humidity value.",
                      {"tried": [f"https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/{s}.csv"
                                 for s, _ in GHCN_CANDIDATES]})
    return None


def fetch_storm_events(years):
    """NCEI Storm Events Database - county-level detail rows for San Francisco.

    San Francisco County, CA = FIPS 06075.  The files are large; only matching
    rows are retained so nothing bulky is committed back to the repository.
    """
    import csv as _csv
    import io as _io

    listing_url = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
    ltext, lres = fetchlib.get_text(listing_url, timeout=180)
    record(lres, note="NCEI Storm Events CSV directory listing")
    if not lres.ok:
        note_irregularity("warning", "storm_events",
                          "Storm Events directory listing unavailable; storm-event history "
                          "omitted from this run.", {"url": listing_url, "status": lres.status})
        return None

    links = re.findall(r'href="(StormEvents_details-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz)"', ltext)
    by_year = {}
    for fname, year, cdate in links:
        y = int(year)
        if y in by_year and int(cdate) <= int(by_year[y][1]):
            continue
        by_year[y] = (fname, cdate)

    events, files_used = [], []
    for year in sorted(by_year, reverse=True):
        if year not in years:
            continue
        fname, cdate = by_year[year]
        url = listing_url + fname
        res = fetchlib.get(url, timeout=600)
        record(res, note=f"NCEI Storm Events details file {year}")
        if not res.ok:
            continue
        files_used.append({"year": year, "file": fname, "url": url,
                           "sha256": res.sha256, "bytes": res.size})
        try:
            raw = fetchlib.gunzip(res.body)
        except Exception as exc:  # noqa: BLE001
            note_irregularity("warning", "storm_events",
                              f"Could not decompress Storm Events file {fname}: {exc}", {})
            continue
        reader = _csv.DictReader(_io.StringIO(raw.decode("utf-8", "replace")))
        for row in reader:
            cz = (row.get("CZ_FIPS") or "").strip()
            cz_name = (row.get("CZ_NAME") or "").strip()
            state = (row.get("STATE") or "").strip()
            cz_type = (row.get("CZ_TYPE") or "").strip().upper()
            # County rows (CZ_TYPE == 'C') carry the county FIPS in CZ_FIPS.
            # San Francisco County, CA = FIPS 06075 -> county code 75.
            is_sf = (
                cz_type == "C"
                and (state.upper().startswith("CALIFORNIA") or state.upper() == "CA")
                and cz.lstrip("0") == "75"
            )
            if not is_sf:
                continue
            events.append({
                "event_id": row.get("EVENT_ID"),
                "event_type": row.get("EVENT_TYPE"),
                "begin_date": row.get("BEGIN_DATE_TIME"),
                "end_date": row.get("END_DATE_TIME"),
                "cz_name": cz_name,
                "cz_type": row.get("CZ_TYPE"),
                "cz_fips": cz,
                "magnitude": row.get("MAGNITUDE"),
                "magnitude_type": row.get("MAGNITUDE_TYPE"),
                "damage_property": row.get("DAMAGE_PROPERTY"),
                "damage_crops": row.get("DAMAGE_CROPS"),
                "injuries_direct": row.get("INJURIES_DIRECT"),
                "deaths_direct": row.get("DEATHS_DIRECT"),
                "event_narrative": (row.get("EVENT_NARRATIVE") or "")[:900],
                "episode_narrative": (row.get("EPISODE_NARRATIVE") or "")[:900],
            })
    if not events:
        note_irregularity("warning", "storm_events",
                          "Storm Events files were reachable but no rows matched San "
                          "Francisco County in the requested years.",
                          {"years": sorted(years), "files": files_used[:3]})
    events.sort(key=lambda e: (e.get("begin_date") or ""), reverse=True)
    return {"county": "San Francisco County, CA (FIPS 06075)",
            "years": sorted(years), "files_used": files_used,
            "n_events": len(events), "events": events[:400],
            "source": "NOAA NCEI Storm Events Database",
            "human_url": "https://www.ncdc.noaa.gov/stormevents/"}


# ==========================================================================
# main
# ==========================================================================

def main():
    global _LOG_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="data")
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = outdir / "pipeline.log"
    if _LOG_PATH.exists():
        _LOG_PATH.unlink()

    today = dt.datetime.now(dt.timezone.utc).date()
    log(f"SFWeather pipeline - {today.isoformat()}")

    assets_dir = Path("assets/cpc")

    log("[1/7] ZIP centroid (U.S. Census Bureau)")
    centroid = fetch_zip_centroid()
    lat, lon = centroid["lat"], centroid["lon"]
    log(f"      94122 centroid: {lat:.4f}, {lon:.4f} ({'verified' if centroid.get('verified') else 'FALLBACK'})")

    log("[2/7] NWS (api.weather.gov)")
    nws = fetch_nws(lat, lon)

    log("[3/7] CPC outlooks")
    cpc = fetch_cpc(lat, lon, assets_dir, today)

    log("[4/7] ENSO / ONI")
    enso = fetch_enso()

    log("[5/7] NCEI climatology archives")
    ghcn = fetch_ghcn(outdir)
    if ghcn:
        days = ghcn["data"]
        keys = sorted(days)
        log(f"      GHCN {ghcn['station_id']}: {len(days)} station-days parsed; "
            f"range {keys[0] if keys else 'n/a'} .. {keys[-1] if keys else 'n/a'}")
        if keys:
            log(f"      sample record: {keys[len(keys)//2]} -> {days[keys[len(keys)//2]]}")
        else:
            note_irregularity("error", "climatology",
                              "The GHCN-Daily station file parsed to zero usable rows; the "
                              "rain climatology is unavailable.",
                              {"station": ghcn["station_id"], "url": ghcn["url"],
                               "bytes": ghcn["bytes"]})
    gsod_years = list(range(1991, today.year))
    gsod = fetch_gsod(gsod_years)
    normals = fetch_daily_normals()
    monthly_normals = fetch_monthly_normals()
    humidity_normals = fetch_humidity_normals()

    # season calendar days
    season_month_days = []
    d = dt.date(2026, 10, 1)
    end = dt.date(2027, 1, 31)
    while d <= end:
        season_month_days.append((d.month, d.day))
        d += dt.timedelta(days=1)

    climo_out = {}
    if ghcn and gsod:
        log("[6/7] computing rainy-season climatology")
        oni_series = {}
        if enso.get("oni_series"):
            for k, v in enso["oni_series"].items():
                y, m = int(k[:4]), int(k[5:7])
                oni_series[(y, m)] = v
        climo_out["daily"] = climo.build_daily_climatology(
            ghcn["data"], gsod["data"], season_month_days, NORMALS_PERIOD)
        climo_out["season"] = climo.build_season_statistics(
            ghcn["data"], gsod["data"], season_month_days, NORMALS_PERIOD, oni_series,
            oni_seasons=(enso.get("official_oni") or {}).get("seasons") or None)
        climo_out["meta"] = {
            "normals_period": list(NORMALS_PERIOD),
            "season": SEASON,
            "precip_station": {"id": ghcn["station_id"], "name": ghcn["name"], "url": ghcn["url"]},
            "wind_station": {"id": gsod["station_id"], "name": gsod["name"],
                             "url": gsod["base_url"]},
            "unit_authority": {"gsod_readme": climo.GSOD_README_URL},
            "units": {
                "precip": "inches (liquid)",
                "temp": "degrees Fahrenheit",
                "wind": "miles per hour (converted from GSOD knots, 1 kt = 1.15078 mph)",
            },
            "caveats": [
                "GSOD (wind) days are UTC days (0000Z-2359Z), i.e. roughly 16:00-16:00 "
                "local time in San Francisco, whereas GHCN-Daily (rain) days are local "
                "days. The joint wind-and-rain statistics therefore pair a local-day rain "
                "total with a UTC-day wind figure for the same calendar date. This is an "
                "approximation and is stated rather than hidden.",
                "Wind data come from the SFO ASOS (KSFO), about 10 miles south-east of "
                "94122. Exposure at SFO is more open than in the Sunset, so wind speeds "
                "there are typically higher than at the ZIP code itself.",
                "GSOD 'MAX'/'MIN' are the reported daily extremes, which per NCEI are not "
                "always the true calendar-day extremes.",
                "Percentages for a single calendar date are computed from 30 seasons "
                "(1991-2020). One season adds or subtracts about 3.3 percentage points, so "
                "treat single-date percentages as indicative, not precise.",
            ],
            "definitions": {
                "wet_day": "calendar day with >= 0.01 in of liquid precipitation",
                "wet_streak": "consecutive wet days within Oct 1 - Jan 31",
                "wind_and_rain_day": "SFO ASOS daily max sustained wind >= 20 kt AND precip >= 0.01 in",
                "heavy_wind_and_rain_day": "SFO ASOS max gust >= 35 kt AND precip >= 0.50 in",
            },
        }
        # Data-completeness checks
        thin = [d_ for d_ in climo_out["daily"]
                if (d_["n_years_precip"] or 0) < 25 or (d_["n_years_wind"] or 0) < 25]
        if thin:
            note_irregularity("warning", "climatology",
                              f"{len(thin)} calendar dates have fewer than 25 years of data "
                              "in the 1991-2020 window; their percentages are less reliable.",
                              {"dates": [d_["mmdd"] for d_ in thin][:40]})
    else:
        note_irregularity("error", "climatology",
                          "Climatology could not be computed because an NCEI archive was "
                          "unavailable.", {"ghcn": bool(ghcn), "gsod": bool(gsod)})

    log("[7/7] Storm Events + writing outputs")
    storm = fetch_storm_events(set(range(today.year - 12, today.year + 1)))

    run = {
        "generated_utc": fetchlib.iso_utc(),
        "pipeline_version": "1.0",
        "target": {**TARGET, "centroid": centroid},
        "season": SEASON,
        "normals_period": list(NORMALS_PERIOD),
        "counts": {
            "manifest_entries": len(MANIFEST),
            "successful_fetches": sum(1 for m in MANIFEST if m["ok"]),
            "failed_fetches": sum(1 for m in MANIFEST if not m["ok"]),
            "irregularities": len(IRREGULARITIES),
        },
    }

    write_json(outdir / "run.json", run)
    write_json(outdir / "nws.json", nws)
    write_json(outdir / "cpc.json", cpc)
    write_json(outdir / "enso.json", enso)
    write_json(outdir / "climatology.json", climo_out)
    if storm:
        write_json(outdir / "storm_events.json", storm)
    if normals:
        write_json(outdir / "daily_normals.json", normals)
    if monthly_normals:
        write_json(outdir / "monthly_normals.json", monthly_normals)
    if humidity_normals:
        write_json(outdir / "humidity_normals.json", humidity_normals)
    write_json(outdir / "provenance.json", {
        "generated_utc": fetchlib.iso_utc(),
        "note": "Every value in this repository comes from one of the URLs below.",
        "entries": MANIFEST,
    })
    write_json(outdir / "quality_report.json", {
        "generated_utc": fetchlib.iso_utc(),
        "counts": {
            "total": len(IRREGULARITIES),
            "errors": sum(1 for i in IRREGULARITIES if i["severity"] == "error"),
            "warnings": sum(1 for i in IRREGULARITIES if i["severity"] == "warning"),
            "info": sum(1 for i in IRREGULARITIES if i["severity"] == "info"),
        },
        "irregularities": IRREGULARITIES,
    })

    log("\n=== summary ===")
    # A compact, human-readable digest is written next to the JSON so the
    # numbers can be checked at a glance (and from anywhere) without parsing
    # the large datasets.
    lines = [
        "SFWeather - rainy season digest",
        f"generated_utc: {run['generated_utc']}",
        f"target: 94122  centroid {centroid['lat']:.4f}, {centroid['lon']:.4f}  "
        f"(verified={centroid.get('verified')}) source={centroid.get('source')}",
        "",
    ]
    if climo_out.get("meta"):
        m = climo_out["meta"]
        lines += [
            "STATIONS",
            f"  rain/temp: {m['precip_station']['id']}  {m['precip_station']['name']}",
            f"             {m['precip_station']['url']}",
            f"  wind:      {m['wind_station']['id']}  {m['wind_station']['name']}",
            f"             {m['wind_station']['url']}",
            f"  normals period: {m['normals_period'][0]}-{m['normals_period'][1]}",
            "",
        ]
    dist = climo_out.get("season", {}).get("distribution", {})
    if dist:
        lines.append("MONTHLY / SEASONAL RAINFALL (inches, 1991-2020)")
        for label, key in (("October", "october_total_prcp_in"),
                           ("November", "november_total_prcp_in"),
                           ("December", "december_total_prcp_in"),
                           ("January", "january_total_prcp_in"),
                           ("Oct 1 - Jan 31 total", "season_total_prcp_in")):
            d = dist.get(key) or {}
            if d:
                lines.append(f"  {label:22s} mean {d['mean']:>6}  median {d['median']:>6}  "
                             f"min {d['min']:>6}  max {d['max']:>6}  p10 {d['p10']:>6}  p90 {d['p90']:>6}")
        lines.append("")
        streaks = climo_out.get("season", {}).get("probability_of_at_least_one_streak", {})
        if streaks:
            lines.append("LONG WET STREAKS (consecutive days >= 0.01 in, Oct 1 - Jan 31)")
            for k, v in streaks.items():
                lines.append(f"  at least one run >= {k.replace('ge_','').replace('_days','')} days: "
                             f"{v['pct']}% of {NORMALS_PERIOD[1]-NORMALS_PERIOD[0]+1} seasons "
                             f"({v['seasons']} seasons)")
            lws = dist.get("longest_wet_streak_days") or {}
            if lws:
                lines.append(f"  longest run per season: mean {lws['mean']}  median {lws['median']}  "
                             f"min {lws['min']}  max {lws['max']}")
            lines.append("")
        wd = dist.get("wet_days") or {}
        if wd:
            lines.append(f"WET DAYS per season: mean {wd['mean']}  median {wd['median']}  "
                         f"min {wd['min']}  max {wd['max']}")
        jr = dist.get("wind_and_rain_days") or {}
        hj = dist.get("heavy_wind_and_rain_days") or {}
        mg = dist.get("max_gust_mph") or {}
        if jr:
            lines.append(f"WIND+RAIN DAYS per season (SFO, >=20kt & >=0.01in): mean {jr['mean']}  "
                         f"median {jr['median']}  max {jr['max']}")
        if hj:
            lines.append(f"HEAVY wind+rain days (>=35kt gust & >=0.50in): mean {hj['mean']}  "
                         f"median {hj['median']}  max {hj['max']}")
        if mg:
            lines.append(f"SEASON MAX GUST (mph, SFO): mean {mg['mean']}  median {mg['median']}  max {mg['max']}")
        lines.append("")
        en = climo_out.get("season", {}).get("enso_stratified_season_total_prcp_in", {})
        if en:
            lines.append("OCT-JAN TOTAL RAINFALL BY ENSO PHASE (inches)")
            for phase, d in en.items():
                if d:
                    lines.append(f"  {phase:10s} n={d.get('n')}  mean {d.get('mean')}  "
                                 f"median {d.get('median')}  min {d.get('min')}  max {d.get('max')}")
            lines.append("")
    if enso.get("latest_oni"):
        lines += ["ENSO (NOAA CPC ONI)",
                  f"  latest: {enso['latest_oni']['year_month']}  ONI {enso['latest_oni']['oni_c']} C  "
                  f"({enso['latest_oni']['phase']})",
                  f"  table: {enso.get('oni_table_url')}", ""]
    ws = climo_out.get("season", {}).get("wettest_seasons") or []
    ds = climo_out.get("season", {}).get("driest_seasons") or []
    if ws:
        lines.append("WETTEST Oct-Jan seasons: " + ", ".join(f"{w['season']} {w['total_prcp_in']}in" for w in ws))
    if ds:
        lines.append("DRIEST  Oct-Jan seasons: " + ", ".join(f"{w['season']} {w['total_prcp_in']}in" for w in ds))
        lines.append("")
    lines.append(f"FETCHES: {run['counts']['successful_fetches']} ok / {run['counts']['failed_fetches']} failed")
    lines.append(f"IRREGULARITIES: {run['counts']['irregularities']}")
    for i in IRREGULARITIES:
        lines.append(f"  [{i['severity']}] {i['area']}: {i['message']}")
    (outdir / "summary.txt").write_text("\n".join(lines) + "\n")

    log(f"  fetches: {run['counts']['successful_fetches']} ok / "
        f"{run['counts']['failed_fetches']} failed")
    log(f"  irregularities: {run['counts']['irregularities']}")
    for i in IRREGULARITIES:
        log(f"    [{i['severity']}] {i['area']}: {i['message'][:200]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - surface the traceback in the committed log
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        try:
            log("FATAL: uncaught exception")
            log(tb)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
