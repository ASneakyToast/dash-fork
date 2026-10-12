import { CHEER_MS, PEARL_MS, SETTLE_MS, SINK_MS, phase } from "./model.js";
import { alpha, darker, lighter } from "./palette.js";

export const ASPECT = 9 / 19.5;

const TAU = Math.PI * 2;
const JOB = { sat: 66, light: 66 };
const SUNK = { sat: 8, light: 48 };
const MOODS = {
  content: { pulse: 0.8, eyes: "open", glow: 0.35, droop: 0 },
  busy: { pulse: 2, eyes: "wide", glow: 0.6, droop: 0 },
  strained: { pulse: 3.4, eyes: "wide", glow: 0.5, droop: 0 },
  sick: { pulse: 0.5, eyes: "dizzy", glow: 0.1, droop: 1 },
  asleep: { pulse: 0.3, eyes: "closed", glow: 0.05, droop: 0.6 },
};
const hsl = (hue, sat, light) => `hsl(${hue} ${sat}% ${light}%)`;
const SPOTS = [
  [-0.35, -1.0, 0.12],
  [0.3, -0.8, 0.09],
  [0.05, -1.35, 0.08],
  [-0.15, -0.5, 0.07],
  [0.45, -0.35, 0.1],
];

const ease = (u) => {
  const c = Math.min(1, Math.max(0, u));
  return c * c * (3 - 2 * c);
};
const lerp = (a, b, u) => a + (b - a) * u;
const mix = (from, to, u) => ({ x: lerp(from.x, to.x, u), y: lerp(from.y, to.y, u) });

export function hash(text, salt = "") {
  const h = [...`${text}${salt}`].reduce((acc, ch) => Math.imul(acc ^ ch.charCodeAt(0), 16777619), 2166136261);
  return (h >>> 0) / 2 ** 32;
}

function drawEyes(ctx, kind, look, p) {
  [-0.42, 0.42].forEach((x) => {
    ctx.save();
    ctx.translate(x, -0.05);
    ctx.lineCap = "round";
    ctx.strokeStyle = p.ink;
    ctx.lineWidth = 0.07;
    ctx.beginPath();
    if (kind === "happy") {
      ctx.arc(0, 0.1, 0.17, Math.PI * 1.1, Math.PI * 1.9);
    } else if (kind === "closed") {
      ctx.arc(0, -0.05, 0.17, Math.PI * 0.1, Math.PI * 0.9);
    } else if (kind === "x") {
      ctx.moveTo(-0.13, -0.13);
      ctx.lineTo(0.13, 0.13);
      ctx.moveTo(0.13, -0.13);
      ctx.lineTo(-0.13, 0.13);
    } else if (kind === "dizzy") {
      Array.from({ length: 24 }, (_, i) => i / 23).forEach((u, i) => {
        const a = u * TAU * 1.6;
        const r = u * 0.18;
        ctx[i ? "lineTo" : "moveTo"](Math.cos(a) * r, Math.sin(a) * r);
      });
    }
    if (["happy", "closed", "x", "dizzy"].includes(kind)) {
      ctx.stroke();
    } else {
      const r = kind === "wide" ? 0.26 : 0.2;
      ctx.fillStyle = p.sclera;
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, TAU);
      ctx.fill();
      ctx.fillStyle = p.ink;
      ctx.beginPath();
      ctx.arc(look[0] * 0.07, look[1] * 0.07, r * 0.52, 0, TAU);
      ctx.fill();
      ctx.fillStyle = p.sclera;
      ctx.beginPath();
      ctx.arc(look[0] * 0.07 - r * 0.15, look[1] * 0.07 - r * 0.18, r * 0.16, 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  });
}

function drawTentacles(ctx, o) {
  ctx.lineCap = "round";
  ctx.strokeStyle = darker(o.color, 15);
  Array.from({ length: o.tentacles }, (_, i) => {
    const spread = (i - (o.tentacles - 1) / 2) / ((o.tentacles - 1) / 2 || 1);
    const points = Array.from({ length: 9 }, (_, j) => {
      const u = j / 8;
      const sway = Math.sin(o.t * 2.2 + i * 0.9 - u * 3.4) * 0.22 * u * (1 - o.droop * 0.7);
      return [spread * 0.6 * (1 + u * 0.5) + sway, 0.45 + u * o.length * (1 - o.droop * 0.25)];
    });
    points.slice(1).forEach(([px, py], j) => {
      ctx.beginPath();
      ctx.moveTo(...points[j]);
      ctx.lineTo(px, py);
      ctx.lineWidth = 0.17 * (1 - (j + 1) / 9) + 0.025;
      ctx.stroke();
    });
  });
}

export function drawSquid(ctx, o) {
  const s = { eyes: "open", tentacles: 4, droop: 0, tilt: 0, alpha: 1, glow: 0.3, pulse: 1, look: [0, 0], length: 1, ...o };
  ctx.save();
  ctx.globalAlpha = s.alpha;
  ctx.translate(s.x, s.y);
  ctx.rotate(s.tilt);
  ctx.scale(s.size, s.size * (1 + Math.sin(s.t * s.pulse * 2) * 0.035));
  if (s.glow > 0) {
    const halo = ctx.createRadialGradient(0, -0.6, 0.3, 0, -0.6, 2.6);
    halo.addColorStop(0, alpha(s.color, s.glow));
    halo.addColorStop(1, alpha(s.color, 0));
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(0, -0.6, 2.6, 0, TAU);
    ctx.fill();
  }
  drawTentacles(ctx, s);
  ctx.fillStyle = darker(s.color, 18);
  [-1, 1].forEach((side) => {
    ctx.beginPath();
    ctx.ellipse(side * 0.62, -1.2, 0.42, 0.22, side * 0.9, 0, TAU);
    ctx.fill();
  });
  const body = ctx.createLinearGradient(0, -1.75, 0, 0.62);
  body.addColorStop(0, lighter(s.color, 30));
  body.addColorStop(1, darker(s.color, 25));
  ctx.fillStyle = body;
  ctx.beginPath();
  ctx.moveTo(0, -1.75);
  ctx.bezierCurveTo(0.55, -1.5, 0.95, -0.7, 0.8, 0.1);
  ctx.quadraticCurveTo(0.7, 0.62, 0, 0.62);
  ctx.quadraticCurveTo(-0.7, 0.62, -0.8, 0.1);
  ctx.bezierCurveTo(-0.95, -0.7, -0.55, -1.5, 0, -1.75);
  ctx.fill();
  SPOTS.forEach(([x, y, r], k) => {
    ctx.fillStyle = alpha(darker(s.color, 45), 0.35 + 0.2 * Math.sin(s.t * s.pulse * 2 + k));
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.fill();
  });
  drawEyes(ctx, s.eyes, s.look, s.palette);
  ctx.restore();
}

function drawBackground(ctx, w, h, t, p) {
  const water = ctx.createLinearGradient(0, 0, 0, h);
  water.addColorStop(0, p.waterTop);
  water.addColorStop(0.5, p.waterMid);
  water.addColorStop(1, p.waterDeep);
  ctx.fillStyle = water;
  ctx.fillRect(0, 0, w, h);
  [0, 1, 2].forEach((k) => {
    const x = w * (0.2 + 0.3 * k) + Math.sin(t * 0.15 + k * 2) * w * 0.05;
    const shaft = ctx.createLinearGradient(0, 0, 0, h * 0.8);
    shaft.addColorStop(0, alpha(p.light, 0.13));
    shaft.addColorStop(1, alpha(p.light, 0));
    ctx.fillStyle = shaft;
    ctx.beginPath();
    ctx.moveTo(x - w * 0.04, 0);
    ctx.lineTo(x + w * 0.04, 0);
    ctx.lineTo(x + w * 0.2, h * 0.8);
    ctx.lineTo(x - w * 0.12, h * 0.8);
    ctx.fill();
  });
  Array.from({ length: 36 }, (_, i) => i).forEach((i) => {
    const speed = 3 + hash(i, "v") * 6;
    const x = hash(i, "x") * w + Math.sin(t * 0.3 + i) * 8;
    const y = (hash(i, "y") * h + t * speed) % h;
    ctx.fillStyle = alpha(p.light, 0.12 + hash(i, "a") * 0.2);
    ctx.beginPath();
    ctx.arc(x, y, 0.6 + hash(i, "r") * 1.1, 0, TAU);
    ctx.fill();
  });
}

function drawFloor(ctx, w, h, t, p) {
  [0.06, 0.14, 0.87, 0.95].forEach((fx, k) => {
    ctx.strokeStyle = p.weed;
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.beginPath();
    Array.from({ length: 8 }, (_, j) => j / 7).forEach((u, j) => {
      const x = w * fx + Math.sin(t * 0.8 + k + u * 3) * 6 * u;
      const y = h * 0.93 - u * h * (0.1 + 0.03 * (k % 2));
      ctx[j ? "lineTo" : "moveTo"](x, y);
    });
    ctx.stroke();
  });
  ctx.fillStyle = p.floor;
  ctx.beginPath();
  ctx.moveTo(0, h);
  ctx.lineTo(0, h * 0.92);
  ctx.quadraticCurveTo(w * 0.3, h * 0.89, w * 0.55, h * 0.925);
  ctx.quadraticCurveTo(w * 0.8, h * 0.95, w, h * 0.91);
  ctx.lineTo(w, h);
  ctx.fill();
}

function drawEgg(ctx, x, y, r, t, i, p) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(Math.sin(t * 1.6 + i) * 0.12);
  const halo = ctx.createRadialGradient(0, 0, r * 0.4, 0, 0, r * 2.4);
  halo.addColorStop(0, alpha(p.eggShell, 0.35));
  halo.addColorStop(1, alpha(p.eggShell, 0));
  ctx.fillStyle = halo;
  ctx.beginPath();
  ctx.arc(0, 0, r * 2.4, 0, TAU);
  ctx.fill();
  const shell = ctx.createRadialGradient(-r * 0.3, -r * 0.4, r * 0.1, 0, 0, r * 1.3);
  shell.addColorStop(0, p.eggShell);
  shell.addColorStop(1, p.eggShade);
  ctx.fillStyle = shell;
  ctx.beginPath();
  ctx.ellipse(0, 0, r * 0.8, r, 0, 0, TAU);
  ctx.fill();
  ctx.restore();
}

function motherAt(w, h, t) {
  const size = w * 0.16;
  const y = h * 0.2 + Math.sin(t * 0.6) * h * 0.008;
  return { x: w / 2, y, size, base: { x: w / 2, y: y + size * 0.9 } };
}

function place(c, now, t, w, h, mother) {
  const a = hash(c.jobId, "a");
  const b = hash(c.jobId, "b");
  const d = hash(c.jobId, "c");
  const size = w * (0.042 + d * 0.014);
  const orbit = {
    x: w / 2 + Math.sin(t * 0.45 + a * TAU) * w * (0.2 + 0.14 * b),
    y: h * 0.5 + Math.cos(t * 0.6 + b * TAU) * h * 0.1 + (d - 0.5) * h * 0.08,
  };
  const floor = { x: w * (0.1 + 0.8 * a), y: h * (0.885 + 0.045 * b) };
  const age = now - c.at;
  const birth = ease((now - c.born) / 1200);
  const look = [Math.cos(t * 0.9 + a * TAU), Math.sin(t * 0.7 + b * TAU)];
  const hue = 170 + a * 160;
  const lively = { color: hsl(hue, JOB.sat, JOB.light), glow: 0.25, pulse: 1.4 + b, look, size: size * (0.3 + 0.7 * birth) };
  const kind = phase(c, now);
  const places = {
    swimming: () => ({ ...mix(mother.base, orbit, birth), ...lively }),
    thinking: () => ({ ...mix(mother.base, orbit, birth), ...lively, eyes: "wide" }),
    cheering: () => ({
      ...orbit,
      y: orbit.y - Math.abs(Math.sin(age / 150)) * size * 1.4,
      ...lively,
      eyes: "happy",
      size,
    }),
    settling: () => ({
      ...mix(orbit, floor, ease((age - CHEER_MS) / SETTLE_MS)),
      ...lively,
      eyes: "happy",
      size,
    }),
    resting: () => ({ ...floor, ...lively, eyes: "closed", glow: 0.1, pulse: 0.5, tilt: (b - 0.5) * 0.4, size }),
    sinking: () => {
      const u = ease(age / SINK_MS);
      return { ...mix(orbit, floor, u), ...lively, color: hsl(hue, lerp(JOB.sat, SUNK.sat, u), lerp(JOB.light, SUNK.light, u)), glow: 0, eyes: "x", tilt: u * Math.PI, alpha: 0.85, size };
    },
    sunk: () => ({ ...floor, ...lively, color: hsl(hue, SUNK.sat, SUNK.light), glow: 0, eyes: "x", tilt: Math.PI, alpha: 0.85, pulse: 0.2, size }),
  };
  return { c, phase: kind, ...places[kind]() };
}

function drawLabel(ctx, text, x, y, w, p) {
  ctx.font = `${Math.round(w * 0.042)}px system-ui, sans-serif`;
  const shown = text.length > 24 ? `${text.slice(0, 23)}…` : text;
  const width = ctx.measureText(shown).width + 16;
  const left = Math.min(Math.max(x - width / 2, 6), w - width - 6);
  ctx.fillStyle = p.labelBg;
  ctx.beginPath();
  ctx.roundRect(left, y, width, w * 0.075, 8);
  ctx.fill();
  ctx.fillStyle = p.labelText;
  ctx.textBaseline = "middle";
  ctx.fillText(shown, left + 8, y + w * 0.0375);
}

export function drawScene(ctx, scene) {
  const { w, h, t, now, brood, waiting, hover, labelFor, palette } = scene;
  const m = MOODS[scene.mood] ?? MOODS.content;
  const mother = motherAt(w, h, t);
  drawBackground(ctx, w, h, t, palette);
  drawFloor(ctx, w, h, t, palette);
  Array.from({ length: Math.min(waiting, 10) }, (_, i) => i).forEach((i) =>
    drawEgg(ctx, w * (0.12 + 0.76 * ((i * 0.618 + 0.1) % 1)), h * (0.945 + (i % 2) * 0.012), w * 0.024, t, i, palette),
  );
  const placed = [...brood.creatures.values()].map((c) => place(c, now, t, w, h, mother));
  const onFloor = ["settling", "resting", "sinking", "sunk"];
  placed.filter((p) => onFloor.includes(p.phase)).forEach((p) => drawSquid(ctx, { ...p, t, palette }));
  drawSquid(ctx, { ...m, color: palette.mood[scene.mood] ?? palette.mood.content, palette, x: mother.x, y: mother.y, size: mother.size, t, tentacles: 8, length: 1.5, tilt: Math.sin(t * 0.4) * 0.03 });
  if (scene.mood === "asleep") {
    ctx.fillStyle = alpha(palette.sleep, 0.7);
    ctx.font = `${Math.round(w * 0.07)}px system-ui, sans-serif`;
    [0, 1, 2].forEach((k) => {
      const u = ((t * 0.25 + k / 3) % 1);
      ctx.globalAlpha = 1 - u;
      ctx.fillText("z", mother.x + mother.size * (0.9 + u * 0.6), mother.y - mother.size * (0.8 + u * 1.2));
    });
    ctx.globalAlpha = 1;
  }
  placed.filter((p) => !onFloor.includes(p.phase)).forEach((p) => drawSquid(ctx, { ...p, t, palette }));
  const at = new Map(placed.map((p) => [p.c.jobId, p]));
  brood.pearls.forEach((pearl) => {
    const from = at.get(pearl.jobId);
    if (!from) return;
    const u = ease((now - pearl.at) / PEARL_MS);
    const p = mix(from, { x: mother.x, y: mother.y }, u);
    const x = p.x + Math.sin(u * 9) * 5;
    const glow = ctx.createRadialGradient(x, p.y, 0, x, p.y, w * 0.035);
    glow.addColorStop(0, alpha(palette.pearl, 0.95));
    glow.addColorStop(1, alpha(palette.pearl, 0));
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(x, p.y, w * 0.035, 0, TAU);
    ctx.fill();
  });
  const hits = placed.map((p) => ({ jobId: p.c.jobId, conversationId: p.c.conversationId, x: p.x, y: p.y, r: Math.max(p.size * 2.6, 28) }));
  const hovered = placed.find((p) => p.c.jobId === hover);
  if (hovered) drawLabel(ctx, labelFor(hovered.c), hovered.x, hovered.y + hovered.size * 2.2, w, palette);
  ctx.fillStyle = darker(palette.bezel, 55);
  ctx.beginPath();
  ctx.roundRect(w * 0.36, h * 0.012, w * 0.28, h * 0.02, h * 0.01);
  ctx.fill();
  return hits;
}
