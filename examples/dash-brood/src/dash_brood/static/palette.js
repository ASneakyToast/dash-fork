export const TOKENS = {
  waterTop: "brood.water.top",
  waterMid: "brood.water.mid",
  waterDeep: "brood.water.deep",
  floor: "brood.floor",
  weed: "brood.weed",
  light: "brood.light",
  eggShell: "brood.egg.shell",
  eggShade: "brood.egg.shade",
  pearl: "brood.pearl",
  ink: "brood.ink",
  sclera: "brood.sclera",
  labelBg: "brood.label.bg",
  labelText: "brood.label.text",
  sleep: "brood.sleep",
  bezel: "brood.bezel",
  bezelEdge: "brood.bezel.edge",
  mood: {
    content: "brood.mood.content",
    busy: "brood.mood.busy",
    strained: "brood.mood.strained",
    sick: "brood.mood.sick",
    asleep: "brood.mood.asleep",
  },
};

export function readPalette(get, tokens = TOKENS) {
  const read = (node) =>
    typeof node === "string" ? get(node) : Object.fromEntries(Object.entries(node).map(([key, child]) => [key, read(child)]));
  return read(tokens);
}

export const darker = (color, percent) => `color-mix(in oklab, ${color}, black ${percent}%)`;
export const lighter = (color, percent) => `color-mix(in oklab, ${color}, white ${percent}%)`;
export const alpha = (color, opacity) => `color-mix(in srgb, ${color} ${Math.round(opacity * 100)}%, transparent)`;
