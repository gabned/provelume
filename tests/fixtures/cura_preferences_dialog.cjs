"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const callbacks = {};
const state = {opened: false, cancelled: false, prevented: 0};
const document = {
  activeElement: null,
  querySelector: (selector) => selector === "[data-preference-confirm]" ? dialog : null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};
const confirm = {focus: () => {document.activeElement = confirm;}};
const cancel = {
  focus: () => {document.activeElement = cancel;},
  click: () => {state.cancelled = true;},
};
const dialog = {
  close: () => {state.opened = false;},
  showModal: () => {state.opened = true; document.activeElement = cancel;},
  querySelector: () => cancel,
  querySelectorAll: () => [confirm, cancel],
  addEventListener: (event, callback) => {callbacks[event] = callback;},
};
const forbidden = () => {throw Error("Unexpected presentation capability");};
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), {
  document, window: {matchMedia: () => ({matches: false}), addEventListener: () => {},
                    clearInterval: () => {}},
  performance: {now: () => 0}, Date,
  fetch: forbidden, XMLHttpRequest: forbidden,
  localStorage: new Proxy({}, {get: forbidden, set: forbidden}),
});
assert.equal(state.opened, true);
assert.equal(document.activeElement, cancel);
const event = (key, shiftKey = false) => ({key, shiftKey,
  preventDefault: () => {state.prevented++;}});
callbacks.keydown(event("Tab"));
assert.equal(document.activeElement, confirm);
callbacks.keydown(event("Tab", true));
assert.equal(document.activeElement, cancel);
callbacks.keydown(event("Enter"));
assert.equal(state.prevented, 2);
callbacks.cancel(event("Escape"));
assert.equal(state.cancelled, true);
process.stdout.write("Preference dialog keyboard contracts passed\n");
