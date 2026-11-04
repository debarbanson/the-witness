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
  URL,
  URLSearchParams,
  document: {
    getElementById: (id) => {
      seenIds.push(id);
      return byId[id] || (byId[id] = makeEl());
    },
    createElement: () => makeEl(),
    createTextNode: (text) => ({ text, node: "text" }),
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
    { year: 1865, image: "era_1865.png", caption: ["1865", "first era"],
      site: "W", ready_at: 0 },
    { year: 1920, image: "era_1920.png", caption: ["1920", "second era"],
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
    "1865", `stamp shown at t=${t}`);
}
assert.ok(!seenIds.includes("layers"), "no layers element touched");

// Caption and image switch on the same frame: no early dissolve
// shows the next painting under the old caption.
const imgB = () => sandbox.document.getElementById("imgB");
const cap1 = () => sandbox.document.getElementById("cap1").textContent;
render(11.9);
assert.strictEqual(imgA().src, "era_1865.png", "old painting up to the cut");
assert.strictEqual(cap1(), "1865", "old caption up to the cut");
assert.strictEqual(imgB().style.opacity, 0, "no early dissolve into next era");
render(12.0);
assert.strictEqual(imgA().src, "era_1920.png", "new painting on the cut");
assert.strictEqual(cap1(), "1920", "new caption on the cut");
render(12.1);
assert.strictEqual(imgA().src, "era_1920.png", "new painting after the cut");
assert.strictEqual(cap1(), "1920", "new caption after the cut");

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

// Dissolving into today hides the era caption; eras cut cleanly.
render(11.5);
assert.strictEqual(sandbox.document.getElementById("caption").style.display,
  "block", "era caption stays up to the cut");
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

// After the film: more checked facts above the sources, each a stamp,
// the checked text and a link to its page. None: no heading.
const byIdEl = (id) => sandbox.document.getElementById(id);
assert.strictEqual(byIdEl("morehead").style.display, "none",
  "no more-facts heading without more facts");
assert.strictEqual(byIdEl("endcard").className, "card",
  "plain end card without more facts");
vm.runInContext(`FILM.more_facts = [
  { stamp: "1880", text: "A wing was added.", site: "b.example",
    url: "https://b.example/2" },
  { stamp: "11 July 1914", text: "<b>The roof fell.</b>",
    site: "Wikipedia", url: "https://en.wikipedia.org/wiki/Mill" }];`,
  sandbox);
render(26.0);
assert.strictEqual(byIdEl("morehead").style.display, "block",
  "more-facts heading shown");
assert.strictEqual(byIdEl("more").style.display, "block",
  "more-facts list shown");
assert.strictEqual(byIdEl("endcard").className, "card more",
  "the end card makes room for more facts");
const facts = byIdEl("more").children;
assert.strictEqual(facts.length, 2, "both more facts listed");
assert.strictEqual(facts[0].children[0].textContent, "1880 ");
assert.strictEqual(facts[0].children[1].text, "A wing was added. ");
assert.strictEqual(facts[0].children[2].href, "https://b.example/2");
assert.strictEqual(facts[0].children[2].textContent, "b.example");
assert.strictEqual(facts[0].children[2].target, "_blank");
assert.strictEqual(facts[1].children[0].textContent, "11 July 1914 ");
assert.strictEqual(facts[1].children[1].text, "<b>The roof fell.</b> ",
  "a fact lands as text, never markup");
render(26.0);
assert.strictEqual(byIdEl("more").children.length, 2,
  "re-rendering the end card never doubles the list");
assert.strictEqual(byIdEl("sources").children.length, 1,
  "sources still listed under the more facts");
vm.runInContext("FILM.more_facts = undefined;", sandbox);
render(26.0);
assert.strictEqual(byIdEl("morehead").style.display, "none",
  "the heading goes with the facts");
assert.strictEqual(byIdEl("more").children.length, 0);

// After the film: the film's own facts with their pages (4 Nov, the
// owner: they are no longer listed while the film is made). Film facts
// alone still turn the end card top-down.
assert.strictEqual(byIdEl("filmhead").style.display, "none",
  "no film-facts heading without film facts");
vm.runInContext(`FILM.film_facts = [
  { stamp: "1850", text: "The mill was built.", site: "Wikipedia",
    url: "https://en.wikipedia.org/wiki/Mill" }];`, sandbox);
render(26.0);
assert.strictEqual(byIdEl("filmhead").style.display, "block",
  "film-facts heading shown");
assert.strictEqual(byIdEl("filmfacts").style.display, "block",
  "film-facts list shown");
assert.strictEqual(byIdEl("endcard").className, "card more",
  "film facts alone make room too");
const inFilm = byIdEl("filmfacts").children;
assert.strictEqual(inFilm.length, 1, "the film fact listed");
assert.strictEqual(inFilm[0].children[0].textContent, "1850 ");
assert.strictEqual(inFilm[0].children[1].text, "The mill was built. ");
assert.strictEqual(inFilm[0].children[2].href,
  "https://en.wikipedia.org/wiki/Mill");
assert.strictEqual(inFilm[0].children[2].textContent, "Wikipedia");
assert.strictEqual(inFilm[0].children[2].target, "_blank");
assert.strictEqual(byIdEl("morehead").style.display, "none",
  "no more heading without more facts");
render(26.0);
assert.strictEqual(byIdEl("filmfacts").children.length, 1,
  "re-rendering never doubles the film facts");
vm.runInContext("FILM.film_facts = undefined;", sandbox);
render(26.0);
assert.strictEqual(byIdEl("filmhead").style.display, "none",
  "the heading goes with the film facts");
assert.strictEqual(byIdEl("filmfacts").children.length, 0);

// The end card links the photo source: author, licence and file page.
vm.runInContext(`FILM.photo_source = { author: "A. Uthor",
  licence: "CC BY 4.0", licence_url: "https://creativecommons.org/x",
  file_url: "https://commons.wikimedia.org/y" };`, sandbox);
render(26.0);
const credit = sandbox.document.getElementById("credit").children;
const hrefs = credit.filter((c) => c.href).map((c) => c.href);
assert.deepStrictEqual(hrefs,
  ["https://creativecommons.org/x", "https://commons.wikimedia.org/y"],
  "licence and file page linked");
assert.ok(credit.some((c) => (c.text || "").includes("A. Uthor")),
  "author named");
vm.runInContext("FILM.photo_source = null;", sandbox);

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

// The audience switch navigates to the sibling page, so every asset
// resolves against its own manifest; both directions round-trip.
const audienceTarget = vm.runInContext("audienceTarget", sandbox);
const adultPage = "https://example.org/film/id/cap/film.html";
const childPage = audienceTarget({ sibling_page: "child/film.html" }, adultPage);
assert.strictEqual(childPage,
  "https://example.org/film/id/cap/child/film.html", "adult goes to the child page");
assert.strictEqual(audienceTarget({ sibling_page: "../film.html" }, childPage),
  adultPage, "child returns to the adult page");

// A 202 "still publishing" retries the manifest fetch; never a final miss.
function extractBoot(name, args) {
  const found = html.match(
    new RegExp("(?:async )?function " + name + "\\(" + args +
      "\\) \\{[\\s\\S]*?\\n\\}"));
  assert(found, "no " + name + "(" + args + ")");
  return found[0];
}

{
  const stage = { fetches: 0, started: null, failed: null, timers: [],
    script: [] };
  const boot = {
    fetch: () => {
      stage.fetches += 1;
      const next = stage.script.length ? stage.script.shift() : 200;
      if (next === 202) {
        return Promise.resolve({ status: 202,
          json: () => Promise.resolve({ status: "publishing" }) });
      }
      if (next === 404) {
        return Promise.resolve({ status: 404,
          json: () => Promise.reject(new Error("no json")) });
      }
      return Promise.resolve({ status: 200,
        json: () => Promise.resolve({ scenes: [] }) });
    },
    setTimeout: (fn) => { stage.timers.push(fn); return stage.timers.length; },
    start: (film) => { stage.started = film; },
    document: { getElementById: () => makeEl() },
    console,
  };
  vm.createContext(boot);
  vm.runInContext(extractBoot("fail", "msg"), boot);
  vm.runInContext(extractBoot("loadFilmJson", "left"), boot);
  vm.runInContext("globalThis.load = loadFilmJson;", boot);

  const tick = () => new Promise((resolve) => setImmediate(resolve));
  async function drain() {
    for (let i = 0; i < 40 && (stage.timers.length || i < 2); i++) {
      while (stage.timers.length) {
        stage.timers.shift()();
      }
      await tick();
    }
    await tick();
    await tick();
  }
  function reset(script) {
    stage.fetches = 0; stage.started = null; stage.timers = [];
    stage.script = script.slice();
    boot.document.getElementById = () => {
      const el = makeEl();
      Object.defineProperty(el, "textContent", {
        get: () => stage.failed || "",
        set: (v) => { stage.failed = v; },
      });
      return el;
    };
    stage.failed = null;
  }

  (async () => {
    reset([200]);
    vm.runInContext("load(15)", boot);
    await drain();
    assert(stage.started, "a ready film starts");
    assert.strictEqual(stage.fetches, 1, "no retry when ready");

    reset([202, 202, 200]);
    vm.runInContext("load(15)", boot);
    await drain();
    assert(stage.started, "a published film starts after retries");
    assert.strictEqual(stage.fetches, 3, "each 202 retries once");

    reset(new Array(20).fill(202));
    vm.runInContext("load(15)", boot);
    await drain();
    assert(!stage.started, "nothing starts while publishing");
    assert.strictEqual(stage.fetches, 16, "retries are bounded");
    assert(stage.failed && stage.failed.includes("still publishing"),
      "exhaustion says still publishing, never a missing film");

    reset([404]);
    vm.runInContext("load(15)", boot);
    await drain();
    assert(!stage.started, "a missing manifest never starts");
    assert(stage.failed && stage.failed.includes("needs film.json"),
      "a true miss keeps its message");
  })().then(
    () => console.log(
      "player check OK: finished film, photo-first today, titled sources"),
    (err) => { console.error(err); process.exit(1); });
}
