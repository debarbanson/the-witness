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
  sources: [{ url: "https://en.wikipedia.org/wiki/Mill",
              site: "Wikipedia", title: "Mill" }],
  segments: [
    { kind: "title", start: 0, end: 3 },
    { kind: "era", year: 1865, image: "era_1865.png", start: 3, end: 10,
      caption: ["I stood here in 1865.", "second"], site: "Wikipedia" },
    { kind: "era", year: 1920, image: "era_1920.png", start: 10, end: 17,
      caption: ["I stood here in 1920.", "second"], site: "Wikipedia" },
    { kind: "today", start: 17, end: 22 },
    { kind: "end", start: 22, end: 28 },
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

// Start, middle and end of the layered scene: the shared transform.
for (const t of [3.0, 6.5, 9.9]) {
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
render(4.0);
const first = layersEl().children.slice();
render(4.1);
assert.deepStrictEqual(layersEl().children, first, "layer images reused");

// Leaving the scene clears the layers.
render(12.0);
assert.strictEqual(layersEl().children.length, 0, "layers cleared");
render(1.0);
assert.strictEqual(layersEl().children.length, 0, "layers cleared on title");

// Today opens on the photo, never on black.
render(17.0);
assert.strictEqual(imgA().src, "today.jpg", "photo under the cut-out");
assert.strictEqual(imgA().style.opacity, 1, "photo visible from the start");
render(20.0);
assert.strictEqual(imgA().style.opacity, 1, "photo stays up");

// The end card names sites and pages, not raw URLs.
render(24.0);
const items = sandbox.document.getElementById("sources").children;
assert.strictEqual(items.length, 1, "one source listed");
assert.strictEqual(items[0].textContent, "Wikipedia: Mill");

console.log("player check OK: flat layers, photo-first today, titled sources");
