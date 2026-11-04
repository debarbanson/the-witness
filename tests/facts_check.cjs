// Drives renderFacts from the landing page with a stub DOM; asserts the
// "Checked so far" panel lists the checked facts in film order with a
// source link each, counts accepted paintings, and renders nothing but
// stamp, sentence and source link.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");

const box = html.match(/<div id="facts"([^>]*)>/);
assert(box, "no #facts panel");
assert(/class="hidden"/.test(box[1]), "the facts panel must start hidden");
assert(html.includes("<h3>Checked so far</h3>"), "no Checked so far heading");
assert(html.includes('<ol id="facts-list"></ol>'), "no #facts-list");
assert(html.includes('<p id="paint-count"></p>'), "no #paint-count");

const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
const renderFn = script[1].match(
  /function renderFacts\(st\) \{[\s\S]*?\n\}/);
assert(renderFn, "no renderFacts(st)");
assert(!renderFn[0].includes("innerHTML"), "facts must land as text");
assert(script[1].includes("renderFacts(st)"), "poll loop never renders facts");

function makeEl() {
  const el = { style: {}, children: [], _text: "",
    appendChild(c) { this.children.push(c); return c; } };
  Object.defineProperty(el, "textContent", {
    get() { return this._text; },
    set(v) { this._text = String(v); this.children.length = 0; },
  });
  return el;
}

const els = { facts: makeEl(), "facts-list": makeEl(), "paint-count": makeEl() };
const sandbox = {
  document: {
    getElementById: (id) => els[id] || null,
    createElement: () => makeEl(),
    createTextNode: (text) => ({ text }),
  },
};
vm.createContext(sandbox);
vm.runInContext(renderFn[0], sandbox);
const renderFacts = vm.runInContext("renderFacts", sandbox);

// Before painting starts: nothing shown.
renderFacts({ events: [
  { event: "facts", data: { claims: 9, anchor: 1850 } },
  { event: "verifying", data: {} },
] });
assert.strictEqual(els.facts.style.display, "none",
  "facts panel shown before painting");
assert.strictEqual(els["facts-list"].children.length, 0);
assert.strictEqual(els["paint-count"].textContent, "");

// Painting starts: the checked facts appear in film order; the old
// research "facts" event stays ignored.
const items = [
  { stamp: "1850", text: "The mill stood tall.",
    url: "https://a.example/mill", guess: "Poldertoren", lat: 52.1 },
  { stamp: "23 April 1932", text: "The mill burnt down.",
    url: "http://plain.example/fire" },
];
renderFacts({ events: [
  { event: "painting", data: { model: "Muse Image" } },
  { event: "checked_facts", data: { items } },
] });
assert.strictEqual(els.facts.style.display, "block");
const kids = els["facts-list"].children;
assert.strictEqual(kids.length, 2, "both film facts listed");
assert.strictEqual(kids[0].children[0].textContent, "1850 ");
assert.strictEqual(kids[0].children[1].text, "The mill stood tall.");
assert.strictEqual(kids[0].children[2].href, "https://a.example/mill");
assert.strictEqual(kids[1].children.length, 2,
  "a non-https URL must not become a link");
const shown = JSON.stringify(els["facts-list"]);
assert(!shown.includes("Poldertoren"), "a guessed name reached the page");
assert(!shown.includes("52.1"), "a coordinate reached the page");
assert(!shown.includes('"claims":9'), "the research event leaked in");
assert.strictEqual(els["paint-count"].textContent, "",
  "no count before the first painting");

// The counter advances as paintings are accepted.
renderFacts({ events: [
  { event: "checked_facts", data: { items } },
  { event: "painted", data: { year: 1850, verdict: "matches",
    accepted: 1, dropped: 0, attempted: 2 } },
] });
assert.strictEqual(els["paint-count"].textContent, "Painted 1 of 2");
renderFacts({ events: [
  { event: "checked_facts", data: { items } },
  { event: "painted", data: { year: 1932, verdict: "dropped",
    accepted: 1, dropped: 1, attempted: 2 } },
] });
assert.strictEqual(els["paint-count"].textContent, "Painted 1 of 1",
  "a dropped era leaves the count the film will have");

// A dropped painting marks its fact, so the panel matches the film.
renderFacts({ events: [
  { event: "checked_facts", data: { items } },
  { event: "painted", data: { year: 1850, verdict: "matches",
    accepted: 1, dropped: 0, attempted: 2 } },
  { event: "painted", data: { year: 1932, verdict: "dropped",
    accepted: 1, dropped: 1, attempted: 2 } },
] });
const marked = els["facts-list"].children;
assert.strictEqual(marked.length, 2);
assert(!JSON.stringify(marked[0]).includes("not painted"),
  "a painted fact must not be marked");
assert(JSON.stringify(marked[1]).includes("not painted"),
  "a dropped full-date fact must be marked not painted");

// A hostile sentence lands as text, never markup.
renderFacts({ events: [{ event: "checked_facts", data: { items: [
  { stamp: "1850", text: "<img src=x>", url: "https://a.example/mill" },
] } }] });
assert.strictEqual(els["facts-list"].children.length, 1);
assert.strictEqual(els["facts-list"].children[0].children[1].text,
  "<img src=x>");

// More checked facts, the ones shown after the film: their own heading
// and list, text plus an https source link, never marked not painted.
assert(/<h3 id="more-head"[^>]*>Also checked, shown after the film<\/h3>/
  .test(html), "no more-facts heading");
assert(html.includes('<ul id="more-list"></ul>'), "no #more-list");
els["more-head"] = makeEl();
els["more-list"] = makeEl();
const more = [
  { stamp: "1880", text: "A wing was added.", url: "https://b.example/wing" },
  { stamp: "1932", text: "<b>x</b>", url: "javascript:alert(1)" },
];
renderFacts({ events: [
  { event: "checked_facts", data: { items, more } },
  { event: "painted", data: { year: 1932, verdict: "dropped",
    accepted: 1, dropped: 1, attempted: 2 } },
] });
assert.strictEqual(els["more-head"].style.display, "block");
const extra = els["more-list"].children;
assert.strictEqual(extra.length, 2, "both more facts listed");
assert.strictEqual(extra[0].children[0].textContent, "1880 ");
assert.strictEqual(extra[0].children[1].text, "A wing was added.");
assert.strictEqual(extra[0].children[2].href, "https://b.example/wing");
assert.strictEqual(extra[1].children.length, 2,
  "a non-https URL must not become a link");
assert.strictEqual(extra[1].children[1].text, "<b>x</b>");
assert(!JSON.stringify(extra).includes("not painted"),
  "a more fact is never marked not painted");
renderFacts({ events: [{ event: "checked_facts", data: { items } }] });
assert.strictEqual(els["more-head"].style.display, "none",
  "no heading without more facts");
assert.strictEqual(els["more-list"].children.length, 0);

console.log("checked facts while painting: OK");
