"""EFT parsing, stat vector, and fit-equivalence check on Eos."""

from __future__ import annotations

import math
import re

_engine_ready = False
_getItem = None


class FitError(ValueError):
    """User-facing problem with the submitted fit text."""


def init_engine(gamedata_path: str) -> None:
    """Point Eos at a gamedata sqlite file (eve.db) and use an in-memory saveddata DB."""
    global _engine_ready, _getItem
    if _engine_ready:
        return
    import eos.config as ec

    ec.gamedataCache = False
    ec.gamedata_connectionstring = f"sqlite:///{gamedata_path}?check_same_thread=False"
    ec.saveddata_connectionstring = "sqlite:///:memory:"
    ec.settings = None
    import eos.db as eosdb

    _getItem = eosdb.getItem
    _engine_ready = True


def _item(name: str):
    item = _getItem(name)
    if item is None:
        raise FitError(f"Unknown item: {name}")
    return item


_HEADER = re.compile(r"^\[(?P<ship>[^,\]]+)(?:,\s*(?P<name>.*))?\]\s*$")
_QTY = re.compile(r"^(?P<name>.+?)\s+x(?P<qty>\d+)\s*$")
_FLAG = re.compile(r"\s*/(?P<flag>OFFLINE|ONLINE|ACTIVE|OVERLOAD)\s*$", re.IGNORECASE)


def parse_eft(text: str):
    """Build an Eos Fit from EFT text. Raises FitError with a readable message."""
    from eos.const import FittingModuleState
    from eos.saveddata.booster import Booster
    from eos.saveddata.drone import Drone
    from eos.saveddata.fighter import Fighter
    from eos.saveddata.fit import Fit
    from eos.saveddata.implant import Implant
    from eos.saveddata.module import Module
    from eos.saveddata.ship import Ship

    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    # Drop leading blank lines, then find the header.
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        raise FitError("Paste an EFT fit (starting with [Ship, Name]).")
    header = _HEADER.match(lines[0])
    if not header:
        raise FitError("First line must be the EFT header, e.g. [Loki, My Fit].")

    ship_item = _item(header.group("ship").strip())
    fit = Fit(name=(header.group("name") or "Fit").strip())
    fit.ship = Ship(ship_item)

    # Split the remaining lines into blank-line separated sections.
    sections: list[list[str]] = [[]]
    for ln in lines[1:]:
        if not ln:
            if sections[-1]:
                sections.append([])
        elif not (ln.startswith("[") and ln.endswith("]")):  # skip [Empty X slot] etc.
            sections[-1].append(ln)
    sections = [s for s in sections if s]

    for section in sections:
        for ln in section:
            qty = _QTY.match(ln)
            if qty:
                name = qty.group("name").strip()
                item = _item(name)
                category = item.category.name if item.category else ""
                if category == "Fighter":
                    obj = Fighter(item)
                    obj.amount = int(qty.group("qty"))
                    fit.fighters.append(obj)
                else:
                    obj = Drone(item)
                    obj.amount = int(qty.group("qty"))
                    fit.drones.append(obj)
                continue

            flag = _FLAG.search(ln)
            state_name = flag.group("flag").upper() if flag else None
            body = _FLAG.sub("", ln).strip()
            name, _, charge_name = body.partition(",")
            name = name.strip()
            charge_name = charge_name.strip()
            item = _item(name)
            category = item.category.name if item.category else ""
            group = item.group.name if item.group else ""

            if category == "Implant" and group == "Booster":
                fit.boosters.append(Booster(item))
            elif category == "Implant":
                fit.implants.append(Implant(item))
            else:
                mod = Module(item)
                mod.owner = fit
                if charge_name:
                    mod.charge = _item(charge_name)
                if state_name == "OFFLINE":
                    mod.state = FittingModuleState.OFFLINE
                elif mod.canHaveState(FittingModuleState.ACTIVE):
                    mod.state = FittingModuleState.ACTIVE
                else:
                    mod.state = FittingModuleState.ONLINE
                fit.modules.append(mod)
    return fit


# Slots compared in the stat vector.
def _slot_stats(fit, out):
    from eos.const import FittingSlot

    labels = {
        FittingSlot.HIGH: "slots.high",
        FittingSlot.MED: "slots.mid",
        FittingSlot.LOW: "slots.low",
        FittingSlot.RIG: "slots.rig",
        FittingSlot.SUBSYSTEM: "slots.subsystem",
    }
    for slot, label in labels.items():
        out[label + ".free"] = float(fit.getSlotsFree(slot))


def compute_stats(fit) -> dict:
    """Return the full stat vector for a fit. Price is intentionally excluded."""
    out: dict = {}
    ship = fit.ship

    out["cpu.used"] = float(fit.cpuUsed)
    out["cpu.output"] = float(ship.getModifiedItemAttr("cpuOutput") or 0)
    out["pg.used"] = float(fit.pgUsed)
    out["pg.output"] = float(ship.getModifiedItemAttr("powerOutput") or 0)
    _slot_stats(fit, out)

    ehp = fit.ehp
    for layer in ("shield", "armor", "hull"):
        out[f"ehp.{layer}"] = float(ehp.get(layer, 0))
    out["ehp.total"] = float(sum(ehp.values()))

    dps = fit.getTotalDps()
    for dmg in ("em", "thermal", "kinetic", "explosive"):
        out[f"dps.{dmg}"] = float(getattr(dps, dmg, 0) or 0)
    out["dps.total"] = out["dps.em"] + out["dps.thermal"] + out["dps.kinetic"] + out["dps.explosive"]

    out["cap.stable"] = bool(fit.capStable)
    out["cap.state"] = float(fit.capState or 0)
    out["cap.used"] = float(fit.capUsed)
    out["cap.recharge"] = float(fit.capRecharge)

    out["speed.max"] = float(fit.maxSpeed or 0)
    out["align.time"] = float(fit.alignTime or 0)
    out["warp.speed"] = float(fit.warpSpeed or 0)
    out["range.max"] = float(fit.maxTargetRange or 0)
    out["scan.strength"] = float(fit.scanStrength or 0)
    out["sig.radius"] = float(ship.getModifiedItemAttr("signatureRadius") or 0)
    return out


# ---- module roles and hardpoints -------------------------------------------
# A fit must use the same module types as the answer: if the answer has a
# webifier, the fit needs a webifier (any webifier); same for scram, point and
# remote rep. Hardpoint usage must match exactly (turret count and missile count),
# and so must the weapon families (energy, hybrid, projectile).

ROLE_KEYS = ("role.webifier", "role.scram", "role.point", "role.remote_rep")
HARDPOINT_KEYS = ("hardpoint.turret", "hardpoint.missile")
WEAPON_KEYS = ("weapon.energy", "weapon.hybrid", "weapon.projectile")

_REMOTE_REP_GROUPS = {
    "Remote Armor Repairer",
    "Mutadaptive Remote Armor Repairer",
    "Remote Shield Booster",
    "Remote Hull Repairer",
}
_WEAPON_GROUPS = {
    "Energy Weapon": "weapon.energy",
    "Hybrid Weapon": "weapon.hybrid",
    "Projectile Weapon": "weapon.projectile",
}


def _role_of(item) -> str | None:
    group = item.group.name if item.group else ""
    name = item.name or ""
    if group == "Stasis Web":
        return "role.webifier"
    if group == "Warp Disrupt Field Generator" or (group == "Warp Scrambler" and "Disruptor" in name):
        return "role.point"
    if group == "Warp Scrambler":
        return "role.scram"
    if group in _REMOTE_REP_GROUPS:
        return "role.remote_rep"
    return None


def compute_roles(fit) -> dict:
    """Count module roles, hardpoints and weapon families on a fit."""
    from eos.const import FittingHardpoint

    out = {k: 0 for k in ROLE_KEYS + HARDPOINT_KEYS + WEAPON_KEYS}
    for mod in fit.modules:
        role = _role_of(mod.item)
        if role:
            out[role] += 1
        if mod.hardpoint == FittingHardpoint.TURRET:
            out["hardpoint.turret"] += 1
        elif mod.hardpoint == FittingHardpoint.MISSILE:
            out["hardpoint.missile"] += 1
        weapon = _WEAPON_GROUPS.get(mod.item.group.name if mod.item.group else "")
        if weapon:
            out[weapon] += 1
    return {k: float(v) for k, v in out.items()}


def compare_roles(actual: dict, target: dict) -> list[str]:
    """Return role keys that differ.

    role.* must agree on presence (both have it, or both lack it).
    hardpoint.* and weapon.* must agree on exact counts.
    """
    bad = []
    for key in set(actual) | set(target):
        a = actual.get(key, 0)
        t = target.get(key, 0)
        if key.startswith("role."):
            if (a > 0) != (t > 0):
                bad.append(key)
        elif a != t:
            bad.append(key)
    return sorted(bad)


def is_valid(fit) -> tuple[bool, list[str]]:
    """Hard fitting limits: slots, CPU and power grid must not be exceeded."""
    problems = []
    stats = compute_stats(fit)
    for k in ("slots.high.free", "slots.mid.free", "slots.low.free", "slots.rig.free", "slots.subsystem.free"):
        if stats[k] < 0:
            problems.append(f"{k.split('.')[1]} slots over capacity")
    if stats["cpu.used"] > stats["cpu.output"] + 1e-9:
        problems.append("CPU over capacity")
    if stats["pg.used"] > stats["pg.output"] + 1e-9:
        problems.append("Power grid over capacity")
    return (not problems), problems


def _close(a, b, rel_tol: float, abs_tol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)


def compare_stats(actual: dict, target: dict, rel_tol: float = 1e-6, abs_tol: float = 1e-6) -> list[str]:
    """Return the stat keys that differ. Empty list means equivalent."""
    keys = set(actual) | set(target)
    return sorted(k for k in keys if not _close(actual.get(k, 0), target.get(k, 0), rel_tol, abs_tol))


def check_fit(eft_text: str, target: dict) -> dict:
    """Evaluate a submitted fit against a puzzle target.

    Returns {"ok": bool, "valid": bool, "problems": [...], "mismatched": [...]}.
    `target` is {"stats": {...}, "rel_tol": float, "abs_tol": float} from the build.
    """
    try:
        fit = parse_eft(eft_text)
    except FitError as exc:
        return {"ok": False, "valid": False, "problems": [], "mismatched": [], "role_mismatched": [], "error": str(exc)}
    valid, problems = is_valid(fit)
    stats = compute_stats(fit)
    mismatched = compare_stats(stats, target["stats"], target.get("rel_tol", 1e-6), target.get("abs_tol", 1e-6))
    role_mismatched = []
    if "roles" in target:
        role_mismatched = compare_roles(compute_roles(fit), target["roles"])
    return {
        "ok": valid and not mismatched and not role_mismatched,
        "valid": valid,
        "problems": problems,
        "mismatched": mismatched,
        "role_mismatched": role_mismatched,
    }
