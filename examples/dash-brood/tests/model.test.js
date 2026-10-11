import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CHEER_MS,
  KEEP_MS,
  MAX_CREATURES,
  SETTLE_MS,
  SINK_MS,
  THINK_MS,
  apply,
  createBrood,
  describe,
  phase,
  prune,
  tally,
} from "../src/dash_brood/static/model.js";

const NOW = 10_000_000;
const event = (kind, jobId = "j1", agoMs = 0, data = {}) => ({
  id: `${NOW - agoMs}-0`,
  at: (NOW - agoMs) / 1000,
  kind,
  job_id: jobId,
  conversation_id: `c-${jobId}`,
  data,
});

test("a job hatches a creature that swims", () => {
  const brood = createBrood();
  apply(brood, event("started"), NOW);
  const creature = brood.creatures.get("j1");
  assert.equal(creature.conversationId, "c-j1");
  assert.equal(phase(creature, NOW), "swimming");
});

test("recalling memories makes it think for a moment, then swim on", () => {
  const brood = createBrood();
  apply(brood, event("started", "j1", 5000), NOW);
  apply(brood, event("recalled"), NOW);
  const creature = brood.creatures.get("j1");
  assert.equal(creature.born, NOW - 5000);
  assert.equal(phase(creature, NOW), "thinking");
  assert.equal(phase(creature, NOW + THINK_MS), "swimming");
});

test("a finished job cheers, settles and rests", () => {
  const brood = createBrood();
  apply(brood, event("started", "j1", 9000), NOW);
  apply(brood, event("done"), NOW);
  const creature = brood.creatures.get("j1");
  assert.equal(phase(creature, NOW), "cheering");
  assert.equal(phase(creature, NOW + CHEER_MS), "settling");
  assert.equal(phase(creature, NOW + CHEER_MS + SETTLE_MS), "resting");
});

test("a failed job sinks and stays down", () => {
  const brood = createBrood();
  apply(brood, event("started", "j1", 9000), NOW);
  apply(brood, event("failed"), NOW);
  const creature = brood.creatures.get("j1");
  assert.equal(phase(creature, NOW), "sinking");
  assert.equal(phase(creature, NOW + SINK_MS), "sunk");
});

test("an event for a job we never saw start still makes a creature", () => {
  const brood = createBrood();
  apply(brood, event("done", "late"), NOW);
  assert.equal(phase(brood.creatures.get("late"), NOW), "cheering");
});

test("history older than the keep window is ignored", () => {
  const brood = createBrood();
  apply(brood, event("started", "old", KEEP_MS.swimming + 1), NOW);
  assert.equal(brood.creatures.size, 0);
});

test("replaying the same history twice gives the same brood", () => {
  const history = [event("started", "a", 8000), event("recalled", "a", 7000), event("done", "a", 6000)];
  const once = createBrood();
  const twice = createBrood();
  history.forEach((e) => apply(once, e, NOW));
  [...history, ...history].forEach((e) => apply(twice, e, NOW));
  assert.deepEqual([...twice.creatures], [...once.creatures]);
});

test("a stored memory is a pearl only for a creature we know", () => {
  const brood = createBrood();
  apply(brood, event("remembered", "ghost"), NOW);
  assert.equal(brood.pearls.length, 0);
  apply(brood, event("started"), NOW);
  apply(brood, event("remembered"), NOW);
  assert.equal(brood.pearls.length, 1);
  prune(brood, NOW + 10_000);
  assert.equal(brood.pearls.length, 0);
});

test("prune forgets creatures after their keep time", () => {
  const brood = createBrood();
  apply(brood, event("started", "a", 1000), NOW);
  apply(brood, event("done", "b", 1000), NOW);
  prune(brood, NOW + KEEP_MS.done);
  assert.deepEqual([...brood.creatures.keys()], ["a"]);
});

test("prune keeps only the newest creatures when there are too many", () => {
  const brood = createBrood();
  Array.from({ length: MAX_CREATURES + 3 }, (_, i) => i).forEach((i) =>
    apply(brood, event("started", `j${i}`, 100_000 - i * 1000), NOW),
  );
  prune(brood, NOW);
  assert.equal(brood.creatures.size, MAX_CREATURES);
  assert.equal(brood.creatures.has("j0"), false);
  assert.equal(brood.creatures.has(`j${MAX_CREATURES + 2}`), true);
});

test("describe tells the mother's mood and the counts", () => {
  const brood = createBrood();
  apply(brood, event("started", "a"), NOW);
  apply(brood, event("started", "b"), NOW);
  apply(brood, event("failed", "c"), NOW);
  assert.equal(describe("busy", tally(brood, NOW), 1), "Mother is busy. · 2 swimming · 1 lost · 1 egg");
  assert.equal(describe("asleep", tally(createBrood(), NOW), 0), "Mother is asleep. No worker is running.");
  assert.equal(describe("unknown", tally(createBrood(), NOW), 2), "Mother is content. · 2 eggs");
});
