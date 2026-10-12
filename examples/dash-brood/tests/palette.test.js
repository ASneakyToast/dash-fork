import assert from "node:assert/strict";
import { test } from "node:test";

import { TOKENS, alpha, darker, lighter, readPalette } from "../src/dash_brood/static/palette.js";

test("readPalette reads every token once, nested moods included", () => {
  const asked = [];

  const palette = readPalette((name) => {
    asked.push(name);
    return `<${name}>`;
  });

  assert.equal(palette.waterTop, "<brood.water.top>");
  assert.equal(palette.mood.asleep, "<brood.mood.asleep>");
  assert.equal(new Set(asked).size, asked.length);
  assert.equal(asked.length, 14 + 5);
});

test("a missing token fails loudly rather than painting with nothing", () => {
  const get = (name) => {
    throw new Error(`unknown theme token ${name}`);
  };

  assert.throws(() => readPalette(get), /unknown theme token brood\.water\.top/);
});

test("the shading helpers build CSS color-mix strings", () => {
  assert.equal(darker("red", 25), "color-mix(in oklab, red, black 25%)");
  assert.equal(lighter("red", 30), "color-mix(in oklab, red, white 30%)");
  assert.equal(alpha("red", 0.13), "color-mix(in srgb, red 13%, transparent)");
  assert.equal(alpha("red", 0), "color-mix(in srgb, red 0%, transparent)");
});

test("every token name in TOKENS is in the brood namespace", () => {
  const names = JSON.stringify(TOKENS).match(/"brood\.[a-z.]+"/g);

  assert.ok(names.length > 0);
});
