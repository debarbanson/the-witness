// Drives the landing page script with a stub DOM: resume from a saved
// job id without a new admission, lost-contact without cancel, gone
// jobs clearing the save, the Cancel button, the checked-facts panel
// while painting, too-little end states, failed steps and the confirm
// tap. Usage:
// node resume_check.cjs <landing.html> <resume|misses|gone|cancel|facts|toolittle|failed|decide|decidefail>
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");
const mode = process.argv[3] || "resume";
const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
assert(!script[1].includes("pagehide"), "pagehide must not cancel");
assert(html.includes('id="cancel"'), "no Cancel button");

function makeEl(id) {
  const el = {
    id, style: {}, dataset: {}, innerHTML: "",
    className: "", files: [], value: "",
    children: [],
    appendChild(c) { this.children.push(c); return c; },
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

const lis = ["identify", "research", "check", "paint", "film"].map((step) => {
  const span = { textContent: "" };
  const classes = new Set();
  return {
    dataset: { step },
    querySelector: (sel) => (sel === ".model" ? span : null),
    classList: {
      toggle: (name, on) => {
        if (on) { classes.add(name); } else { classes.delete(name); }
      },
      contains: (name) => classes.has(name),
    },
  };
});

const byId = {};
const saved = { "witness.job": "job-9" };
const calls = [];
let pollCount = 0;
let cancelled = false;
let decided = false;

function jsonResponse(obj, status = 200) {
  return { ok: status >= 200 && status < 300, status,
           json: async () => obj };
}

async function fakeFetch(url, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  calls.push(`${method} ${url}`);
  if (url === "/api/jobs" && method === "POST") {
    return jsonResponse({ job_id: "job-fresh" });
  }
  if (mode === "misses") {
    throw new Error("network down");
  }
  if (mode === "gone") {
    return jsonResponse({ detail: "gone" }, 403);
  }
  if (/\/api\/jobs\/job-9(\/|$)/.test(url) && method === "DELETE") {
    cancelled = true;
    return jsonResponse({ cancelled: true });
  }
  if (url === "/api/jobs/job-9/decide" && method === "POST") {
    if (mode === "decidefail") {
      throw new Error("network down");
    }
    decided = true;
    return jsonResponse({ decided: true });
  }
  if (url === "/api/jobs/job-9" && method === "GET") {
    pollCount += 1;
    if (mode === "cancel") {
      if (cancelled) {
        return jsonResponse({ status: "cancelled", events: [],
          result: { message: "job cancelled" } });
      }
      return jsonResponse({ status: "working", events: [] });
    }
    if (mode === "facts") {
      const items = [
        { stamp: "1850", text: "The mill stood tall.",
          url: "https://a.example/mill",
          guess: "Poldertoren", lat: 52.1 },
        { stamp: "1932", text: "The mill burnt down.",
          url: "https://a.example/fire" },
      ];
      const base = [
        { event: "checked_facts", data: { items } },
      ];
      if (pollCount < 2) {
        return jsonResponse({ status: "working", events: [
          { event: "painting", data: { model: "Muse Image" } }, ...base] });
      }
      if (pollCount < 3) {
        return jsonResponse({ status: "working", events: [
          { event: "painting", data: { model: "Muse Image" } }, ...base,
          { event: "painted", data: { year: 1850, verdict: "matches",
            accepted: 1, dropped: 0, attempted: 2 } }] });
      }
      return jsonResponse({ status: "done",
        events: [{ event: "render", data: {} }, ...base,
          { event: "painted", data: { year: 1932, verdict: "matches",
            accepted: 2, dropped: 0, attempted: 2 } }],
        result: { film_url: "/film/job-9/tok/film.html" } });
    }
    if (mode === "toolittle") {
      if (pollCount < 2) {
        return jsonResponse({ status: "working",
          events: [{ event: "verifying",
                     data: { model: "Muse Spark Open on Baseten" } }] });
      }
      return jsonResponse({ status: "done",
        events: [{ event: "verifying",
                   data: { model: "Muse Spark Open on Baseten" } }],
        result: { message: "No film this time. We found 7 possible facts.",
          claims: [],
          sources: [{ domain: "en.wikipedia.org",
                      url: "https://en.wikipedia.org/wiki/X",
                      outcome: "read" }] } });
    }
    if (mode === "failed") {
      if (pollCount < 2) {
        return jsonResponse({ status: "working",
          events: [{ event: "painting", data: { model: "Muse Image" } }] });
      }
      return jsonResponse({ status: "failed",
        events: [{ event: "painting", data: { model: "Muse Image" } }],
        result: { message: "the runner failed; nothing kept" } });
    }
    if (mode === "subcheck") {
      return jsonResponse({ status: "done",
        events: [{ event: "researched", data: {} },
          { event: "verifying", data: {} },
          { event: "verify", data: { done: 6, total: 6 } }],
        result: { message: "Too little evidence for a film.",
          claims: [{ year: 1850, claim: "The mill stood.",
                     url: "https://a.example/mill" }] } });
    }
    if (mode === "decide" || mode === "decidefail") {
      if (decided || pollCount >= 6) {
        return jsonResponse({ status: "done",
          events: [{ event: "render", data: {} }],
          result: { film_url: "/film/job-9/tok/film.html" } });
      }
      return jsonResponse({ status: "working", events: [],
        confirm: { name: "Test Tower", kind: "tower", description: "" },
        decision: null });
    }
    if (pollCount < 2) {
      return jsonResponse({ status: "working",
        events: [{ event: "painting", data: { model: "Muse Image" } }] });
    }
    return jsonResponse({ status: "done",
      events: [{ event: "render", data: {} }],
      result: { film_url: "/film/job-9/tok/film.html" } });
  }
  return jsonResponse({ status: "working", events: [] });
}

const sandbox = {
  console,
  document: {
    getElementById: (id) => byId[id] || (byId[id] = makeEl(id)),
    createElement: () => makeEl(""),
    createTextNode: (text) => ({ text }),
    querySelector: () => null,
    querySelectorAll: (sel) => (sel === "#steps li" ? lis : []),
  },
  fetch: fakeFetch,
  localStorage: {
    getItem: (k) => (k in saved ? saved[k] : null),
    setItem: (k, v) => { saved[k] = String(v); },
    removeItem: (k) => { delete saved[k]; },
  },
  setTimeout: (fn) => { fn(); return 0; },
  setInterval: () => 0,
  clearInterval: () => {},
  alert: () => {},
  FormData: function () {},
  URL,
  addEventListener: () => {},
  window: {},
};
sandbox.window.localStorage = sandbox.localStorage;
vm.createContext(sandbox);

(async () => {
  vm.runInContext(script[1], sandbox);
  const flush = () => new Promise((r) => setImmediate(r));
  if (mode === "decide" || mode === "decidefail") {
    const yes = sandbox.document.getElementById("yes");
    const no = sandbox.document.getElementById("no");
    assert(yes.onclick && no.onclick, "confirm buttons have no handler");
    for (let i = 0; i < 10; i++) { await flush(); }
    const tap = mode === "decide" ? yes.onclick() : no.onclick();
    assert.strictEqual(yes.style.display, "none", "yes visible after tap");
    assert.strictEqual(no.style.display, "none", "no visible after tap");
    await tap;
    for (let i = 0; i < 10; i++) { await flush(); }
    const note = sandbox.document.getElementById("decide-note");
    if (mode === "decide") {
      assert(calls.includes("POST /api/jobs/job-9/decide"), "no decide POST");
      assert(note.textContent.includes("Thanks. Researching now"),
        "no yes feedback");
      assert.strictEqual(yes.style.display, "none", "yes back too soon");
    } else {
      assert.strictEqual(yes.style.display, "", "yes not restored");
      assert.strictEqual(no.style.display, "", "no not restored");
      assert(note.textContent.includes("That didn't go through"),
        "no retry line");
    }
    console.log("confirm tap feedback: OK");
    return;
  }
  if (mode === "cancel") {
    const btn = sandbox.document.getElementById("cancel");
    const result = sandbox.document.getElementById("result");
    assert(btn.onclick, "Cancel button has no handler");
    const clicked = btn.onclick();
    assert(btn.disabled === true, "cancel not disabled on click");
    assert(result.textContent.includes("Cancelling"),
      "no cancelling feedback");
    await clicked;
    for (let i = 0; i < 20; i++) { await flush(); }
    assert(calls.includes("DELETE /api/jobs/job-9"),
      `no cancel DELETE in ${JSON.stringify(calls)}`);
    assert(result.textContent.includes("Cancelled"),
      "no cancelled confirmation");
    assert(btn.style.display === "none", "cancel visible after end");
    console.log("cancel feedback then cancelled: OK");
    return;
  }
  for (let i = 0; i < 60; i++) { await flush(); }
  const posts = calls.filter((c) => c === "POST /api/jobs");
  if (mode === "resume") {
    assert.strictEqual(posts.length, 0, "resume admitted a second job");
    assert(calls.some((c) => c === "GET /api/jobs/job-9"), "never polled");
    assert(!("witness.job" in saved), "save not cleared at finish");
    const text = sandbox.document.getElementById("result").textContent;
    const kids = sandbox.document.getElementById("result").children.length;
    assert(text.includes("/film/job-9/tok/film.html") || kids > 0,
      "film link not shown");
    assert.strictEqual(
      sandbox.document.getElementById("cancel").style.display, "none",
      "cancel visible after end");
    console.log("resume keeps the film with no second admission: OK");
  } else if (mode === "misses") {
    assert.strictEqual(posts.length, 0, "misses admitted a job");
    assert(!calls.some((c) => /DELETE|POST \/api\/jobs\/job-9\/cancel/.test(c)),
      "misses cancelled the job");
    assert(sandbox.document.getElementById("result").textContent
      .includes("Lost contact"), "no lost-contact message");
    assert(saved["witness.job"] === "job-9", "save cleared on misses");
    console.log("three misses keep the save and send no cancel: OK");
  } else if (mode === "gone") {
    assert(!("witness.job" in saved), "gone job not cleared");
    assert.strictEqual(
      sandbox.document.getElementById("job").style.display, "none");
    console.log("gone job clears the save: OK");
  } else if (mode === "toolittle") {
    assert.strictEqual(posts.length, 0, "toolittle admitted a second job");
    const result = sandbox.document.getElementById("result");
    assert(result.textContent.includes("No film this time"),
      "too-little message missing");
    assert(JSON.stringify(result).includes("en.wikipedia.org"),
      "checked source missing");
    assert(!result.textContent.includes("Checked facts"),
      "no facts, no heading");
    assert(lis[2].classList.contains("done"), "check not done");
    assert(!lis[2].classList.contains("current"), "check stuck current");
    assert(lis[3].classList.contains("skipped"), "paint not skipped");
    assert(lis[4].classList.contains("skipped"), "film not skipped");
    assert.strictEqual(
      sandbox.document.getElementById("events").textContent,
      "Finished: no film");
    assert.strictEqual(
      sandbox.document.getElementById("cancel").style.display, "none",
      "cancel visible after end");
    console.log("too-little end state with skipped steps: OK");
  } else if (mode === "subcheck") {
    assert.strictEqual(
      sandbox.document.getElementById("subprogress").textContent,
      "Facts checked: 6 of 6", "check count not rebuilt from events");
    assert(sandbox.document.getElementById("result").textContent
      .includes("Checked facts"), "facts heading missing");
    assert.strictEqual(
      sandbox.document.getElementById("events").textContent,
      "Finished: no film");
    console.log("facts-only end keeps the check count: OK");
  } else if (mode === "failed") {
    assert(lis[3].classList.contains("stopped"), "paint not stopped");
    assert(!lis[3].classList.contains("current"), "paint stuck current");
    assert(sandbox.document.getElementById("result").textContent
      .includes("nothing kept"), "failure message missing");
    console.log("failed step shows stopped: OK");
  } else if (mode === "facts") {
    assert.strictEqual(posts.length, 0, "facts admitted a second job");
    assert.strictEqual(
      sandbox.document.getElementById("facts").style.display, "block",
      "facts panel hidden during painting");
    const list = sandbox.document.getElementById("facts-list");
    assert.strictEqual(list.children.length, 2, "both facts listed");
    assert.strictEqual(list.children[0].children[0].textContent, "1850 ");
    assert.strictEqual(list.children[0].children[2].href,
      "https://a.example/mill");
    assert.strictEqual(
      sandbox.document.getElementById("paint-count").textContent,
      "Painted 2 of 2");
    const rendered = JSON.stringify(list);
    assert(!rendered.includes("Poldertoren"), "a guess reached the page");
    assert(!rendered.includes("52.1"), "a coordinate reached the page");
    const text = sandbox.document.getElementById("result").textContent;
    const kids = sandbox.document.getElementById("result").children.length;
    assert(text.includes("/film/job-9/tok/film.html") || kids > 0,
      "film link not shown after the facts");
    console.log("checked facts then the film with no second admission: OK");
  }
})().catch((e) => { process.stderr.write(String(e)); process.exit(1); });
