// Drives updateSteps from the landing page with a stub DOM; asserts the
// current step names the model from the event, never a fixed label.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");

const ol = html.match(/<ol id="steps">([\s\S]*?)<\/ol>/);
assert(ol, "no #steps list");
const items = [...ol[1].matchAll(
  /<li data-step="([^"]+)">([^<]*)<span class="model"><\/span><\/li>/g)];
assert(items.length === 5, "each step needs a model slot");

const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
const stepFor = script[1].match(/const STEP_FOR = \{[^}]*\};/);
assert(stepFor, "no STEP_FOR");
const updateFn = script[1].match(
  /function updateSteps\(ev\) \{[\s\S]*?\n\}/);
assert(updateFn, "no updateSteps(ev)");

function makeLi(step, label) {
  const span = { textContent: "" };
  const classes = new Set();
  return {
    dataset: { step },
    label,
    span,
    querySelector: (sel) => (sel === ".model" ? span : null),
    classList: {
      toggle: (name, on) => {
        if (on) { classes.add(name); } else { classes.delete(name); }
      },
      contains: (name) => classes.has(name),
    },
    text: () => label + span.textContent,
  };
}

const lis = items.map((m) => makeLi(m[1], m[2]));
const sandbox = {
  document: { querySelectorAll: (sel) => (sel === "#steps li" ? lis : []) },
};
vm.createContext(sandbox);
vm.runInContext(`${stepFor[0]}\n${updateFn[0]}`, sandbox);
const updateSteps = sandbox.updateSteps || vm.runInContext(
  "updateSteps", sandbox);

function current() {
  return lis.find((li) => li.classList.contains("current"));
}

// Check names the open model from the event.
updateSteps({ event: "verifying",
  data: { model: "Muse Spark Open on Baseten" } });
assert.strictEqual(current().dataset.step, "check");
assert.strictEqual(current().text(), "Check · Muse Spark Open on Baseten");

// The same step follows a Meta fallback event instead.
updateSteps({ event: "verify", data: { model: "Muse Spark" } });
assert.strictEqual(current().dataset.step, "check");
assert.strictEqual(current().text(), "Check · Muse Spark");

// Paint names Muse Image; the old step clears its label.
updateSteps({ event: "painting", data: { model: "Muse Image" } });
assert.strictEqual(current().dataset.step, "paint");
assert.strictEqual(current().text(), "Paint · Muse Image");
assert.strictEqual(
  lis.find((li) => li.dataset.step === "check").text(), "Check");

// A step without a model shows its name only.
updateSteps({ event: "render", data: {} });
assert.strictEqual(current().dataset.step, "film");
assert.strictEqual(current().text(), "Film");

console.log("steps label follows events: OK");
