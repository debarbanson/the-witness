// Drives renderSub from the landing page with a stub DOM; asserts real
// sub-progress lines from the job's own events, the still-working line
// after 20 s without events, and a static marker under reduced motion.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");
const order = ["<ol id=\"steps\">", 'id="subprogress"', 'id="still-working"',
  'id="calls-box"'];
let at = 0;
for (const marker of order) {
  const found = html.indexOf(marker, at);
  assert(found >= 0, `no ${marker}`);
  at = found;
}

const style = html.match(/<style>([\s\S]*?)<\/style>/);
assert(style, "no page style");
assert(style[1].includes("#steps li.current::before"),
  "no current-step marker rule");
assert(/animation:\s*pulse/.test(style[1]), "the current step must pulse");
const frames = style[1].match(/@keyframes pulse\s*\{([\s\S]*?)\}\s*\}/);
assert(frames, "no pulse keyframes");
assert(frames[1].includes("opacity"), "pulse must animate opacity");
assert(!/box-shadow|width|height|margin|transform/.test(frames[1]),
  "pulse must stay composite-only");
const calm = style[1].match(
  /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\}\s*\}/);
assert(calm, "no reduced-motion rule");
assert(calm[1].includes("animation:none"), "reduced motion must not animate");

const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
const stepFor = script[1].match(/const STEP_FOR = \{[^}]*\};/);
assert(stepFor, "no STEP_FOR");
const names = script[1].match(/const STEP_NAMES = \[[^\]]*\];/);
assert(names, "no STEP_NAMES");
const state = script[1].match(/const subState = \{[^}]*\};/);
assert(state, "no subState");
const subFn = script[1].match(
  /function renderSub\(st, now\) \{[\s\S]*?\n\}/);
assert(subFn, "no renderSub(st, now)");
assert(script[1].includes("renderSub(st,"), "poll loop never renders sub");

const els = {};
const sandbox = {
  document: {
    getElementById: (id) => els[id] || (els[id] = { textContent: "" }),
  },
};
vm.createContext(sandbox);
vm.runInContext(`${stepFor[0]}\n${names[0]}\n${state[0]}\n${subFn[0]}`,
  sandbox);
const renderSub = vm.runInContext("renderSub", sandbox);
const reset = () => vm.runInContext("subState.key='';subState.t=0;", sandbox);
const sub = () => els["subprogress"].textContent;
const still = () => els["still-working"].textContent;

// Research: searching first, then the reading count.
reset();
renderSub({ status: "working",
  events: [{ event: "facts", data: { claims: 6 } }] }, 0);
assert.strictEqual(sub(), "Muse Spark is searching the web");
assert.strictEqual(still(), "");
renderSub({ status: "working", events: [
  { event: "facts", data: { claims: 6 } },
  { event: "fetch", data: { done: 3, total: 6 } },
] }, 1000);
assert.strictEqual(sub(), "Reading sources: 3 of 6");

// Check counts finished claims.
renderSub({ status: "working", events: [
  { event: "researched", data: {} },
  { event: "verifying", data: {} },
  { event: "verify", data: { done: 4, total: 6 } },
] }, 2000);
assert.strictEqual(sub(), "Facts checked: 4 of 6");

// Paint mirrors the Checked so far counter.
renderSub({ status: "working", events: [
  { event: "painting", data: {} },
  { event: "painted",
    data: { accepted: 1, dropped: 0, attempted: 3 } },
] }, 3000);
assert.strictEqual(sub(), "Painted 1 of 3");

// A resume rebuilds the line from the stored events alone.
reset();
renderSub({ status: "working", events: [
  { event: "painting", data: {} },
  { event: "checked_facts", data: { items: [] } },
  { event: "painted",
    data: { accepted: 2, dropped: 1, attempted: 3 } },
] }, 50000);
assert.strictEqual(sub(), "Painted 2 of 2");

// Twenty seconds without events shows the still-working line with the
// active step; the next event clears it.
reset();
const quiet = [{ event: "painting", data: {} }];
renderSub({ status: "working", events: quiet }, 0);
assert.strictEqual(still(), "");
renderSub({ status: "working", events: quiet }, 19999);
assert.strictEqual(still(), "");
renderSub({ status: "working", events: quiet }, 20000);
assert.strictEqual(still(),
  "Still working: Paint can take a minute or two.");
renderSub({ status: "working", events: [...quiet,
  { event: "painted", data: { accepted: 1, dropped: 0, attempted: 3 } },
] }, 21000);
assert.strictEqual(still(), "");

// Terminal states never nag.
reset();
renderSub({ status: "done", events: quiet }, 99999);
assert.strictEqual(still(), "");
renderSub({ status: "failed", events: quiet }, 99999);
assert.strictEqual(still(), "");
reset();
renderSub({ status: "done",
  events: [{ event: "render", data: {} }],
  result: { film_url: "/film/x/film.html" } }, 99999);
assert.strictEqual(sub(), "");

console.log("sub-progress and still-working: OK");
