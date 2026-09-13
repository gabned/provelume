"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");

function page({compact = false, seconds = 3, expires = 13000, badge = true} = {}) {
  const callbacks = {};
  const listeners = (owner) => (name, fn) => { callbacks[`${owner}:${name}`] = fn; };
  const state = {wall: 10000, monotonic: 0, focuses: 0, intervals: 0};
  const summary = {focus: () => { state.focuses += 1; }};
  const inside = {};
  const navigation = {
    open: true, querySelector: () => summary,
    contains: (node) => node === inside || node === summary,
    addEventListener: listeners("navigation"),
  };
  const media = {matches: compact, addEventListener: listeners("media")};
  const cue = {
    dataset: {remainingSeconds: String(seconds), expiresAt: new Date(expires).toISOString()},
    isConnected: true, remove() { this.isConnected = false; },
  };
  const document = {
    querySelector: () => navigation,
    querySelectorAll: () => badge ? [cue] : [],
    addEventListener: listeners("document"),
  };
  const window = {
    matchMedia: () => media, addEventListener: listeners("window"),
    setInterval: (fn) => { state.intervals += 1; callbacks.tick = fn; return 1; },
    clearInterval: () => { state.intervals = 0; },
  };
  const forbidden = () => { throw new Error("Presentation accessed a forbidden capability"); };
  vm.runInNewContext(source, {
    document, window, performance: {now: () => state.monotonic},
    Date: {parse: Date.parse, now: () => state.wall},
    fetch: forbidden, XMLHttpRequest: forbidden,
    localStorage: new Proxy({}, {get: forbidden, set: forbidden}),
  });
  return {state, navigation, media, cue, inside, callbacks};
}

const desktop = page();
assert.equal(desktop.navigation.open, true);
desktop.callbacks["document:keydown"]({key: "Escape"});
assert.equal(desktop.navigation.open, true);
assert.equal(desktop.state.focuses, 0);
desktop.media.matches = true;
desktop.callbacks["media:change"]();
assert.equal(desktop.navigation.open, false);
desktop.navigation.open = true;
desktop.callbacks["document:click"]({target: desktop.inside});
assert.equal(desktop.navigation.open, true);
desktop.callbacks["document:click"]({target: {}});
assert.equal(desktop.navigation.open, false);
assert.equal(desktop.state.focuses, 0);
desktop.navigation.open = true;
desktop.callbacks["document:keydown"]({key: "Escape"});
assert.equal(desktop.navigation.open, false);
assert.equal(desktop.state.focuses, 1);
desktop.navigation.open = true;
desktop.callbacks["navigation:focusout"]({relatedTarget: {}});
assert.equal(desktop.navigation.open, false);
assert.equal(desktop.state.focuses, 1);
desktop.media.matches = false;
desktop.callbacks["media:change"]();
assert.equal(desktop.navigation.open, true);
assert.equal(page({compact: true}).navigation.open, false);

const ordinary = page();
ordinary.state.wall = 12999;
ordinary.state.monotonic = 2999;
ordinary.callbacks.tick();
assert.equal(ordinary.cue.isConnected, true);
ordinary.state.wall = 13000;
ordinary.callbacks.tick();
assert.equal(ordinary.cue.isConnected, false);
assert.equal(ordinary.state.intervals, 0);

const rollback = page();
rollback.state.wall = 0;
rollback.state.monotonic = 3000;
rollback.callbacks.tick();
assert.equal(rollback.cue.isConnected, false, "Wall-clock rollback cannot extend a live cue");

for (const event of ["document:visibilitychange", "window:pageshow"]) {
  const resumed = page();
  resumed.state.wall = 20000;
  resumed.callbacks[event]();
  assert.equal(resumed.cue.isConnected, false, "Resumed pages expire stale cues");
}
assert.equal(page({seconds: 0}).cue.isConnected, false);
assert.equal(page({seconds: "invalid"}).cue.isConnected, false);
assert.equal(page({expires: 9000}).cue.isConnected, false);
assert.equal(page({badge: false}).state.intervals, 0);
process.stdout.write("Cura navigation, focus and publication expiry contracts passed\n");
