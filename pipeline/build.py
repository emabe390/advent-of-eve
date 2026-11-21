#!/usr/bin/env python3
"""Build the static advent site.

    py -3.12 pipeline/build.py            # full build into site/
    py -3.12 pipeline/build.py --skip-db  # reuse build/eve.db from a previous run
    py -3.12 pipeline/build.py --puzzles path/to/other  # use another puzzle folder (e.g. tests)

Steps
  1. Fetch the Pyfa source at PYFA_TAG (newest release) into build/pyfa.
  2. Build eve.db (Eos gamedata) from Pyfa's static JSON, using a config shim so
     no wxPython/GUI install is needed.
  3. Stage the browser runtime: Pyfa's eos package + fitcheck + shims -> runtime.zip.
  4. Gzip eve.db into site/data/.
  5. Vendor Pyodide and the pure pieces it needs (sqlalchemy, logbook, ...) into site/vendor/.
  6. Compute each puzzle's target stats from its reference fit (CPython, same Eos code)
     and write site/data/puzzles.json. Reference fits are NOT shipped to the site.
  7. Copy the static web files into site/.

Requirements (build machine): Python 3.12+, git, Node.js + npm (for Pyodide),
and `pip install -r pipeline/requirements.txt`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
SITE = ROOT / "site"
WEB = ROOT / "web"
PUZZLES = ROOT / "puzzles"

PYFA_REPO = "https://github.com/pyfa-org/Pyfa.git"
PYFA_TAG = "v2.70.0"  # newest Pyfa release (2026-11-10)
PYODIDE_VERSION = "0.29.0"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
# Packages the runtime imports; their dependencies are resolved from the lock file.
PYODIDE_PACKAGES = ["sqlalchemy", "logbook"]


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def run(cmd, cwd=None, **kw) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, **kw)


def fetch_pyfa() -> Path:
    dest = BUILD / "pyfa"
    if not (dest / "eos" / "__init__.py").exists():
        if dest.exists():
            shutil.rmtree(dest)
        log(f"cloning Pyfa {PYFA_TAG}")
        run(["git", "clone", "--depth", "1", "--branch", PYFA_TAG, PYFA_REPO, str(dest)])
    else:
        log(f"using existing Pyfa checkout at {dest}")
    return dest


def build_gamedata(pyfa: Path, skip: bool) -> Path:
    out = BUILD / "eve.db"
    if skip and out.exists():
        log("skipping DB build (--skip-db)")
        return out
    # Work in a copy so the config shim never touches the Pyfa checkout.
    work = BUILD / "db-build"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(pyfa, work, ignore=shutil.ignore_patterns(".git", "*.pyc", "__pycache__"))
    shutil.copy(WEB / "py" / "config.py", work / "config.py")
    log("building eve.db from Pyfa static data (about 45 s)")
    run([sys.executable, "db_update.py"], cwd=work)
    shutil.copy(work / "eve.db", out)
    return out


def stage_runtime(pyfa: Path) -> Path:
    stage = BUILD / "runtime"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copytree(pyfa / "eos", stage / "eos", ignore=shutil.ignore_patterns("__pycache__"))
    (stage / "utils").mkdir()
    shutil.copy(pyfa / "utils" / "repr.py", stage / "utils" / "repr.py")
    (stage / "utils" / "__init__.py").write_text("", encoding="utf-8")
    for item in (WEB / "py").iterdir():
        if item.name == "__pycache__":
            continue
        if item.is_dir():
            shutil.copytree(item, stage / item.name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy(item, stage / item.name)
    zip_path = SITE / "runtime.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(stage).as_posix())
    log(f"runtime.zip: {zip_path.stat().st_size / 1e6:.1f} MB")
    return stage


def write_gamedata(db: Path) -> None:
    out = SITE / "data" / "eve.db.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(db, "rb") as src, gzip.open(out, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    log(f"eve.db.gz: {out.stat().st_size / 1e6:.1f} MB (from {db.stat().st_size / 1e6:.1f} MB)")


def _resolve_packages(lock: dict, names: list[str]) -> list[str]:
    seen: list[str] = []

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.append(name)
        for dep in lock["packages"][name].get("depends", []):
            visit(dep)

    for name in names:
        visit(name)
    return seen


def vendor_pyodide() -> None:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise SystemExit("npm not found; install Node.js to vendor Pyodide")
    npm_dir = BUILD / "npm"
    npm_dir.mkdir(parents=True, exist_ok=True)
    if not (npm_dir / "node_modules" / "pyodide").exists():
        log(f"installing pyodide@{PYODIDE_VERSION} via npm")
        run([npm, "install", f"pyodide@{PYODIDE_VERSION}", "--silent"], cwd=npm_dir)
    src = npm_dir / "node_modules" / "pyodide"
    dest = SITE / "vendor" / "pyodide"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]:
        shutil.copy(src / name, dest / name)

    lock = json.loads((dest / "pyodide-lock.json").read_text(encoding="utf-8"))
    needed = _resolve_packages(lock, PYODIDE_PACKAGES)
    for name in needed:
        file_name = lock["packages"][name]["file_name"]
        target = dest / file_name
        if target.exists():
            continue
        log(f"fetching Pyodide package {file_name}")
        urllib.request.urlretrieve(PYODIDE_CDN + file_name, target)
    (dest / "packages.json").write_text(json.dumps(needed), encoding="utf-8")
    log(f"Pyodide {PYODIDE_VERSION} vendored with packages: {', '.join(needed)}")


def build_targets(stage: Path, db: Path) -> None:
    """Compute each puzzle's target stat vector with the same engine the browser uses."""
    sys.path.insert(0, str(stage))
    from fitcheck.engine import compute_roles, compute_stats, init_engine, is_valid, parse_eft

    init_engine(str(db.resolve()).replace("\\", "/"))
    puzzles = []
    for path in sorted(PUZZLES.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        for key in ("day", "title", "unlock", "prompt", "reference_fit"):
            if key not in spec:
                raise SystemExit(f"{path.name}: missing '{key}'")
        fit = parse_eft(spec["reference_fit"])
        valid, problems = is_valid(fit)
        if not valid:
            raise SystemExit(f"{path.name}: reference fit is invalid: {problems}")
        dt.date.fromisoformat(spec["unlock"])  # validate date format
        puzzles.append({
            "day": int(spec["day"]),
            "title": spec["title"],
            "unlock": spec["unlock"],
            "prompt": spec["prompt"],
            "target": {
                "stats": compute_stats(fit),
                "roles": compute_roles(fit),
                "rel_tol": float(spec.get("rel_tol", 1e-6)),
                "abs_tol": float(spec.get("abs_tol", 1e-6)),
            },
        })
        log(f"target for day {spec['day']}: {spec['title']}")
    puzzles.sort(key=lambda p: p["day"])
    out = SITE / "data" / "puzzles.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "pyfa_tag": PYFA_TAG,
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "puzzles": puzzles,
    }, indent=1), encoding="utf-8")
    log(f"wrote {len(puzzles)} puzzle(s) to {out.relative_to(ROOT)}")


def copy_web() -> None:
    for name in ["index.html", "app.js", "style.css"]:
        shutil.copy(WEB / name, SITE / name)
    (SITE / ".nojekyll").write_text("", encoding="utf-8")


def main() -> None:
    global PUZZLES
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-db", action="store_true", help="reuse build/eve.db")
    ap.add_argument("--puzzles", type=Path, default=PUZZLES, help="folder with day-*.json files")
    args = ap.parse_args()
    PUZZLES = args.puzzles.resolve()

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    BUILD.mkdir(exist_ok=True)

    pyfa = fetch_pyfa()
    db = build_gamedata(pyfa, args.skip_db)
    stage = stage_runtime(pyfa)
    write_gamedata(db)
    vendor_pyodide()
    build_targets(stage, db)
    copy_web()
    log(f"site ready: {SITE}")


if __name__ == "__main__":
    main()
