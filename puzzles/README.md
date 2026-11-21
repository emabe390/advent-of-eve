# Puzzles

One file per day, named e.g. `day-01.json` … `day-25.json`. The build reads every `*.json` in this folder.

```json
{
  "day": 1,
  "title": "Short title shown on the door",
  "unlock": "2026-12-01",
  "prompt": "The puzzle text. Plain text, line breaks kept.",
  "reference_fit": "[Loki, Answer]\nLarge Shield Extender II\n..."
}
```

- `unlock` is the date the door opens (YYYY-MM-DD, viewer's local date).
- `reference_fit` is your answer in EFT format. It is used only at build time to compute the target stats.
  It is **not** published on the site; the site only contains the target stat vector.
- Optional: `rel_tol` / `abs_tol` (default `1e-6`) for stat comparison tolerance.

A submitted fit is correct when every stat (everything except price) matches the reference within tolerance
and the fit does not exceed CPU, power grid or slot limits.

`examples/` holds a sample that is not built into the calendar. Test with:

    py -3.12 pipeline/build.py --puzzles puzzles/examples
