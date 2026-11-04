// Location help: EXIF probe, submit gating, geo feedback and the
// after-No hint, driven against the landing page with stub globals.
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.match(/<script nonce="[^"]*">([\s\S]*?)<\/script>/);
assert(script, "no inline page script");
const src = script[1];

function extract(name, args) {
  const found = src.match(
    new RegExp("(?:async )?function " + name + "\\(" + args +
      "\\) \\{[\\s\\S]*?\\n\\}"));
  assert(found, "no " + name + "(" + args + ")");
  return found[0];
}

// --- Markup: the question, its buttons, the geo note ---------------------
assert(html.includes('<div id="locq" class="hidden">'),
  "no hidden location question");
assert(html.includes("This photo has no location. Where is the landmark?"),
  "no location question text");
assert(html.includes('id="locq-text"'), "no question text line");
for (const id of ["loc-here", "loc-type", "loc-auto"]) {
  assert(html.includes('id="' + id + '"'), "no #" + id);
}
assert(html.includes("I'm standing in front of it now"), "no here button");
assert(html.includes("I'll type its name and town"), "no type button");
assert(html.includes("Let Muse Spark recognise it"), "no auto button");
assert(html.includes('id="geo-note"'), "no geo feedback line");

// --- jpegGpsPresent: true / false / "unknown" -----------------------------
function bytes(arr) {
  return new Uint8Array(arr).buffer;
}

function gpsTiff(bigEndian, tags) {
  const tiff = new Uint8Array(128);
  const view = new DataView(tiff.buffer);
  const bo = !bigEndian;
  const set16 = (o, v) => view.setUint16(o, v, bo);
  const set32 = (o, v) => view.setUint32(o, v, bo);
  if (bigEndian) { tiff[0] = 0x4d; tiff[1] = 0x4d; }
  else { tiff[0] = 0x49; tiff[1] = 0x49; }
  set16(2, 42);
  set32(4, 8);
  set16(8, 1);
  set16(10, 0x8825); set16(12, 4); set32(14, 1); set32(18, 26);
  set32(22, 0);
  set16(26, tags.length);
  tags.forEach((tag, i) => {
    const e = 28 + i * 12;
    set16(e, tag); set16(e + 2, 5); set32(e + 4, 1); set32(e + 8, 96);
  });
  set32(28 + tags.length * 12, 0);
  return tiff;
}

function app1(tiffBytes) {
  const head = [0xff, 0xe1, 0, 0, 0x45, 0x78, 0x69, 0x66, 0, 0];
  const len = tiffBytes.length + 8;
  head[2] = (len >> 8) & 0xff;
  head[3] = len & 0xff;
  return new Uint8Array([...head, ...tiffBytes]);
}

function jpeg(payloads) {
  const parts = [0xff, 0xd8];
  for (const part of payloads) { parts.push(...part); }
  parts.push(0xff, 0xd9);
  return bytes(parts);
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(extract("jpegGpsPresent", "buf"), sandbox);
const jpegGpsPresent = vm.runInContext("jpegGpsPresent", sandbox);

assert.strictEqual(jpegGpsPresent(jpeg([app1(gpsTiff(false, [1, 2, 3, 4]))])),
  true, "little-endian GPS found");
assert.strictEqual(jpegGpsPresent(jpeg([app1(gpsTiff(true, [1, 2, 3, 4]))])),
  true, "big-endian GPS found");
assert.strictEqual(jpegGpsPresent(jpeg([app1(gpsTiff(false, [2, 4]))])), true,
  "latitude plus longitude without refs counts");
assert.strictEqual(jpegGpsPresent(jpeg([app1(gpsTiff(false, [0]))])), false,
  "a version tag alone is no fix");
assert.strictEqual(jpegGpsPresent(jpeg([app1(gpsTiff(false, [1, 2]))])), false,
  "latitude without longitude is no fix");
assert.strictEqual(jpegGpsPresent(jpeg([app1(gpsTiff(false, [2]))])), false,
  "latitude alone is no fix");

const noGpsTiff = new Uint8Array(14);
noGpsTiff[0] = 0x49; noGpsTiff[1] = 0x49;
new DataView(noGpsTiff.buffer).setUint16(2, 42, true);
new DataView(noGpsTiff.buffer).setUint32(4, 8, true);
assert.strictEqual(jpegGpsPresent(jpeg([app1(noGpsTiff)])), false,
  "EXIF without GPS is false");
assert.strictEqual(jpegGpsPresent(jpeg([])), false, "no EXIF is false");
assert.strictEqual(
  jpegGpsPresent(bytes([0x89, 0x50, 0x4e, 0x47, 1, 2, 3])), "unknown",
  "non-JPEG is unknown");
assert.strictEqual(jpegGpsPresent(jpeg([new Uint8Array([0xff, 0xe1])])),
  "unknown", "truncated marker is unknown");

// --- decideSubmitState truth table ----------------------------------------
vm.runInContext(
  extract("decideSubmitState", "locNeeded, locChoice, placeText"), sandbox);
const decideSubmitState =
  vm.runInContext("decideSubmitState", sandbox);
assert.strictEqual(decideSubmitState(false, null, ""), false);
assert.strictEqual(decideSubmitState(true, null, ""), true);
assert.strictEqual(decideSubmitState(true, "auto", ""), false);
assert.strictEqual(decideSubmitState(true, "here", ""), false);
assert.strictEqual(decideSubmitState(true, null, "Haarlem"), false);
assert.strictEqual(decideSubmitState(true, null, "  "), true);

// --- requestGeo: asked once, 10 s timeout, both feedback lines ------------
let geoCalls = [];
const lat = { value: "" };
const lon = { value: "" };
const geoNote = { textContent: "" };
const locq = { classList: { add() {}, remove() {} } };
sandbox.document = {
  getElementById: (id) => (
    { lat, lon, "geo-note": geoNote, locq }[id] || null),
  querySelector: () => null,
};
sandbox.navigator = {
  geolocation: {
    getCurrentPosition: (ok, fail, opts) => { geoCalls.push([ok, fail, opts]); },
  },
};
sandbox.submitBtnForTest = { disabled: true };
sandbox.photoSeq = 0;
vm.runInContext(extract("requestGeo", ""), sandbox);
vm.runInContext(
  "function updateSubmit() { submitBtnForTest.disabled = true; }" +
  "function hideLocQ() {}", sandbox);
const requestGeo = vm.runInContext("requestGeo", sandbox);
assert.strictEqual(geoCalls.length, 0, "nothing asked before the tap");
requestGeo();
assert.strictEqual(geoCalls.length, 1, "one request per tap");
assert.strictEqual(geoCalls[0][2].timeout, 10000, "10 s timeout");
geoCalls[0][0]({ coords: { latitude: 52.1, longitude: 4.3 } });
assert.strictEqual(lat.value, 52.1);
assert.strictEqual(lon.value, 4.3);
assert.strictEqual(geoNote.textContent, "Location added.");
geoCalls = [];
requestGeo();
geoCalls[0][1]({ code: 1 });
assert.strictEqual(geoNote.textContent,
  "Location blocked or unavailable. Type the name and town instead.");

// A late fix for an older photo never lands on the new one.
vm.runInContext("locChoice = null;", sandbox);
lat.value = "";
lon.value = "";
geoNote.textContent = "";
sandbox.photoSeq = 21;
geoCalls = [];
requestGeo();
sandbox.photoSeq = 22;
geoCalls[0][0]({ coords: { latitude: 52.1, longitude: 4.3 } });
assert.strictEqual(lat.value, "", "stale latitude applied");
assert.strictEqual(lon.value, "", "stale longitude applied");
assert.strictEqual(geoNote.textContent, "", "stale note applied");
assert.strictEqual(vm.runInContext("locChoice", sandbox), null,
  "stale choice applied");
geoCalls = [];
requestGeo();
sandbox.photoSeq = 23;
geoCalls[0][1]({ code: 1 });
assert.strictEqual(geoNote.textContent, "", "stale error applied");

// The tap is the only trigger: no other call site requests a position.
const callSites = src.match(/getCurrentPosition\(/g) || [];
assert.strictEqual(callSites.length, 1, "one getCurrentPosition call site");
assert(src.includes('document.getElementById("geo").onclick = requestGeo;'),
  "geo button wired to requestGeo");
assert(src.includes(
  'document.getElementById("loc-here").onclick = requestGeo;'),
  "here button wired to requestGeo");

// --- After No: hint shows, the photo input is untouched --------------------
vm.runInContext(extract("notConfirmedHint", "message"), sandbox);
const notConfirmedHint = vm.runInContext("notConfirmedHint", sandbox);
assert.strictEqual(
  notConfirmedHint("Not confirmed. Only the identification ran."),
  "Type its name and town under 'Where is it?' and try again. " +
  "This run used one of your tries.");
assert.strictEqual(notConfirmedHint("Ready."), "");
assert.strictEqual(notConfirmedHint(""), "");

const touched = [];
sandbox.document = {
  getElementById: (id) => { touched.push(id); return null; },
  createElement: () => ({ textContent: "", href: "" }),
  createTextNode: () => ({}),
};
const box = { textContent: "", appendChild() {} };
vm.runInContext(extract("showResult", "box, st"), sandbox);
vm.runInContext("showResult", sandbox)(box, { status: "done",
  result: { message: "Not confirmed. Only the identification ran." } });
assert(box.textContent.includes("Type its name and town"), "hint shown");
assert(!touched.includes("upload"), "form untouched, photo kept");

// --- photoChanged: clears the old fix, guards out-of-order reads --------
{
  const nodes = {};
  function node() {
    return { value: "", files: [], textContent: "",
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener() {} };
  }
  const stage = {
    locNeeded: false, locChoice: "stale",
    photoInput: node(), preview: node(),
    lat: node(), lon: node(), geoNote: node(),
    locq: node(), locqText: node(),
    gpsOf: () => Promise.resolve(false),
    submits: 0,
  };
  const ctx = { locNeeded: stage.locNeeded, locChoice: stage.locChoice,
    photoSeq: 0,
    photoInput: stage.photoInput, preview: stage.preview,
    document: { getElementById: (id) => (
      { lat: stage.lat, lon: stage.lon, "geo-note": stage.geoNote,
        locq: stage.locq, "locq-text": stage.locqText }[id] || null) },
    URL: { createObjectURL: () => "blob:picked" },
    photoHasGps: (file) => stage.gpsOf(file),
    updateSubmit: () => { stage.submits += 1; },
    locqShown: null,
    console };
  ctx.document.getElementById("locq").classList.toggle = (cls, force) => {
    ctx.locqShown = !force;
  };
  vm.createContext(ctx);
  vm.runInContext(extract("photoChanged", ""), ctx);
  vm.runInContext("globalThis.changed = photoChanged;", ctx);

  (async () => {
    // A new photo clears the earlier browser fix and its note.
    stage.lat.value = "prior-fix";
    stage.lon.value = "prior-fix";
    stage.geoNote.textContent = "Location added.";
    stage.photoInput.files = [{}];
    await vm.runInContext("changed()", ctx);
    assert.strictEqual(stage.lat.value, "", "old latitude cleared");
    assert.strictEqual(stage.lon.value, "", "old longitude cleared");
    assert.strictEqual(stage.geoNote.textContent, "", "old note cleared");
    assert.strictEqual(vm.runInContext("locChoice", ctx), null);
    assert.strictEqual(ctx.locqShown, true, "question shows without GPS");
    assert.strictEqual(stage.locqText.textContent,
      "This photo has no location. Where is the landmark?");

    // When the probe cannot tell, the question says so.
    stage.gpsOf = () => Promise.resolve("unknown");
    await vm.runInContext("changed()", ctx);
    assert.strictEqual(stage.locqText.textContent,
      "We couldn't read a location from this photo. " +
      "Where is the landmark?");

    // A slow read for a photo no longer picked is ignored.
    const waiting = {};
    stage.gpsOf = (file) => new Promise((resolve) => {
      waiting[file.name] = resolve;
    });
    const first = { name: "first" };
    const second = { name: "second" };
    stage.photoInput.files = [first];
    const slow = vm.runInContext("changed()", ctx);
    stage.photoInput.files = [second];
    const fast = vm.runInContext("changed()", ctx);
    waiting.second(false);
    await fast;
    assert.strictEqual(ctx.locqShown, true, "second photo needs a place");
    waiting.first(true);
    await slow;
    assert.strictEqual(ctx.locqShown, true, "stale GPS ignored");
    assert.strictEqual(
      vm.runInContext("locNeeded", ctx), true, "stale result ignored");
  })().then(
    () => console.log("location help: OK"),
    (err) => { console.error(err); process.exit(1); });
}
