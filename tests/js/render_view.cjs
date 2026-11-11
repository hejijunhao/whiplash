// Render view.html in jsdom with real state frames and report what the page shows.
//
//   node tests/js/render_view.cjs <view.html> <frames.json>
//
// frames.json is a list of state frames (as /events sends them). Each is delivered as an SSE "state"
// event, then the page's own requestAnimationFrame loop runs for a few frames, and a summary of the
// rendered DOM is taken. Prints {"errors": [...], "shots": [...]} as JSON. Used by tests/test_view_harmony.py and
// tests/test_view_timeline.py;
// needs jsdom (npm install jsdom@24.1.3, found through NODE_PATH). Nothing here touches the network.
"use strict";
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const [htmlPath, framesPath] = process.argv.slice(2);
const html = fs.readFileSync(htmlPath, "utf8");
const frames = JSON.parse(fs.readFileSync(framesPath, "utf8"));
const errors = [];

const vc = new VirtualConsole();
vc.on("jsdomError", (e) => { if (!/Not implemented/.test(String(e.message))) errors.push(String(e.stack || e.message)); });
vc.on("error", (...a) => errors.push(a.map(String).join(" ")));

const handlers = {};
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, url: "http://127.0.0.1:7341/", virtualConsole: vc,
  beforeParse(window) {
    // jsdom has no canvas, EventSource or matchMedia: inert stand-ins, so the page's own code runs as is
    const ctx = new Proxy({}, { get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
    window.HTMLCanvasElement.prototype.getContext = function () { return ctx; };
    window.matchMedia = () => ({ matches: false, addEventListener() {} });
    window.EventSource = class {
      constructor() { this.readyState = 1; }
      addEventListener(name, fn) { handlers[name] = fn; }
    };
  },
});
const { window } = dom;
const doc = window.document;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : null);

function shot() {
  const harm = doc.getElementById("harm");
  const cells = [...doc.querySelectorAll("#chordRow .cell")].map((c) => ({
    num: txt(c.querySelector(".num")), name: txt(c.querySelector(".cname")), notes: txt(c.querySelector(".cnotes")),
    now: c.classList.contains("now"), next: c.classList.contains("next"),
    bars_on: c.querySelectorAll(".cbars i.on").length,
  }));
  const tracks = {};
  for (const el of doc.querySelectorAll("section.trk")) {
    const chd = el.querySelector(".chd");
    const title = el.querySelector("canvas.ttl")._k.split("|")[0];   // pxText's cache key: "TRK 7|2|#F0F0F0"
    tracks[title.replace("TRK ", "")] = {
      role: el.querySelector(".role").textContent, chd: chd.classList.contains("hidden") ? null : txt(chd),
    };
  }
  return {
    harm_hidden: harm.classList.contains("hidden"), key: txt(doc.getElementById("keyName")), key_src: txt(doc.getElementById("keySrc")),
    meta: txt(doc.getElementById("progMeta")), follow: txt(doc.getElementById("progFollow")), next_key: txt(doc.getElementById("nextKey")),
    row: txt(doc.getElementById("chordRow")), cells, tracks,
    // v0.6.1 section timeline and v0.7.0 EAR module
    tl_hidden: doc.getElementById("tl").classList.contains("hidden"), tl_name: txt(doc.getElementById("tlName")),
    tl_meta: txt(doc.getElementById("tlMeta")), tl_now: txt(doc.getElementById("tlNow")), tl_next: txt(doc.getElementById("tlNext")),
    tl_cue: doc.querySelectorAll("#tlNext .led.on").length, tl_events: txt(doc.getElementById("tlEvents")),
    tl_label: doc.getElementById("tlCv").getAttribute("aria-label"),
    ear_state: txt(doc.getElementById("earState")), ear_read: txt(doc.getElementById("earRead")), ear_note: txt(doc.getElementById("earNote")),
    guard: doc.getElementById("guardLed").classList.contains("on"), ear_patched: doc.getElementById("earIn").classList.contains("patched"),
    ear_stale: doc.getElementById("ear").classList.contains("stale"),
  };
}

(async () => {
  const shots = [];
  try {
    await sleep(30);
    for (const frame of frames) {
      handlers.state({ data: JSON.stringify(frame) });
      await sleep(120);   // several animation frames: the playhead extrapolates from frame.pos
      shots.push(shot());
    }
  } catch (e) {
    errors.push(String(e.stack || e));
  }
  process.stdout.write(JSON.stringify({ errors, shots }));
  window.close();
  process.exit(0);
})();
