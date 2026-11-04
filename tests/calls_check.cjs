// Drives renderCalls from the landing page with a stub DOM; asserts the
// model-calls toggle lists the job's call rows as plain text and stays
// closed until the visitor opens it.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");

const details = html.match(/<details id="calls-box"([^>]*)>/);
assert(details, "no #calls-box details toggle");
assert(!/open/.test(details[1]), "the toggle must start closed");
assert(html.includes("<summary>Show the model calls</summary>"),
  "no Show the model calls summary");
assert(html.includes('<ul id="calls"></ul>'), "no #calls list");

const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
const renderFn = script[1].match(
  /function renderCalls\(st\) \{[\s\S]*?\n\}/);
assert(renderFn, "no renderCalls(st)");
assert(script[1].includes("renderCalls(st)"), "poll loop never renders calls");

function makeList() {
  return {
    items: [],
    textContent: "",
    appendChild(item) { this.items.push(item); },
  };
}

function makeDocument(list) {
  return {
    getElementById: (id) => (id === "calls" ? list : null),
    createElement: (tag) => ({ tag, textContent: "" }),
  };
}

const list = makeList();
const sandbox = { document: makeDocument(list) };
vm.createContext(sandbox);
vm.runInContext(renderFn[0], sandbox);
const renderCalls = vm.runInContext("renderCalls", sandbox);

// 4 Nov, the owner: "muse-spark-1.3 · meta · verify · 4.6s" was boring.
// Each row now says which model did what, for which year, from data
// every call already records: no extra model call, no source text.
renderCalls({ events: [
  { event: "verifying", data: { model: "Muse Spark Open on Baseten" } },
  { event: "call", data: { op: "call", phase: "verify",
    provider: "baseten", model: "meta-models/muse-spark-open-1026",
    duration_s: 2.43, about: 1736 } },
  { event: "call", data: { op: "call", phase: "paint",
    provider: "meta", model: "muse-image-1.0", duration_s: 33.7,
    about: 1736 } },
  { event: "call", data: { op: "call", phase: "research",
    provider: "meta", model: "muse-spark-1.3", duration_s: 89.1,
    searches: 17, prompt_tokens: 232509 } },
  { event: "call", data: { op: "call", phase: "check",
    provider: "meta", model: "muse-spark-1.3", duration_s: 29.04,
    about: 1736 } },
  { event: "call", data: { op: "call", phase: "check",
    provider: "meta", model: "muse-spark-1.3", duration_s: 4 } },
  { event: "call", data: { op: "call", phase: "identify",
    provider: "meta", model: "muse-spark-1.3", duration_s: 5.04 } },
  { event: "call", data: { op: "call", phase: "captions",
    provider: "meta", model: "muse-spark-1.3", duration_s: 9.5,
    about: 1862, ok: false } },
  { event: "call", data: { op: "call", phase: "research",
    provider: "meta", model: "muse-spark-1.3", duration_s: 12,
    searches: 1, prompt_tokens: 900 } },
  { event: "call", data: { op: "call", phase: "verify",
    provider: "baseten", model: "meta-models/muse-spark-open-1026",
    duration_s: 3, about: "1736 <b>x</b>" } },
] });
const lines = list.items.map((item) => item.textContent);
assert.strictEqual(lines.length, 9, "only call rows are listed");
assert.strictEqual(lines[0],
  "Muse Spark Open on Baseten checked a fact from 1736 against its source · 2.4 s");
assert.strictEqual(lines[1], "Muse Image painted 1736 · 34 s");
assert.strictEqual(lines[2],
  "Muse Spark searched the web 17 times and read 232,509 tokens · 89 s");
assert.strictEqual(lines[3],
  "Muse Spark compared the 1736 painting with the facts · 29 s");
assert.strictEqual(lines[4], "Muse Spark checked a picture · 4.0 s");
assert.strictEqual(lines[5],
  "Muse Spark worked out which landmark this is · 5.0 s");
assert.strictEqual(lines[6],
  "Muse Spark wrote the caption for 1862 · 9.5 s (failed)");
assert.strictEqual(lines[7],
  "Muse Spark searched the web once and read 900 tokens · 12 s");
assert.strictEqual(lines[8],
  "Muse Spark Open on Baseten checked a fact against its source · 3.0 s",
  "only a whole year is ever shown");

// A hostile model name lands as text, never markup.
const evil = makeList();
sandbox.document = makeDocument(evil);
renderCalls({ events: [{ event: "call", data: { op: "call", phase: "x",
  provider: "y", model: "<img src=x>", duration_s: 1 } }] });
assert.strictEqual(evil.items.length, 1);
assert(evil.items[0].textContent.includes("<img src=x>"));

console.log("model calls toggle: OK");
