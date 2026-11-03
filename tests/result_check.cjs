// Drives showResult from the landing page with a stub DOM; asserts the
// too-little end state lists checked sources (never unconfirmed claims),
// one or two facts list under a heading, and films link out.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
const hintFn = script[1].match(
  /function notConfirmedHint\(message\) \{[\s\S]*?\n\}/);
assert(hintFn, "no notConfirmedHint(message)");
const resultFn = script[1].match(
  /function showResult\(box, st\) \{[\s\S]*?\n\}/);
assert(resultFn, "no showResult(box, st)");
assert(!resultFn[0].includes("innerHTML"), "results must land as text");

function makeEl() {
  const el = { children: [], _text: "", appendChild(c) {
    this.children.push(c); return c; } };
  Object.defineProperty(el, "textContent", {
    get() { return this._text; },
    set(v) { this._text = String(v); this.children.length = 0; },
  });
  return el;
}

function flatten(node) {
  if (node.text !== undefined) { return node.text; }
  return (node._text || "") + (node.children || []).map(flatten).join("");
}

const sandbox = {
  document: {
    createElement: () => makeEl(),
    createTextNode: (text) => ({ text }),
  },
};
vm.createContext(sandbox);
vm.runInContext(`${hintFn[0]}\n${resultFn[0]}`, sandbox);
const showResult = vm.runInContext("showResult", sandbox);

// Zero confirmed facts: the message, then each checked source with its
// outcome; no claim text anywhere.
const box = makeEl();
showResult(box, { status: "done", result: {
  message: "No film this time. We found 7 possible facts in 6 sources.",
  claims: [],
  sources: [
    { domain: "en.wikipedia.org", url: "https://en.wikipedia.org/wiki/X",
      outcome: "read" },
    { domain: "waymarking.com", url: "https://www.waymarking.com/x",
      outcome: "asked for a login" },
    { domain: "shady.example", url: "javascript:alert(1)", outcome: "read" },
  ],
} });
const text = flatten(box);
assert(text.includes("No film this time"));
assert(text.includes("en.wikipedia.org read"));
assert(text.includes("waymarking.com asked for a login"));
assert(!text.includes("Checked facts"), "no facts, no heading");
const links = [];
(function walk(node) {
  for (const child of node.children || []) {
    if (child.href) { links.push(child); }
    walk(child);
  }
})(box);
assert.strictEqual(links.length, 2, "only https sources link out");
assert.strictEqual(links[0].href, "https://en.wikipedia.org/wiki/X");
assert.strictEqual(links[0].textContent, "en.wikipedia.org");

// One confirmed fact lists under its heading.
const one = makeEl();
showResult(one, { status: "done", result: {
  message: "Too little evidence for a film; the facts are below.",
  claims: [{ year: 1850, claim: "The mill stood.",
             url: "https://a.example/mill" }],
} });
assert(flatten(one).includes("Checked facts:"));
assert(flatten(one).includes("1850: The mill stood."));

// A film links out with no facts heading.
const film = makeEl();
showResult(film, { status: "done",
  result: { film_url: "/film/job-9/tok/film.html" } });
assert(flatten(film).includes("Ready."));
assert(flatten(film).includes("Watch your film."));
assert(!flatten(film).includes("Checked facts"));

// A hostile source lands as text, never markup.
const evil = makeEl();
showResult(evil, { status: "done", result: { message: "m", claims: [],
  sources: [{ domain: "<img src=x>", url: "https://a.example/x",
              outcome: "read" }] } });
assert(flatten(evil).includes("<img src=x>"));

console.log("result end states: OK");
