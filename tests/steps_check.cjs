// Drives updateSteps from the landing page with a stub DOM; asserts each
// step shows its model from the start, follows the answering provider,
// and keeps it after the step ends.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");

const ol = html.match(/<ol id="steps">([\s\S]*?)<\/ol>/);
assert(ol, "no #steps list");
const items = [...ol[1].matchAll(
  /<li data-step="([^"]+)">([^<]*)<span class="model">([^<]*)<\/span><\/li>/g)];
assert(items.length === 5, "each step needs a model slot");
assert.deepStrictEqual(items.map((m) => m[2] + m[3]), [
  "Recognise · Muse Spark",
  "Research · Muse Spark",
  "Check · Muse Spark Open on Baseten",
  "Paint · Muse Image",
  "Film",
]);

const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
const stepFor = script[1].match(/const STEP_FOR = \{[^}]*\};/);
assert(stepFor, "no STEP_FOR");
const defaults = script[1].match(/const STEP_DEFAULTS = \[[^\]]*\];/);
assert(defaults, "no STEP_DEFAULTS");
const answered = script[1].match(/const answeredModels = new Map\(\);/);
assert(answered, "no answeredModels");
const updateFn = script[1].match(
  /function updateSteps\(ev\) \{[\s\S]*?\n\}/);
assert(updateFn, "no updateSteps(ev)");

function makeLi(step, label, model) {
  const span = { textContent: model, dataset: {} };
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

const lis = items.map((m) => makeLi(m[1], m[2], m[3]));
const sandbox = {
  document: { querySelectorAll: (sel) => (sel === "#steps li" ? lis : []) },
};
vm.createContext(sandbox);
vm.runInContext(
  `${stepFor[0]}\n${defaults[0]}\n${answered[0]}\n${updateFn[0]}`, sandbox);
const updateSteps = sandbox.updateSteps || vm.runInContext(
  "updateSteps", sandbox);

function current() {
  return lis.find((li) => li.classList.contains("current"));
}

function shown(step) {
  return lis.find((li) => li.dataset.step === step).text();
}

// Check names the open model from the event; the rest keep defaults.
updateSteps({ event: "verifying",
  data: { model: "Muse Spark Open on Baseten" } });
assert.strictEqual(current().dataset.step, "check");
assert.strictEqual(shown("check"), "Check · Muse Spark Open on Baseten");
assert.strictEqual(shown("identify"), "Recognise · Muse Spark");

// The same step follows a Meta fallback event instead.
updateSteps({ event: "verify", data: { model: "Muse Spark" } });
assert.strictEqual(shown("check"), "Check · Muse Spark");

// Paint names Muse Image; Check keeps the provider that answered.
updateSteps({ event: "painting", data: { model: "Muse Image" } });
assert.strictEqual(shown("paint"), "Paint · Muse Image");
assert.strictEqual(shown("check"), "Check · Muse Spark");

// A step without a model shows its name only.
updateSteps({ event: "render", data: {} });
assert.strictEqual(current().dataset.step, "film");
assert.strictEqual(shown("film"), "Film");
assert.strictEqual(shown("paint"), "Paint · Muse Image");

console.log("steps keep their answering models: OK");
