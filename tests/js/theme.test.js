import assert from "node:assert/strict";
import { test } from "node:test";

import { KEYS, apply, createTheme, forcedMode, resolve, varFor } from "../../src/dash/static/theme.js";

const both = { name: "paper", title: "Paper", source: "dash", modes: ["light", "dark"], warnings: [] };
const night = { name: "night", title: "Night", source: "tide", modes: ["dark"], warnings: [] };
const tokens = [
  { name: "dash.color.bg", var: "--dash-color-bg" },
  { name: "tide.water.top", var: "--tide-water-top" },
];
const manifest = { themes: [both, night], tokens, overrides: null };

function fixture(saved = {}) {
  const store = new Map(Object.entries(saved));
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const listeners = [];
  const dark = { matches: false, addEventListener: (_, fn) => listeners.push(fn) };
  const root = { dataset: {} };
  const values = { "--dash-color-bg": " #fafaf9 ", "--tide-water-top": "#123456" };
  const style = () => ({ getPropertyValue: (name) => values[name] ?? "" });
  const theme = createTheme({ manifest, root, dark, style, storage });
  return { theme, root, store, dark, listeners };
}

test("a theme that sets one mode forces it", () => {
  assert.equal(forcedMode(night), "dark");
  assert.equal(forcedMode(both), null);
  assert.equal(forcedMode(null), null);
});

test("resolve falls back to the default theme and to auto mode", () => {
  assert.deepEqual(resolve(manifest.themes, { theme: "gone", mode: "sepia" }), { theme: "default", mode: "auto" });
  assert.deepEqual(resolve(manifest.themes, { theme: "paper", mode: "dark" }), { theme: "paper", mode: "dark" });
  assert.deepEqual(resolve(manifest.themes, { theme: "night", mode: "light" }), { theme: "night", mode: "dark" });
});

test("apply sets and clears the attributes", () => {
  const root = { dataset: { theme: "paper", mode: "dark" } };

  apply(root, { theme: "default", mode: "auto" });

  assert.deepEqual(root.dataset, {});
  apply(root, { theme: "paper", mode: "light" });
  assert.deepEqual(root.dataset, { theme: "paper", mode: "light" });
});

test("varFor maps a token name, passes a variable through and rejects a typo", () => {
  assert.equal(varFor(tokens, "tide.water.top"), "--tide-water-top");
  assert.equal(varFor(tokens, "--anything"), "--anything");
  assert.throws(() => varFor(tokens, "tide.water.tpo"), /unknown theme token/);
});

test("get reads a token's computed value", () => {
  const { theme } = fixture();

  assert.equal(theme.get("dash.color.bg"), "#fafaf9");
});

test("a saved choice is applied at boot", () => {
  const { root } = fixture({ [KEYS.theme]: "paper", [KEYS.mode]: "dark" });

  assert.deepEqual(root.dataset, { theme: "paper", mode: "dark" });
});

test("storage that throws does not stop the theme", () => {
  const root = { dataset: {} };
  const storage = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
  };
  const dark = { matches: true, addEventListener() {} };

  const theme = createTheme({ manifest, root, dark, style: () => ({ getPropertyValue: () => "" }), storage });

  assert.equal(theme.mode(), "dark");
  assert.deepEqual(theme.select({ theme: "paper" }), { theme: "paper", mode: "auto" });
});

test("select persists the choice, the preference and the applied pair", () => {
  const { theme, store } = fixture();

  theme.select({ theme: "night", mode: "light" });

  assert.equal(store.get(KEYS.theme), "night");
  assert.equal(store.get(KEYS.mode), "light");
  assert.equal(store.get(KEYS.applied), "night dark");
});

test("leaving a forced theme restores the user's own mode preference", () => {
  const { theme, root } = fixture();
  theme.select({ theme: "paper", mode: "light" });

  theme.select({ theme: "night" });
  assert.equal(root.dataset.mode, "dark");
  theme.select({ theme: "paper" });

  assert.equal(root.dataset.mode, "light");
});

test("onChange fires on select and on a system change only in auto mode", () => {
  const { theme, dark, listeners } = fixture();
  const seen = [];
  const off = theme.onChange((mode) => seen.push(mode));

  theme.select({ theme: "paper", mode: "dark" });
  listeners.forEach((fn) => fn());
  theme.select({ mode: "auto" });
  dark.matches = true;
  listeners.forEach((fn) => fn());
  off();
  theme.select({ mode: "light" });

  assert.deepEqual(seen, ["dark", "light", "dark"]);
});

test("mode follows the system when none is chosen", () => {
  const { theme, dark } = fixture();

  assert.equal(theme.mode(), "light");
  dark.matches = true;
  assert.equal(theme.mode(), "dark");
});
