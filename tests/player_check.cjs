// Drives render(t) from film.html with a stub DOM; asserts the finished film.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");
const main = html.split('<script>\n"use strict";')[1].split("\nfunction start(film) {")[0];
const code = '"use strict";' + main;

function makeEl() {
  const el = {
    style: {}, textContent: "", className: "", src: "",
    children: [],
    appendChild(c) { this.children.push(c); },
  };
  let htmlText = "";
  Object.defineProperty(el, "innerHTML", {
    get: () => htmlText,
    set: (v) => { htmlText = v; el.children = []; },
  });
  return el;
}

const byId = {};
const seenIds = [];
const sandbox = {
  location: { search: "" },
  URLSearchParams,
  document: {
    getElementById: (id) => {
      seenIds.push(id);
      return byId[id] || (byId[id] = makeEl());
    },
    createElement: () => makeEl(),
  },
  matchMedia: () => ({ matches: false }),
  addEventListener: () => {},
  requestAnimationFrame: () => {},
  performance: { now: () => 0 },
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

sandbox.__DATA__ = {
  object: "Mill", kind: "watermill", photo: "today.jpg",
  photo_credit: "me", cutout: null, attribution: [],
  ai_label: "AI",
  today_line: "The society announced I died.", today_sub: "Photographed in 1900.",
  sources: [{ url: "https://en.wikipedia.org/wiki/Mill",
              site: "Wikipedia", title: "Mill" }],
  anchor: { line: "I have stood here since", label: "1865" },
  segments: [
    { kind: "title", start: 0, end: 3 },
    { kind: "anchor", start: 3, end: 5 },
    { kind: "era", year: 1865, image: "era_1865.png", start: 5, end: 12,
      caption: ["1865", "second"], site: "Wikipedia" },
    { kind: "era", year: 1920, image: "era_1920.png", start: 12, end: 19,
      caption: ["1920", "second"], site: "Wikipedia" },
    { kind: "today", start: 19, end: 24 },
    { kind: "end", start: 24, end: 30 },
  ],
  scenes: [
    { year: 1865, image: "era_1865.png", caption: ["a", "b"],
      site: "W", ready_at: 0 },
    { year: 1920, image: "era_1920.png", caption: ["a", "b"],
      site: "W", ready_at: 0 },
  ],
};

vm.runInContext("FILM = __DATA__;", sandbox);
const render = vm.runInContext("render", sandbox);
const imgA = () => sandbox.document.getElementById("imgA");

// The title card shows the verified kind, never a typed place.
render(1.0);
assert.strictEqual(sandbox.document.getElementById("cardTitle").textContent,
  "Mill", "title names the object");
assert.strictEqual(sandbox.document.getElementById("cardSub").textContent,
  "watermill", "subtitle shows the verified kind");

// The anchor card shows one year from the film data.
render(4.0);
assert.strictEqual(sandbox.document.getElementById("cardTitle").textContent,
  "I have stood here since", "anchor line from the film data");
assert.strictEqual(sandbox.document.getElementById("cardSub").textContent,
  "1865", "anchor shows one year");

// Start, middle and end of the era: one painting, no layers element.
for (const t of [5.0, 8.5, 11.9]) {
  render(t);
  assert.strictEqual(imgA().src, "era_1865.png", `painting up at t=${t}`);
  assert.strictEqual(sandbox.document.getElementById("cap1").textContent,
    "a", `stamp shown at t=${t}`);
}
assert.ok(!seenIds.includes("layers"), "no layers element touched");

// Every painted scene carries a visible AI label while on screen;
// the photo and the cards never do.
const badge = () => sandbox.document.getElementById("painted");
render(1.0);
assert.strictEqual(badge().style.display, "none",
  "no label on the title card");
render(8.5);
assert.strictEqual(badge().style.display, "block",
  "label on the painted era");
assert.ok(badge().textContent.includes("AI"),
  "label names AI imagery");
render(19.0);
assert.strictEqual(badge().style.display, "none",
  "no label on the photo");
render(26.0);
assert.strictEqual(badge().style.display, "none",
  "no label on the end card");

// Dissolving into today hides the era caption; era-to-era keeps it.
render(11.5);
assert.strictEqual(sandbox.document.getElementById("caption").style.display,
  "block", "era caption stays during era dissolves");
render(18.5);
assert.strictEqual(sandbox.document.getElementById("caption").style.display,
  "none", "no stamp rides onto the photo");

// Today opens on the photo, never on black.
render(19.0);
assert.strictEqual(sandbox.document.getElementById("caption").style.display,
  "block", "today caption appears");
assert.strictEqual(imgA().src, "today.jpg", "photo under the cut-out");
assert.strictEqual(imgA().style.opacity, 1, "photo visible from the start");
assert.strictEqual(sandbox.document.getElementById("cap1").textContent,
  "The society announced I died.", "today line from the film data");
assert.strictEqual(sandbox.document.getElementById("cap2").textContent,
  "Photographed in 1900.", "photo note from the film data");
render(22.0);
assert.strictEqual(imgA().style.opacity, 1, "photo stays up");

// An empty today line stays empty: no default line lands on the photo.
vm.runInContext("FILM.today_line = '';", sandbox);
render(19.0);
assert.strictEqual(sandbox.document.getElementById("cap1").textContent,
  "", "empty today line honored");
vm.runInContext("FILM.today_line = __DATA__.today_line;", sandbox);

// The end card names sites and pages, not raw URLs.
render(26.0);
const items = sandbox.document.getElementById("sources").children;
assert.strictEqual(items.length, 1, "one source listed");
const link = items[0].children[0];
assert.strictEqual(link.textContent, "Wikipedia: Mill");
assert.strictEqual(link.href, "https://en.wikipedia.org/wiki/Mill");
assert.strictEqual(link.target, "_blank");

// The finished film plays every era straight through: no check interlude,
// even for a scene whose paint landed late.
vm.runInContext("FILM.scenes[0].ready_at = 9999;", sandbox);
render(8.5);
assert.strictEqual(imgA().src, "era_1865.png", "late paint still plays");
assert.strictEqual(sandbox.document.getElementById("progress").style.display,
  "none", "no check interlude in the finished film");
vm.runInContext("FILM.scenes[0].ready_at = 0;", sandbox);

// The clock shows by default.
render(8.5);
assert.strictEqual(sandbox.document.getElementById("clock").style.display,
  "block", "clock visible");
assert.strictEqual(sandbox.document.getElementById("clock").textContent,
  "0:08", "clock reads the film time");

// Pause freezes the clock; replay restarts it.
const tickPlayer = vm.runInContext("tickPlayer", sandbox);
const togglePause = vm.runInContext("togglePause", sandbox);
vm.runInContext("player.t0 = 1000; player.last = 1000; player.total = 60;", sandbox);
assert.strictEqual(tickPlayer(3000), 2, "playing advances");
const frozen = tickPlayer(4000);
togglePause({ textContent: "Pause" });
assert.strictEqual(tickPlayer(9000), frozen, "paused clock frozen");
vm.runInContext("player.paused = false;", sandbox);
assert.strictEqual(tickPlayer(10000), frozen + 1, "resume continues");

// Preload covers the photo, the cut-out and every painting.
const collectImages = vm.runInContext("collectImages", sandbox);
const withCutout = Object.assign({}, sandbox.__DATA__, { cutout: "cutout.png" });
assert.deepStrictEqual([...collectImages(withCutout)],
  ["today.jpg", "cutout.png", "era_1865.png", "era_1920.png"],
  "every frame image, deduplicated");

console.log("player check OK: finished film, photo-first today, titled sources");
