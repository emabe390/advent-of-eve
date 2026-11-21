# Advent of Eve

A static advent calendar of EVE Online fitting puzzles. Each day's door opens on its date. Players paste an
EFT fit and it is checked in the browser with Pyfa's Eos engine (Pyfa v2.70.0, the newest release).

A fit is correct when every stat (price excluded) matches the reference fit's stats. Different modules with the same
numbers count as the same answer.

## Layout

| Path | What it is |
|------|------------|
| `puzzles/day-NN.json` | One puzzle per day (see [puzzles/README.md](puzzles/README.md)) |
| `web/` | Static site: `index.html`, `app.js`, `style.css` |
| `web/py/fitcheck/` | Fit parsing, stat vector and comparison (runs in the browser and at build time) |
| `pipeline/build.py` | Builds everything into `site/` |
| `.github/workflows/pages.yml` | Builds and deploys `site/` to GitHub Pages on push to `main` |

## Build on this machine

Requirements: Python 3.12, git, Node.js 22 (for Pyodide), and:

```bash
py -3.12 -m venv build-venv
build-venv\Scripts\activate
pip install -r pipeline/requirements.txt
python pipeline/build.py
```

The first build clones Pyfa into `build/pyfa`, builds `build/eve.db` (about 45 s), and writes `site/`.
Use `--skip-db` to reuse the database on later builds.

Preview locally:

```bash
python -m http.server 8000 --directory site
```

Then open http://localhost:8000/ . Add `?today=2026-12-03` to preview as if it were that date.

## Publish on GitHub Pages

1. Push this folder to a GitHub repository.
2. In the repository settings, open **Pages** and set **Source** to **GitHub Actions**.
3. Every push to `main` runs `pipeline/build.py` and deploys `site/`.

## Limits

- Pages is static, so the reference answer can't be hidden from someone who reads the site's files. The site ships only
  each puzzle's target stat vector, not the reference fit.
- Expect a first-visit download of about 40 MB (Pyodide plus the EVE database), cached by the browser afterwards.
- "Solved" marks are stored in the browser only.
