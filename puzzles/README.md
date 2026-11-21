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

A submitted fit is correct when all of these hold:

1. **Stats match.** Every stat (everything except price) matches the reference fit's stats within tolerance.
2. **Module types match.** The fit uses the same module types as the reference, though not necessarily the same
   modules (for example, any webifier counts as a webifier):
   - Webifier, warp scrambler (scram), warp disruptor (point) and remote repairer/booster: the fit has one if and
     only if the reference has one.
   - Turret hardpoints and missile hardpoints: the same count as the reference.
   - Energy, hybrid and projectile weapons: the same count as the reference.
3. **Fitting rules.** The fit does not exceed CPU, power grid or slot limits.

Warp disruptors and warp scramblers are told apart by name ("Disruptor" = point). Remote repairers include armor
repairers, shield boosters and hull repairers.

`examples/` holds a sample that is not built into the calendar. Test with:

    py -3.12 pipeline/build.py --puzzles puzzles/examples
