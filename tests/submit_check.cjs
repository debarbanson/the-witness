// Drives the landing page script with a stub DOM: the first tap on
// "Make my film" shows the upload at once and blocks every further tap
// until the film ends (4 Nov: a silent upload invited a second tap, the
// two uploads got two visitor ids, and two polling loops fought over the
// page), a failed or refused upload frees the button, and a resumed film
// blocks a new one. Usage:
// node submit_check.cjs <landing.html> <double|fail|refused|resumed>
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");
const mode = process.argv[3] || "double";
const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
assert(html.includes('id="upload-note"'), "no upload note under the button");

function makeEl(id) {
  const el = {
    id, style: {}, dataset: {}, innerHTML: "",
    className: "", files: [], value: "", disabled: false,
    attrs: {},
    children: [],
    appendChild(c) { this.children.push(c); return c; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    click() { if (typeof el.onclick === "function") { return el.onclick(); } },
  };
  let text = "";
  Object.defineProperty(el, "textContent", {
    get: () => text,
    set: (v) => { text = String(v); el.children.length = 0; },
  });
  return el;
}

const byId = {};
const saved = mode === "resumed" ? { "witness.job": "job-9" } : {};
const calls = [];
const alerts = [];
let releaseUpload = null;
let jobDone = false;

const button = makeEl("make");
button.textContent = "Make my film";
const place = makeEl("place");

function jsonResponse(obj, status = 200) {
  return { ok: status >= 200 && status < 300, status,
           json: async () => obj };
}

async function fakeFetch(url, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  calls.push(`${method} ${url}`);
  if (url === "/api/jobs" && method === "POST") {
    if (mode === "fail") { throw new Error("network down"); }
    if (mode === "refused") {
      return jsonResponse({ error: "Today's films are used up." }, 429);
    }
    await new Promise((r) => { releaseUpload = r; });
    return jsonResponse({ job_id: "job-1" });
  }
  if (/^\/api\/jobs\/job-[19]$/.test(url) && method === "GET") {
    if (!jobDone) {
      return jsonResponse({ status: "working",
        events: [{ event: "researching", data: {} }] });
    }
    return jsonResponse({ status: "done",
      events: [{ event: "render", data: {} }],
      result: { film_url: "/film/job-1/tok/film.html" } });
  }
  return jsonResponse({ status: "working", events: [] });
}

const sandbox = {
  console,
  document: {
    getElementById: (id) => byId[id] || (byId[id] = makeEl(id)),
    createElement: () => makeEl(""),
    createTextNode: (text) => ({ text }),
    querySelector: (sel) => {
      if (sel === '#upload button[type="submit"]') { return button; }
      if (sel === '#upload input[name="place"]') { return place; }
      return null;
    },
    querySelectorAll: () => [],
  },
  fetch: fakeFetch,
  localStorage: {
    getItem: (k) => (k in saved ? saved[k] : null),
    setItem: (k, v) => { saved[k] = String(v); },
    removeItem: (k) => { delete saved[k]; },
  },
  setTimeout: (fn) => { setImmediate(fn); return 0; },
  setInterval: () => 0,
  clearInterval: () => {},
  alert: (msg) => { alerts.push(String(msg)); },
  FormData: function () {},
  URL,
  addEventListener: () => {},
  window: {},
};
sandbox.window.localStorage = sandbox.localStorage;
vm.createContext(sandbox);

const flush = () => new Promise((r) => setImmediate(r));
async function settle(n = 30) { for (let i = 0; i < n; i++) { await flush(); } }
const posts = () => calls.filter((c) => c === "POST /api/jobs").length;
const tap = () => sandbox.document.getElementById("upload")
  .onsubmit({ preventDefault() {} });

(async () => {
  vm.runInContext(script[1], sandbox);
  const form = sandbox.document.getElementById("upload");
  assert.strictEqual(typeof form.onsubmit, "function", "form has no submit handler");
  const note = sandbox.document.getElementById("upload-note");

  if (mode === "resumed") {
    await settle();
    assert(calls.includes("GET /api/jobs/job-9"), "the saved film was not resumed");
    assert.strictEqual(button.disabled, true, "button free while a resumed film runs");
    assert(button.textContent.includes("Making your film"),
      `no film label while resumed: ${button.textContent}`);
    tap();
    await settle();
    assert.strictEqual(posts(), 0, "a tap during a resumed film started another");
    jobDone = true;
    await settle(60);
    assert.strictEqual(button.disabled, false, "button not freed after the resumed film");
    assert.strictEqual(button.textContent, "Make my film", "label not restored");
    console.log("resumed film blocks a new one: OK");
    return;
  }

  if (mode === "fail" || mode === "refused") {
    tap();
    assert.strictEqual(button.disabled, true, "button free during the upload");
    await settle();
    assert.strictEqual(alerts.length, 1, `expected one alert, got ${alerts}`);
    assert.strictEqual(button.disabled, false, "button not freed after a failed upload");
    assert.strictEqual(button.textContent, "Make my film", "label not restored");
    assert.strictEqual(note.textContent, "", "upload note left behind");
    tap();
    await settle();
    assert.strictEqual(posts(), 2, "the retry did not upload again");
    console.log(`${mode} upload frees the button: OK`);
    return;
  }

  // double: a slow upload, a second and a third impatient tap
  tap();
  assert.strictEqual(button.disabled, true, "button still free while uploading");
  assert(button.textContent.includes("Uploading your photo"),
    `no uploading label: ${button.textContent}`);
  assert(note.textContent.includes("Keep this page open"),
    `no upload note: ${note.textContent}`);
  tap();
  await settle();
  assert.strictEqual(posts(), 1, "a second tap started a second upload");
  assert(releaseUpload, "the upload never started");
  releaseUpload();
  await settle();
  assert(calls.includes("GET /api/jobs/job-1"), "the film was never polled");
  assert.strictEqual(button.disabled, true, "button free while the film runs");
  assert(button.textContent.includes("Making your film"),
    `no film label: ${button.textContent}`);
  assert.strictEqual(note.textContent, "", "upload note kept after the upload");
  tap();
  await settle();
  assert.strictEqual(posts(), 1, "a tap during the film started another");
  jobDone = true;
  await settle(60);
  assert.strictEqual(button.disabled, false, "button not freed after the film");
  assert.strictEqual(button.textContent, "Make my film", "label not restored");
  console.log("one tap, one film: OK");
})().catch((err) => { console.error(err.stack || String(err)); process.exit(1); });
