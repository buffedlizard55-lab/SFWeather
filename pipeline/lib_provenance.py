"""Provenance manifest handling shared by the pipeline and the ledger.

The nightly pipeline writes ``data/provenance.json`` and *nothing else may touch
it*: ``data/run.json`` publishes the entry count and the ok/failed/absent
split, and the claim ledger fails the run if those counts do not recount exactly
from that file.  A second script appending rows would desynchronise them and
silently stop the nightly publish.

So every auxiliary script (the CPC back-test, the NCEI archive probe, the model
guidance tier, the AFD history) writes **its own** manifest, named
``data/<area>_provenance.json`` with the same ``{"entries": [...]}`` shape.  This
module is the single place that knows the convention:

* :func:`manifest_paths` - the ordered list of manifests in a data directory;
* :func:`load_entries` - every recorded fetch across all of them;
* :func:`write_manifest` - idempotent write of one auxiliary manifest.

The ledger's traceability rule ("every URL printed on the site was actually
fetched, with a status, a byte count and a SHA-256") is evaluated over the union
of all manifests, so a link published by a new script is held to exactly the same
standard as one published by the nightly pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The nightly pipeline's manifest.  Written only by ``pipeline/main.py``.
PRIMARY = "provenance.json"

#: Suffix every auxiliary manifest must use, so they can be found by convention
#: rather than by a hard-coded list that a new script would forget to update.
SUFFIX = "_provenance.json"


def manifest_paths(data_dir):
    """Ordered manifest files in *data_dir*: the primary one first."""
    data_dir = Path(data_dir)
    out = []
    primary = data_dir / PRIMARY
    if primary.exists():
        out.append(primary)
    out.extend(sorted(p for p in data_dir.glob("*" + SUFFIX)))
    return out


def load_manifest(path):
    try:
        obj = json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001 - a malformed manifest must not kill the run
        return []
    entries = obj.get("entries") if isinstance(obj, dict) else None
    return [e for e in (entries or []) if isinstance(e, dict) and e.get("url")]


def load_entries(data_dir):
    """Every recorded fetch across every manifest, plus which file it came from."""
    out = []
    for path in manifest_paths(data_dir):
        for entry in load_manifest(path):
            rec = dict(entry)
            rec.setdefault("manifest", Path(path).name)
            out.append(rec)
    return out


def urls_with_evidence(data_dir):
    """URLs whose manifest rows carry a 2xx status, a byte count and a hash."""
    ok = set()
    for e in load_entries(data_dir):
        status = e.get("http_status")
        if (e.get("ok") and isinstance(status, int) and 200 <= status < 300
                and isinstance(e.get("bytes"), int) and e.get("bytes") > 0
                and e.get("sha256")):
            ok.add(e.get("url"))
    return ok


def write_manifest(data_dir, area, entries, generated_utc, note):
    """Write ``data/<area>_provenance.json`` (idempotent: the file is replaced)."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{area}{SUFFIX}"
    path.write_text(json.dumps({
        "generated_utc": generated_utc,
        "area": area,
        "note": note,
        "entries": entries,
    }, indent=2, sort_keys=False) + "\n")
    return path


# --------------------------------------------------------------------------
# quality report
# --------------------------------------------------------------------------

QUALITY_REPORT = "quality_report.json"
SEVERITIES = ("error", "warning", "info")


def merge_irregularities(data_dir, area, items):
    """Add *items* to ``data/quality_report.json`` under a removable tag.

    Idempotent by construction: every entry this project's auxiliary scripts add
    carries ``"source": area``, and any entry already carrying that tag is
    dropped before the new ones are appended.  Running a script twice therefore
    cannot double-count a finding, and a finding an auxiliary script raised on a
    previous run cannot survive being fixed on this one.

    Counts are recomputed from the resulting list, so the published totals can
    never disagree with the entries - which is the same rule the nightly pipeline
    applies to its own report.
    """
    data_dir = Path(data_dir)
    path = data_dir / QUALITY_REPORT
    try:
        report = json.loads(path.read_text()) if path.exists() else {}
    except Exception:  # noqa: BLE001
        report = {}
    entries = [e for e in (report.get("irregularities") or [])
               if isinstance(e, dict) and e.get("source") != area]
    for item in items or []:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        entry["source"] = area
        entry.setdefault("severity", "info")
        if entry["severity"] not in SEVERITIES:
            entry["severity"] = "info"
        entries.append(entry)
    report.setdefault("generated_utc", None)
    report["irregularities"] = entries
    report["counts"] = {
        "total": len(entries),
        "errors": sum(1 for e in entries if e.get("severity") == "error"),
        "warnings": sum(1 for e in entries if e.get("severity") == "warning"),
        "info": sum(1 for e in entries if e.get("severity") == "info"),
    }
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path
