// Drives showConfirm from the landing page with a stub DOM; asserts the
// confirm question names the place from its description, with the kind
// in brackets when no description is stored.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");

const para = html.match(
  /<p>Is this <strong id="confirm-name"><\/strong><span id="confirm-detail"><\/span>\?<\/p>/);
assert(para, "no confirm question with a detail slot");

const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
const showFn = script[1].match(
  /function showConfirm\(st\) \{[\s\S]*?\n\}/);
assert(showFn, "no showConfirm(st)");

function elements() {
  const box = { style: { display: "" } };
  const name = { textContent: "" };
  const detail = { textContent: "" };
  return {
    box, name, detail,
    byId: { confirm: box, "confirm-name": name, "confirm-detail": detail },
  };
}

let els = elements();
const sandbox = {
  document: { getElementById: (id) => els.byId[id] || null },
};
vm.createContext(sandbox);
vm.runInContext(showFn[0], sandbox);
const showConfirm = vm.runInContext("showConfirm", sandbox);

function question() {
  return "Is this " + els.name.textContent + els.detail.textContent + "?";
}

// A stored description names the place.
showConfirm({ confirm: { name: "Poldertoren", kind: "water tower",
  description: "water tower in Noordoostpolder" }, decision: null });
assert.strictEqual(els.box.style.display, "block");
assert.strictEqual(question(),
  "Is this Poldertoren, water tower in Noordoostpolder?");

// Without a description the kind shows in brackets, as before.
els = elements();
showConfirm({ confirm: { name: "Mill", kind: "mill" }, decision: null });
assert.strictEqual(els.box.style.display, "block");
assert.strictEqual(question(), "Is this Mill (mill)?");

// No confirm hides the box.
els = elements();
showConfirm({ confirm: null, decision: null });
assert.strictEqual(els.box.style.display, "none");

console.log("confirm names the place: OK");
