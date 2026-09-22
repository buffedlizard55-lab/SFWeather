#!/usr/bin/env python3
"""Generator output contract: the staging assertion that closes the defect-84 hole.

Defect 84 (nightly run of 21 Sep 2026) was a *staging* bug: the commit step of
``.github/workflows/update-data.yml`` staged ``data/`` and ``assets/`` but not
the repair tier's generated copy in ``docs/``, so the tracked printable page
kept the previous run's stamp while the data moved.  The claim ledger caught
it *after the fact* (``repair-printable-page-generated`` compares the two
copies).  This module moves the catch to *before the commit*:

1. **A registry.**  ``GENERATORS`` below is the single declaration of what
   every pipeline step publishes: exact file paths, glob patterns for outputs
   whose count varies (archived CPC gifs, archived NMME maps) and outputs a
   step may legitimately skip (a source that returned nothing on that run).
   ``data/README.md`` is the one hand-maintained file living in the pipeline
   output area; it is allow-listed, not registered.

2. **``check`` (run in CI on every push and in the nightly before the commit
   gate).**  (a) every registered, non-optional output exists - a generator
   that silently stops writing fails the run; (b) no file in the pipeline
   output area is *unregistered* - a new generator that writes a path it never
   declared fails the run instead of quietly committing an undeclared file.

3. **``check --after-stage`` (run in the commit step, after ``git add``).**
   (c) ``git status`` must be clean for the whole output area - anything a
   generator produced but the staging list did not pick up fails the step, so
   the commit never happens.  This is the assertion the defect-84 bullet asks
   for: *list every generator's output paths, and refuse to commit until all
   of them are staged.*

The nightly workflow's commit step keeps its broad ``git add`` list and then
runs ``check --after-stage``; the registry and the assertion together mean a
new generator cannot publish a path that the commit would skip, and a removed
path cannot leave a tracked file stale without a loud failure.

Usage::

    python3 pipeline/generator_outputs.py             # check the committed state
    python3 pipeline/generator_outputs.py --after-stage
    python3 pipeline/generator_outputs.py --selftest  # offline, hermetic git

Exit 0 if the contract holds, 1 otherwise.  Standard library only.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Directories that contain *only* pipeline output.
SCAN_DIRS = ("data", "assets/cpc", "assets/model_guidance")
#: Individual files outside those directories that a pipeline step publishes.
SCAN_FILES = (
    "docs/REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md",  # the repair tier's docs copy
    "pipeline_run.log",                              # the nightly run log (root)
)
#: Files in the scan area that are maintained by hand, not by a generator.
#: ``pipeline_run.log`` is created by the nightly workflow's own shell
#: redirection (it is asserted staged by the after-stage check, but no
#: pipeline *step* publishes it, so it is exempt from the unregistered-file
#: check).  In a developer checkout it does not exist at all.
ALLOWLIST = frozenset({"data/README.md", "pipeline_run.log"})

#: step name -> what the step publishes.  ``outputs`` are exact paths,
#: ``optional`` outputs may be absent when the step's source returned nothing,
#: ``globs`` cover outputs whose count varies per run.  Every path is relative
#: to the repository root.
GENERATORS: dict[str, dict] = {
    "workflow-diagnostics": {
        "command": "Environment diagnostics step of .github/workflows/update-data.yml",
        "outputs": ("data/run_diagnostics.txt",),
        "optional": (),
        "globs": (),
    },
    "main": {
        "command": "pipeline/main.py",
        "outputs": (
            "data/run.json", "data/nws.json", "data/cpc.json", "data/enso.json",
            "data/climatology.json", "data/provenance.json",
            "data/quality_report.json", "data/summary.txt", "data/ghcn_probe.json",
            "data/pipeline.log",
        ),
        # Written only when the corresponding source returned data this run.
        "optional": (
            "data/isd_hourly_summary.json", "data/isd_history.json",
            "data/ghcnh_probe.json", "data/storm_events.json",
            "data/daily_normals.json", "data/monthly_normals.json",
            "data/humidity_normals.json",
        ),
        "globs": ("assets/cpc/*.gif",),
    },
    "build_calendar": {
        "command": "pipeline/build_calendar.py",
        "outputs": (
            "data/calendar.json", "data/forecast_history.json",
            "data/forecast_verification.json", "data/afd_history.json",
        ),
        "optional": (),
        "globs": (),
    },
    "cpc_backtest": {
        "command": "pipeline/cpc_backtest.py",
        "outputs": ("data/cpc_backtest.json",),
        "optional": (),
        "globs": (),
    },
    "ocean_wind": {
        "command": "pipeline/ocean_wind.py",
        "outputs": ("data/ocean_wind.json", "data/ocean_wind_provenance.json"),
        "optional": (),
        "globs": (),
    },
    "landlord": {
        "command": "pipeline/landlord_summary.py",
        "outputs": ("data/landlord.json",),
        "optional": (),
        "globs": (),
    },
    "repair": {
        "command": "pipeline/repair_maintenance_summary.py",
        # The docs copy is part of the generator's contract: defect 84 was
        # exactly this path being unstaged, so it is registered here and the
        # self-test refuses a registry that drops it.
        "outputs": (
            "data/repair_maintenance_summary.json",
            "data/repair_maintenance_executive.md",
            "docs/REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md",
        ),
        "optional": (),
        "globs": (),
    },
    "executive_summary": {
        "command": "pipeline/executive_summary.py",
        "outputs": ("data/executive_summary.json", "data/executive_summary.md"),
        "optional": (),
        "globs": (),
    },
    "digest": {
        "command": "pipeline/build_digest.py",
        "outputs": ("data/digest.json", "data/alerts.xml"),
        "optional": (),
        "globs": (),
    },
    "model_guidance": {
        "command": "pipeline/model_guidance.py",
        "outputs": ("data/model_guidance.json", "data/model_guidance_provenance.json"),
        "optional": (),
        "globs": ("assets/model_guidance/*.png",),
    },
    "feed": {
        "command": "pipeline/build_feed.py",
        "outputs": ("data/feed.json",),
        "optional": (),
        "globs": (),
    },
    "verify_claims": {
        "command": "pipeline/verify_claims.py",
        "outputs": ("data/verify.json", "data/verify_report.txt"),
        "optional": (),
        "globs": (),
    },
}


def _rel(p: pathlib.Path, root: pathlib.Path) -> str:
    return p.relative_to(root).as_posix()


def resolve(root: pathlib.Path | None = None) -> tuple[set[str], dict[str, list[str]], list[str]]:
    """Expand the registry against *root*.

    Returns ``(registered, per_step, errors)`` where ``registered`` is the set
    of POSIX paths the registry declares (globs expanded to the files that
    exist), ``per_step`` maps step name to the paths it resolved, and
    ``errors`` is non-empty when the registry itself is malformed (a glob that
    resolves to nothing in a tree where the directory itself is missing is not
    an error - the directory may legitimately not exist yet).
    """
    root = root or ROOT
    registered: set[str] = set()
    per_step: dict[str, list[str]] = {}
    for step, spec in GENERATORS.items():
        paths: list[str] = []
        for out in spec["outputs"]:
            paths.append(out)
        for opt in spec.get("optional", ()):
            if (root / opt).exists():
                paths.append(opt)
        for pat in spec.get("globs", ()):
            parent = pathlib.PurePosixPath(pat).parent
            base = root / parent if str(parent) != "." else root
            if base.is_dir():
                paths.extend(sorted(_rel(p, root)
                                    for p in base.glob(pat.rsplit("/", 1)[-1])))
        per_step[step] = paths
        registered.update(paths)
    return registered, per_step, []


def _walk_scope(root: pathlib.Path) -> list[str]:
    """Every file in the pipeline output area, as POSIX paths relative to root."""
    found: list[str] = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name != ".gitkeep":
                found.append(_rel(p, root))
    for f in SCAN_FILES:
        if (root / f).exists():
            found.append(f)
    return found


def problems(root: pathlib.Path | None = None, after_stage: bool = False) -> list[str]:
    """The contract, checked.  Returns a list of human-readable problems (empty = pass)."""
    root = root or ROOT
    registered, _per, _err = resolve(root)
    out: list[str] = []

    # (a) every registered, non-optional output exists.
    for step, spec in GENERATORS.items():
        for path in spec["outputs"]:
            if not (root / path).exists():
                out.append(f"registered output missing: {path} "
                           f"(generator: {step} / {spec['command']})")

    # (b) no file in the output area is unregistered.
    for f in _walk_scope(root):
        if f in ALLOWLIST:
            continue
        if f not in registered:
            out.append(f"unregistered file in the pipeline output area: {f} "
                       f"(no generator declares it - register it or remove it)")

    # (c) after staging, nothing the generators produced may be left unstaged.
    if after_stage:
        pathspecs = list(SCAN_DIRS) + list(SCAN_FILES)
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain", "--", *pathspecs],
                cwd=str(root), capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                out.append("git status could not be run in the staging check: "
                           + (proc.stderr.strip() or "unknown error"))
            else:
                # ``git status --porcelain`` lines are ``XY PATH``: X is the
                # staged (index) status, Y the worktree status.  A fully staged
                # output reads ``M  path`` (Y is the space) and must PASS.
                # Only a dirty worktree (Y set) or an untracked file (``??``)
                # is a staging failure.
                for line in proc.stdout.splitlines():
                    if not line.strip():
                        continue
                    unstaged = line.startswith("??") or (
                        len(line) > 1 and line[1] != " ")
                    if unstaged:
                        out.append(f"generator output not staged before commit: {line.strip()}")
        except (OSError, subprocess.SubprocessError) as exc:
            out.append(f"git status could not be run in the staging check: {exc}")
    return out


def report(root: pathlib.Path | None = None, after_stage: bool = False) -> int:
    root = root or ROOT
    registered, per_step, _err = resolve(root)
    fixed = sum(len(spec["outputs"]) for spec in GENERATORS.values())
    optional = sum(len(spec.get("optional", ())) for spec in GENERATORS.values())
    # Glob-resolved files are the registry paths that are not fixed/optional.
    glob_files = 0
    for step, spec in GENERATORS.items():
        known = set(spec["outputs"]) | set(spec.get("optional", ()))
        glob_files += sum(1 for p in per_step[step] if p not in known)
    n_files = len(_walk_scope(root))
    print(f"generator output contract: {len(GENERATORS)} steps, {fixed} fixed output(s), "
          f"{optional} optional, {glob_files} glob-resolved; "
          f"{n_files} file(s) in the output area"
          + (" (after-stage: git status asserted)" if after_stage else ""))
    issues = problems(root, after_stage=after_stage)
    for i in issues:
        print(f"  FAIL: {i}")
    if issues:
        print(f"  contract violated: {len(issues)} problem(s)")
        return 1
    print("  contract holds: every generator output is registered and present"
          + ("; staging is complete" if after_stage else ""))
    return 0


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #

def _copy_scope(tmp: pathlib.Path, root: pathlib.Path) -> None:
    for d in SCAN_DIRS:
        src = root / d
        if src.is_dir():
            shutil.copytree(src, tmp / d, ignore=shutil.ignore_patterns("__pycache__"))
    for f in SCAN_FILES:
        src = root / f
        if src.exists():
            dst = tmp / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def selftest() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok, detail: str = "") -> None:
        checks.append((name, bool(ok), str(detail)))

    root = ROOT

    # 0. The registry itself: the defect-84 regression - the docs copy of the
    #    printable repair page must be registered by its generator.
    check("the registry declares the repair tier's docs copy (defect 84 regression)",
          "docs/REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md" in GENERATORS["repair"]["outputs"],
          str(GENERATORS["repair"]["outputs"]))
    check("the registry covers more than ten pipeline steps",
          len(GENERATORS) >= 11, f"{len(GENERATORS)} steps")
    check("every registered path is relative and POSIX",
          all(p == pathlib.PurePosixPath(p).as_posix() and not p.startswith("/")
              for spec in GENERATORS.values() for p in spec["outputs"]))

    # 1. The committed state satisfies the contract.
    committed = problems(root)
    check("the committed repository state satisfies the contract",
          not committed, "; ".join(committed[:3]))

    with tempfile_area() as tmp:
        _copy_scope(tmp, root)
        # Reproduce the nightly condition the developer checkout lacks: the
        # workflow's own shell redirection creates the run log at the root.
        (tmp / "pipeline_run.log").write_text("step logs\n", encoding="utf-8")
        p_log = problems(tmp)
        check("the workflow's run log in the tree does not break the contract",
              not p_log, "; ".join(p_log[:3]))

        # 2. An unregistered file in the output area fails.
        (tmp / "data" / "_stray.json").write_text("{}", encoding="utf-8")
        p2 = problems(tmp)
        check("an unregistered file in data/ fails the contract",
              any("_stray.json" in x and "unregistered" in x for x in p2),
              "; ".join(p2[:3]))
        (tmp / "data" / "_stray.json").unlink()

        # 3. A missing required output fails.
        (tmp / "data" / "repair_maintenance_summary.json").unlink()
        p3 = problems(tmp)
        check("a missing required output fails the contract",
              any("repair_maintenance_summary.json" in x and "missing" in x for x in p3),
              "; ".join(p3[:3]))
        shutil.copy2(root / "data" / "repair_maintenance_summary.json",
                     tmp / "data" / "repair_maintenance_summary.json")

        # 4. A missing *optional* output is fine (the source may return nothing).
        if (tmp / "data" / "isd_hourly_summary.json").exists():
            (tmp / "data" / "isd_hourly_summary.json").unlink()
            p4 = problems(tmp)
            check("a missing optional output does not fail the contract",
                  not p4, "; ".join(p4[:3]))
            shutil.copy2(root / "data" / "isd_hourly_summary.json",
                         tmp / "data" / "isd_hourly_summary.json")
        else:
            check("a missing optional output does not fail the contract", True,
                  "optional output already absent in this state")

        # 5. Globs: a new archived map is covered; a file of another type is not.
        (tmp / "assets" / "model_guidance").mkdir(parents=True, exist_ok=True)
        (tmp / "assets" / "model_guidance" / "new_map.png").write_bytes(b"png")
        p5a = problems(tmp)
        check("a newly archived map png is covered by its glob",
              not p5a, "; ".join(p5a[:3]))
        (tmp / "assets" / "model_guidance" / "notes.txt").write_text("x")
        p5b = problems(tmp)
        check("a non-png file in the map archive fails the contract",
              any("notes.txt" in x and "unregistered" in x for x in p5b),
              "; ".join(p5b[:3]))

    # 6. The after-stage assertion, hermetic: a temporary git repository whose
    #    working tree is clean passes; an unstaged change fails.
    git = shutil.which("git")
    if not git:
        check("after-stage assertion is hermetic (git available)", True,
              "git not installed; skipped")
    else:
        with tempfile_area() as tmp:
            _copy_scope(tmp, root)
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True, env=env)
            subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, env=env)
            subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp, check=True, env=env)
            p6a = problems(tmp, after_stage=True)
            check("after-stage passes on a clean, fully-staged tree",
                  not p6a, "; ".join(p6a[:3]))
            # The nightly condition: the commit step's ``git add -A`` has run,
            # so the refreshed outputs are STAGED (``M  path``) and the
            # worktree is clean.  Porcelain reports staged changes too - the
            # assertion must pass here, or every nightly run is refused.
            (tmp / "data" / "run.json").write_text(
                (tmp / "data" / "run.json").read_text() + " ", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, env=env)
            p6s = problems(tmp, after_stage=True)
            check("after-stage passes when every change is staged (the nightly state)",
                  not p6s, "; ".join(p6s[:3]))
            (tmp / "data" / "run.json").write_text(
                (tmp / "data" / "run.json").read_text() + " ", encoding="utf-8")
            p6b = problems(tmp, after_stage=True)
            check("after-stage fails when a generated output is left unstaged",
                  any("not staged" in x for x in p6b), "; ".join(p6b[:3]))

    bad = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  [{'ok ' if ok else 'BAD'}] {name}" + (f" :: {detail}" if detail and not ok else ""))
    print()
    if bad:
        print(f"generator output contract self-test: {len(bad)} of {len(checks)} FAILED")
        return 1
    print(f"generator output contract self-test: {len(checks)}/{len(checks)} checks passed")
    return 0


def tempfile_area():
    import tempfile
    d = tempfile.TemporaryDirectory(prefix="sfweather_genout_")
    return _Area(d)


class _Area:
    def __init__(self, td):
        self._td = td

    def __enter__(self):
        return pathlib.Path(self._td.name)

    def __exit__(self, *a):
        self._td.cleanup()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT),
                    help="repository root to check (default: this checkout)")
    ap.add_argument("--after-stage", action="store_true",
                    help="also assert nothing in the output area is left unstaged "
                         "(run after the workflow's git add)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the offline self-test and exit")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    return report(pathlib.Path(args.root), after_stage=args.after_stage)


if __name__ == "__main__":
    sys.exit(main())
