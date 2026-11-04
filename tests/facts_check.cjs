// Drives renderFacts from the landing page with a stub DOM. While the
// film is made the panel lists only the facts shown after the film: the
// film's own facts wait for the film (4 Nov, the owner: listing them
// first made the film repeat them). It counts the accepted paintings,
// and facts land as text with at most an https link.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");

const box = html.match(/<div id="facts"([^>]*)>/);
assert(box, "no #facts panel");
assert(/class="hidden"/.test(box[1]), "the facts panel must start hidden");
assert(!html.includes("Checked so far"), "the film's facts are listed before the film");
assert(!html.includes('id="facts-list"'), "a film-facts list is still on the page");
assert(html.includes('<p id="paint-count"></p>'), "no #paint-count");
assert(/<h3 id="more-head"[^>]*>Also checked, shown after the film<\/h3>/
  .test(html), "no more-facts heading");
assert(html.includes('<ul id="more-list"></ul>'), "no #more-list");

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

const els = { facts: makeEl(), "paint-count": makeEl(),
              "more-head": makeEl(), "more-list": makeEl() };
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
const everything = () => JSON.stringify(
  Object.values(els).map((e) => [e._text, e.children]));

// Before painting starts: nothing shown.
renderFacts({ events: [
  { event: "facts", data: { claims: 9, anchor: 1850 } },
  { event: "verifying", data: {} },
] });
assert.strictEqual(els.facts.style.display, "none",
  "facts panel shown before painting");
assert.strictEqual(els["paint-count"].textContent, "");
assert.strictEqual(els["more-list"].children.length, 0);

// Painting starts: only the facts shown after the film appear.
const items = [
  { stamp: "1850", text: "The mill stood tall.", url: "https://a.example/mill" },
  { stamp: "23 April 1932", text: "The mill burnt down.",
    url: "https://a.example/fire" },
];
const more = [
  { stamp: "1880", text: "A wing was added.", url: "https://b.example/wing",
    guess: "Poldertoren", lat: 52.1 },
  { stamp: "1960", text: "<b>x</b>", url: "javascript:alert(1)" },
];
renderFacts({ events: [
  { event: "painting", data: { model: "Muse Image" } },
  { event: "checked_facts", data: { items, more } },
] });
assert.strictEqual(els.facts.style.display, "block");
assert.strictEqual(els["more-head"].style.display, "block");
const extra = els["more-list"].children;
assert.strictEqual(extra.length, 2, "both more facts listed");
assert.strictEqual(extra[0].children[0].textContent, "1880 ");
assert.strictEqual(extra[0].children[1].text, "A wing was added.");
assert.strictEqual(extra[0].children[2].href, "https://b.example/wing");
assert.strictEqual(extra[1].children.length, 2,
  "a non-https URL must not become a link");
assert.strictEqual(extra[1].children[1].text, "<b>x</b>",
  "a fact lands as text, never markup");
assert(!everything().includes("The mill stood tall."),
  "a film fact was listed before the film");
assert(!everything().includes("The mill burnt down."),
  "a film fact was listed before the film");
assert(!everything().includes("Poldertoren"), "a guessed name reached the page");
assert(!everything().includes("52.1"), "a coordinate reached the page");
assert(!everything().includes('"claims":9'), "the research event leaked in");
assert.strictEqual(els["paint-count"].textContent, "",
  "no count before the first painting");

// The counter advances as paintings are accepted.
renderFacts({ events: [
  { event: "checked_facts", data: { items, more } },
  { event: "painted", data: { year: 1850, verdict: "matches",
    accepted: 1, dropped: 0, attempted: 2 } },
] });
assert.strictEqual(els["paint-count"].textContent, "Painted 1 of 2");
renderFacts({ events: [
  { event: "checked_facts", data: { items, more } },
  { event: "painted", data: { year: 1932, verdict: "dropped",
    accepted: 1, dropped: 1, attempted: 2 } },
] });
assert.strictEqual(els["paint-count"].textContent, "Painted 1 of 1",
  "a dropped era leaves the count the film will have");
assert.strictEqual(els["more-list"].children.length, 2,
  "re-rendering never doubles the list");

// No more facts: nothing to read until the first painting is counted.
renderFacts({ events: [{ event: "checked_facts", data: { items } }] });
assert.strictEqual(els.facts.style.display, "none", "an empty panel was shown");
assert.strictEqual(els["more-head"].style.display, "none",
  "no heading without more facts");
assert.strictEqual(els["more-list"].children.length, 0);
renderFacts({ events: [
  { event: "checked_facts", data: { items } },
  { event: "painted", data: { year: 1850, verdict: "matches",
    accepted: 1, dropped: 0, attempted: 2 } },
] });
assert.strictEqual(els.facts.style.display, "block",
  "the painting count alone shows the panel");
assert.strictEqual(els["paint-count"].textContent, "Painted 1 of 2");
assert.strictEqual(els["more-head"].style.display, "none");
assert(!everything().includes("The mill stood tall."),
  "a film fact was listed before the film");

console.log("checked facts while painting: OK");
