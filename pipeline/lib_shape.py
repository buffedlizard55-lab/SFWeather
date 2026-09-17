"""Minimal, dependency-free ESRI Shapefile reader.

Used to point-sample NOAA Climate Prediction Center (CPC) outlook shapefiles at
the 94122 centroid.  Only what CPC actually ships is implemented:

* PolygonZ / Polygon / PolygonM shape types (5, 15, 25)
* DBF attribute tables (C/N/F/D/L fields)

The projection is read from the sibling ``.prj`` file.  CPC's CONUS outlook
shapefiles are published in geographic coordinates, so a plain lon/lat
point-in-polygon test is used; if the .prj says anything other than a
geographic CRS, the caller is warned instead of silently guessing.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

# --------------------------------------------------------------------------
# .shp
# --------------------------------------------------------------------------

SHAPE_NAMES = {0: "Null", 1: "Point", 3: "PolyLine", 5: "Polygon",
               8: "MultiPoint", 11: "PointZ", 13: "PolyLineZ",
               15: "PolygonZ", 18: "MultiPointZ", 21: "PointM",
               23: "PolyLineM", 25: "PolygonM", 31: "MultiPatch"}


class Shape:
    __slots__ = ("shape_type", "bbox", "rings")

    def __init__(self, shape_type, bbox, rings):
        self.shape_type = shape_type
        self.bbox = bbox
        self.rings = rings      # list of rings; ring = list of (x, y)


def read_shp(path: Path):
    """Return ``(shape_type_name, [Shape, ...])``."""
    data = path.read_bytes()
    if len(data) < 100:
        raise ValueError(f"{path}: file too short to be a shapefile")
    _code, _len, _ver, shp_type = struct.unpack(">4i", data[0:16])
    shapes = []
    off = 100
    n = len(data)
    while off + 8 <= n:
        rec_num, content_len = struct.unpack(">2i", data[off:off + 8])
        content_len_words = content_len
        body = data[off + 8: off + 8 + content_len_words * 2]
        if len(body) < 4:
            break
        st = struct.unpack("<i", body[0:4])[0]
        if st == 0:                                   # null shape
            shapes.append(Shape(st, None, []))
        elif st in (5, 15, 25):                       # polygon family
            xmin, ymin, xmax, ymax = struct.unpack("<4d", body[4:36])
            nparts, npoints = struct.unpack("<2i", body[36:44])
            p = 44
            parts = list(struct.unpack(f"<{nparts}i", body[p:p + 4 * nparts]))
            p += 4 * nparts
            flat = struct.unpack(f"<{2 * npoints}d", body[p:p + 16 * npoints])
            pts = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
            rings = []
            starts = list(parts) + [npoints]
            for i in range(nparts):
                rings.append(pts[starts[i]:starts[i + 1]])
            shapes.append(Shape(st, (xmin, ymin, xmax, ymax), rings))
        else:
            shapes.append(Shape(st, None, []))
        off += 8 + content_len_words * 2
    return SHAPE_NAMES.get(shp_type, f"Unknown({shp_type})"), shapes


# --------------------------------------------------------------------------
# .dbf
# --------------------------------------------------------------------------

def read_dbf(path: Path):
    """Return ``(field_names, [row_dict, ...])``."""
    data = path.read_bytes()
    if len(data) < 32:
        raise ValueError(f"{path}: file too short to be a DBF")
    nrec, hdr_len, rec_len = struct.unpack("<IHH", data[4:12])
    fields = []
    off = 32
    while off < len(data) and data[off] != 0x0D:
        raw = data[off:off + 32]
        if len(raw) < 32:
            break
        name = raw[0:11].split(b"\x00")[0].decode("ascii", "replace").strip()
        ftype = chr(raw[11])
        flen = raw[16]
        fdec = raw[17]
        fields.append((name, ftype, flen, fdec))
        off += 32
    terminator = off
    rows = []
    for i in range(nrec):
        start = terminator + 1 + i * rec_len
        rec = data[start:start + rec_len]
        if not rec or rec[0:1] in (b"*",):        # deleted
            continue
        row = {}
        p = 1
        for name, ftype, flen, _fdec in fields:
            raw = rec[p:p + flen]
            p += flen
            val = raw.decode("ascii", "replace").strip()
            if ftype in ("N", "F") and val not in ("",):
                try:
                    val = float(val) if "." in val else int(val)
                except ValueError:
                    pass
            elif ftype == "L":
                val = val.upper() in ("T", "Y", "1")
            if val == "":
                val = None
            row[name] = val
        rows.append(row)
    return [f[0] for f in fields], rows


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

def point_in_ring(x, y, ring):
    """Ray-casting test for a single ring."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            xint = xi + (y - yi) / (yj - yi) * (xj - xi)
            if x < xint:
                inside = not inside
        j = i
    return inside


def point_in_polygon(x, y, rings):
    """Even-odd test across all rings (handles holes)."""
    count = sum(1 for r in rings if point_in_ring(x, y, r))
    return (count % 2) == 1


def bbox_contains(bbox, x, y):
    if not bbox:
        return True
    xmin, ymin, xmax, ymax = bbox
    return xmin <= x <= xmax and ymin <= y <= ymax


# --------------------------------------------------------------------------
# zip handling
# --------------------------------------------------------------------------

def extract_shapefile(zip_path: Path, workdir: Path):
    """Extract a shapefile bundle from *zip_path* into *workdir*.

    Returns a dict with the resolved ``.shp`` / ``.dbf`` / ``.prj`` paths and
    the list of files that were inside the archive.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        zf.extractall(workdir)

    def find(ext):
        for nm in names:
            if nm.lower().endswith(ext):
                p = workdir / nm
                if p.exists():
                    return p
        # fall back: scan workdir
        for p in sorted(workdir.rglob("*" + ext)):
            return p
        return None

    return {
        "archive": str(zip_path),
        "members": names,
        "shp": find(".shp"),
        "dbf": find(".dbf"),
        "prj": find(".prj"),
    }


def extract_all_shapefiles(zip_path: Path, workdir: Path):
    """Extract every shapefile bundle inside a CPC outlook ZIP.

    CPC's monthly/seasonal archives hold one shapefile per lead (for example
    ``lead1_SON_temp.shp``, ``lead2_OND_temp.shp`` ...).  Sampling only the
    first one silently throws away 13 of the 14 official outlooks, so this
    returns every bundle found.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        zf.extractall(workdir)

    bundles = []
    stems = sorted({Path(n).stem for n in names if n.lower().endswith(".shp")})
    for stem in stems:
        def find(ext):
            cand = workdir / f"{stem}{ext}"
            return cand if cand.exists() else None
        bundles.append({
            "stem": stem,
            "shp": find(".shp"),
            "dbf": find(".dbf"),
            "prj": find(".prj") or find(".PRJ"),
        })
    return {"archive": str(zip_path), "members": names, "bundles": bundles}


def read_prj(path):
    if not path or not Path(path).exists():
        return None
    return Path(path).read_text(errors="replace").strip()


def is_geographic(prj_text):
    """True when the CRS looks like unprojected lat/lon (what CPC ships)."""
    if not prj_text:
        return None
    low = prj_text.lower()
    if "projected" in low or "projcs" in low:
        return False
    if "geogcs" in low or "geographic" in low or low.startswith("geogcrs"):
        return True
    return None
