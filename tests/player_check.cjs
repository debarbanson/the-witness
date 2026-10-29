// Drives render(t) from film.html with a stub DOM; asserts flat layers.
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
const sandbox = {
  location: { search: "" },
  URLSearchParams,
  document: {
    getElementById: (id) => (byId[id] || (byId[id] = makeEl())),
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
  object: "Mill", place: "Town", photo: "today.jpg",
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
      site: "W", layers: ["l0.png", "l1.png"], ready_at: 0 },
    { year: 1920, image: "era_1920.png", caption: ["a", "b"],
      site: "W", layers: [], ready_at: 0 },
  ],
};

vm.runInContext("FILM = __DATA__;", sandbox);
const render = vm.runInContext("render", sandbox);
const imgA = () => sandbox.document.getElementById("imgA");
const layersEl = () => sandbox.document.getElementById("layers");

// The anchor card shows one year from the film data.
render(4.0);
assert.strictEqual(sandbox.document.getElementById("cardTitle").textContent,
  "I have stood here since", "anchor line from the film data");
assert.strictEqual(sandbox.document.getElementById("cardSub").textContent,
  "1865", "anchor shows one year");

// Start, middle and end of the layered scene: the shared transform.
for (const t of [5.0, 8.5, 11.9]) {
  render(t);
  const painting = imgA();
  assert.strictEqual(layersEl().children.length, 2, `two layers at t=${t}`);
  for (const img of layersEl().children) {
    assert.strictEqual(img.style.transform, painting.style.transform,
      `layer transform matches painting at t=${t}`);
    assert.strictEqual(img.style.opacity, painting.style.opacity,
      `layer opacity matches painting at t=${t}`);
  }
}

// Layer images are built once per scene, not once per frame.
render(6.0);
const first = layersEl().children.slice();
render(6.1);
assert.deepStrictEqual(layersEl().children, first, "layer images reused");

// Leaving the scene clears the layers.
render(14.0);
assert.strictEqual(layersEl().children.length, 0, "layers cleared");
render(1.0);
assert.strictEqual(layersEl().children.length, 0, "layers cleared on title");

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
assert.strictEqual(items[0].textContent, "Wikipedia: Mill");

// Preload covers the photo, the cut-out, every painting and its layers.
const collectImages = vm.runInContext("collectImages", sandbox);
const withCutout = Object.assign({}, sandbox.__DATA__, { cutout: "cutout.png" });
assert.deepStrictEqual([...collectImages(withCutout)],
  ["today.jpg", "cutout.png", "era_1865.png", "l0.png", "l1.png", "era_1920.png"],
  "every frame image, deduplicated");

console.log("player check OK: flat layers, photo-first today, titled sources");
