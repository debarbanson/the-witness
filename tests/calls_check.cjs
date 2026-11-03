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

renderCalls({ events: [
  { event: "verifying", data: { model: "Muse Spark Open on Baseten" } },
  { event: "call", data: { op: "call", phase: "verify",
    provider: "baseten", model: "meta-models/muse-spark-open-1026",
    duration_s: 2.4 } },
  { event: "call", data: { op: "call", phase: "paint",
    provider: "meta", model: "muse-image-1.0", duration_s: 33.7 } },
] });
assert.strictEqual(list.items.length, 2, "only call rows are listed");
assert(list.items[0].textContent.includes("meta-models/muse-spark-open-1026"));
assert(list.items[0].textContent.includes("baseten"));
assert(list.items[0].textContent.includes("verify"));
assert(list.items[0].textContent.includes("2.4"));
assert(list.items[1].textContent.includes("muse-image-1.0"));

// A hostile model name lands as text, never markup.
const evil = makeList();
sandbox.document = makeDocument(evil);
renderCalls({ events: [{ event: "call", data: { op: "call", phase: "x",
  provider: "y", model: "<img src=x>", duration_s: 1 } }] });
assert.strictEqual(evil.items.length, 1);
assert(evil.items[0].textContent.includes("<img src=x>"));

console.log("model calls toggle: OK");
