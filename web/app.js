// Advent of Eve: calendar UI + in-browser Pyfa (Eos) fit checking.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const DOORS = 25;
  const SOLVED_KEY = "adventOfEve.solved";

  let puzzles = [];
  let engine = null; // Promise<pyodide> once started
  let active = null; // puzzle currently open

  // ---- dates -------------------------------------------------------------
  function todayString() {
    const override = new URLSearchParams(location.search).get("today");
    if (override && /^\d{4}-\d{2}-\d{2}$/.test(override)) return override;
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  // ---- local "solved" memory (per-viewer convenience only) ----------------
  function loadSolved() {
    try { return new Set(JSON.parse(localStorage.getItem(SOLVED_KEY) || "[]")); }
    catch { return new Set(); }
  }
  function saveSolved(set) {
    try { localStorage.setItem(SOLVED_KEY, JSON.stringify([...set])); } catch { /* private mode */ }
  }

  // ---- calendar ----------------------------------------------------------
  function renderCalendar() {
    const today = todayString();
    const solved = loadSolved();
    const byDay = new Map(puzzles.map((p) => [p.day, p]));
    const cal = $("calendar");
    cal.replaceChildren();
    for (let day = 1; day <= DOORS; day++) {
      const p = byDay.get(day);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "door";
      const num = document.createElement("span");
      num.className = "num";
      num.textContent = String(day);
      const sub = document.createElement("span");
      sub.className = "sub";
      btn.append(num, sub);

      if (!p) {
        btn.classList.add("empty");
        btn.disabled = true;
        sub.textContent = "Coming soon";
      } else if (p.unlock > today) {
        btn.classList.add("locked");
        btn.disabled = true;
        sub.textContent = `Opens ${p.unlock}`;
      } else {
        sub.textContent = p.title;
        if (solved.has(day)) btn.classList.add("solved");
        btn.addEventListener("click", () => openPuzzle(p));
      }
      cal.append(btn);
    }
  }

  // ---- puzzle view -------------------------------------------------------
  function openPuzzle(p) {
    active = p;
    $("calendar").hidden = true;
    $("puzzle").hidden = false;
    $("puzzle-title").textContent = `Day ${p.day}: ${p.title}`;
    $("puzzle-prompt").textContent = p.prompt;
    $("result").hidden = true;
    $("engine-status").textContent = "";
    window.scrollTo({ top: 0 });
    $("fit-input").focus();
  }

  function closePuzzle() {
    active = null;
    $("puzzle").hidden = true;
    $("calendar").hidden = false;
    renderCalendar();
  }

  function showResult(kind, lines) {
    const box = $("result");
    box.className = `result ${kind}`;
    box.replaceChildren();
    for (const line of lines.head) {
      const p = document.createElement("p");
      p.style.margin = "0";
      p.textContent = line;
      box.append(p);
    }
    if (lines.items && lines.items.length) {
      const ul = document.createElement("ul");
      for (const item of lines.items) {
        const li = document.createElement("li");
        li.textContent = item;
        ul.append(li);
      }
      box.append(ul);
    }
    box.hidden = false;
  }

  // ---- engine ------------------------------------------------------------
  async function fetchGamedata(py) {
    const res = await fetch("data/eve.db.gz");
    if (!res.ok) throw new Error(`eve.db.gz: HTTP ${res.status}`);
    const stream = res.body.pipeThrough(new DecompressionStream("gzip"));
    const bytes = new Uint8Array(await new Response(stream).arrayBuffer());
    py.FS.writeFile("/home/pyodide/eve.db", bytes);
  }

  async function startEngine() {
    setStatus("Loading Pyfa engine (first visit downloads about 40 MB)…");
    const py = await loadPyodide({ indexURL: "vendor/pyodide/" });
    setStatus("Loading packages…");
    const pkgs = await (await fetch("vendor/pyodide/packages.json")).json();
    await py.loadPackage(pkgs);
    setStatus("Loading EVE static data…");
    await fetchGamedata(py);
    setStatus("Loading fitting code…");
    const zip = await (await fetch("runtime.zip")).arrayBuffer();
    py.unpackArchive(zip, "zip", { extractDir: "/home/pyodide/runtime" });
    py.runPython(`
import sys
sys.path.insert(0, "/home/pyodide/runtime")
from fitcheck.engine import init_engine
init_engine("/home/pyodide/eve.db")
`);
    setStatus("");
    return py;
  }

  function getEngine() {
    if (!engine) {
      engine = startEngine().catch((err) => { engine = null; throw err; });
    }
    return engine;
  }

  function setStatus(text) { $("engine-status").textContent = text; }

  const LABELS = {
    "cpu.used": "CPU used", "cpu.output": "CPU output",
    "pg.used": "Powergrid used", "pg.output": "Powergrid output",
    "slots.high.free": "High slots free", "slots.mid.free": "Mid slots free",
    "slots.low.free": "Low slots free", "slots.rig.free": "Rig slots free",
    "slots.subsystem.free": "Subsystem slots free",
    "ehp.shield": "EHP shield", "ehp.armor": "EHP armor", "ehp.hull": "EHP hull", "ehp.total": "EHP total",
    "dps.em": "DPS EM", "dps.thermal": "DPS thermal", "dps.kinetic": "DPS kinetic",
    "dps.explosive": "DPS explosive", "dps.total": "DPS total",
    "cap.stable": "Capacitor stable", "cap.state": "Capacitor state", "cap.used": "Capacitor used",
    "cap.recharge": "Capacitor recharge",
    "speed.max": "Max speed", "align.time": "Align time", "warp.speed": "Warp speed",
    "range.max": "Max target range", "scan.strength": "Scan strength", "sig.radius": "Signature radius",
  };

  async function checkFit() {
    if (!active) return;
    const text = $("fit-input").value;
    const button = $("check");
    button.disabled = true;
    try {
      const py = await getEngine();
      setStatus("Checking…");
      py.globals.set("_eft", text);
      py.globals.set("_target", JSON.stringify(active.target));
      const raw = py.runPython(`
import json
from fitcheck.engine import check_fit
json.dumps(check_fit(_eft, json.loads(_target)))
`);
      const res = JSON.parse(raw);
      setStatus("");
      if (res.error) {
        showResult("bad", { head: [res.error] });
      } else if (res.ok) {
        markSolved(active.day);
        showResult("good", { head: [`Equivalent fit. Day ${active.day} solved!`] });
      } else if (!res.valid) {
        showResult("bad", { head: ["This fit breaks fitting rules:"], items: res.problems });
      } else {
        const items = res.mismatched.map((k) => LABELS[k] || k);
        showResult("bad", { head: ["Not equivalent yet. These stats differ from the answer:"], items });
      }
    } catch (err) {
      setStatus("");
      showResult("bad", { head: [`Could not check the fit: ${err.message || err}`] });
    } finally {
      button.disabled = false;
    }
  }

  function markSolved(day) {
    const solved = loadSolved();
    solved.add(day);
    saveSolved(solved);
  }

  // ---- boot --------------------------------------------------------------
  async function boot() {
    try {
      const res = await fetch("data/puzzles.json");
      const data = await res.json();
      puzzles = data.puzzles || [];
    } catch {
      puzzles = [];
    }
    renderCalendar();
    $("check").addEventListener("click", checkFit);
    $("close").addEventListener("click", closePuzzle);
  }

  boot();
})();
