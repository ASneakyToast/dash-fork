export const CHEER_MS = 1500;
export const SETTLE_MS = 2000;
export const SINK_MS = 3000;
export const THINK_MS = 2500;
export const PEARL_MS = 3000;
export const MAX_CREATURES = 14;
export const KEEP_MS = { swimming: 600000, thinking: 600000, done: 240000, failed: 360000 };

export function createBrood() {
  return { creatures: new Map(), pearls: [] };
}

export function apply(brood, event, now) {
  const at = event.at * 1000;
  if (now - at > KEEP_MS.swimming) return;
  const { job_id: jobId, conversation_id: conversationId, kind } = event;
  const known = brood.creatures.get(jobId);
  const base = known ?? { jobId, conversationId, born: at, state: "swimming", at };
  const states = { started: "swimming", recalled: "thinking", done: "done", failed: "failed" };
  if (kind === "started") {
    brood.creatures.set(jobId, { ...base, born: at, at, state: "swimming" });
  } else if (kind in states) {
    brood.creatures.set(jobId, { ...base, at, state: states[kind] });
  } else if (kind === "remembered" && known) {
    brood.pearls.push({ jobId, at });
  }
}

export function prune(brood, now) {
  [...brood.creatures]
    .filter(([, c]) => now - c.at > KEEP_MS[c.state])
    .forEach(([id]) => brood.creatures.delete(id));
  [...brood.creatures]
    .sort(([, a], [, b]) => a.at - b.at)
    .slice(0, Math.max(0, brood.creatures.size - MAX_CREATURES))
    .forEach(([id]) => brood.creatures.delete(id));
  brood.pearls = brood.pearls.filter((p) => now - p.at < PEARL_MS && brood.creatures.has(p.jobId));
}

export function phase(creature, now) {
  const age = now - creature.at;
  if (creature.state === "failed") return age < SINK_MS ? "sinking" : "sunk";
  if (creature.state === "done") {
    if (age < CHEER_MS) return "cheering";
    return age < CHEER_MS + SETTLE_MS ? "settling" : "resting";
  }
  return creature.state === "thinking" && age < THINK_MS ? "thinking" : "swimming";
}

export function tally(brood, now) {
  const phases = [...brood.creatures.values()].map((c) => phase(c, now));
  const count = (...names) => phases.filter((p) => names.includes(p)).length;
  return {
    swimming: count("swimming", "thinking"),
    resting: count("cheering", "settling", "resting"),
    failed: count("sinking", "sunk"),
  };
}

export function describe(mood, tallied, waiting) {
  const feelings = {
    content: "Mother is content.",
    busy: "Mother is busy.",
    strained: "Mother is overwhelmed.",
    sick: "Mother is unwell.",
    asleep: "Mother is asleep. No worker is running.",
  };
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const parts = [
    tallied.swimming && `${tallied.swimming} swimming`,
    tallied.resting && `${tallied.resting} resting`,
    tallied.failed && `${tallied.failed} lost`,
    waiting && plural(waiting, "egg"),
  ].filter(Boolean);
  return [feelings[mood] ?? feelings.content, ...parts].join(" · ");
}
