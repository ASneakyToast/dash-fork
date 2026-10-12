export const KEYS = { theme: "dash.theme", mode: "dash.mode", applied: "dash.applied" };

const DEFAULT = "default";

export function forcedMode(theme) {
  return theme && theme.modes.length === 1 ? theme.modes[0] : null;
}

export function resolve(themes, stored) {
  const theme = themes.find((t) => t.name === stored.theme) ?? null;
  const mode = forcedMode(theme) ?? (["light", "dark"].includes(stored.mode) ? stored.mode : "auto");
  return { theme: theme ? theme.name : DEFAULT, mode };
}

export function apply(root, choice) {
  if (choice.theme === DEFAULT) delete root.dataset.theme;
  else root.dataset.theme = choice.theme;
  if (choice.mode === "auto") delete root.dataset.mode;
  else root.dataset.mode = choice.mode;
}

export function varFor(tokens, name) {
  if (name.startsWith("--")) return name;
  const token = tokens.find((t) => t.name === name);
  if (!token) throw new Error(`unknown theme token ${name}`);
  return token.var;
}

export function createTheme({ manifest, root, dark, style, storage }) {
  const listeners = new Set();
  const read = (key) => {
    try {
      return storage.getItem(key) ?? "";
    } catch {
      return "";
    }
  };
  const write = (key, value) => {
    try {
      storage.setItem(key, value);
    } catch {
      return;
    }
  };
  const current = () => ({ theme: root.dataset.theme ?? DEFAULT, mode: root.dataset.mode ?? "auto" });
  const notify = () => listeners.forEach((fn) => fn(api.mode()));
  const api = {
    themes: () => manifest.themes,
    tokens: () => manifest.tokens,
    overrides: () => manifest.overrides,
    current,
    mode() {
      return root.dataset.mode ?? (dark.matches ? "dark" : "light");
    },
    get(name) {
      return style().getPropertyValue(varFor(manifest.tokens, name)).trim();
    },
    select(wanted) {
      const prefs = {
        theme: wanted.theme ?? read(KEYS.theme),
        mode: wanted.mode ?? read(KEYS.mode),
      };
      const choice = resolve(manifest.themes, prefs);
      apply(root, choice);
      write(KEYS.theme, choice.theme);
      write(KEYS.mode, ["light", "dark"].includes(prefs.mode) ? prefs.mode : "auto");
      write(KEYS.applied, `${choice.theme} ${choice.mode}`);
      notify();
      return choice;
    },
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
  dark.addEventListener("change", () => {
    if (!root.dataset.mode) notify();
  });
  api.select({});
  return api;
}
