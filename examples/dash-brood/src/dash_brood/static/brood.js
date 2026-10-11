import { ASPECT, drawScene } from "./art.js";
import { apply, createBrood, describe, prune, tally } from "./model.js";

const MOTHER_MS = 4000;
const TITLES_MS = 20000;

export default function setup(dash) {
  const brood = createBrood();
  const titles = new Map();
  const state = { mother: { mood: "content", waiting: 0 }, skew: 0, hover: null, hits: [], loading: false };
  const clock = () => Date.now() + state.skew;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");

  async function refreshTitles() {
    if (state.loading) return;
    state.loading = true;
    try {
      (await dash.conversations()).forEach((c) => titles.set(c.id, c.title));
    } finally {
      state.loading = false;
    }
  }

  async function refreshMother() {
    try {
      state.mother = await dash.plugin.api("/mother");
      state.skew = state.mother.now * 1000 - Date.now();
    } catch {
      state.mother = { ...state.mother, mood: "asleep" };
    }
  }

  dash.addDock({
    id: "tank",
    title: "Brood",
    mount(root) {
      const frame = dash.el("div", { className: "brood-frame" });
      const canvas = dash.el("canvas", { className: "brood-canvas" });
      const status = dash.el("p", { className: "brood-status" });
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", "A mother squid and her brood. Each small squid is a job.");
      status.setAttribute("aria-live", "polite");
      frame.append(canvas);
      root.append(frame, status);
      const ctx = canvas.getContext("2d");
      let size = { w: 0, h: 0, dpr: 1 };

      const fit = () => {
        const box = frame.getBoundingClientRect();
        const w = Math.floor(Math.min(box.width, box.height * ASPECT));
        const h = Math.floor(w / ASPECT);
        const dpr = window.devicePixelRatio || 1;
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
        size = { w, h, dpr };
      };
      new ResizeObserver(fit).observe(frame);

      const hitAt = (e) => {
        const box = canvas.getBoundingClientRect();
        const x = e.clientX - box.left;
        const y = e.clientY - box.top;
        return state.hits
          .filter((h) => Math.hypot(h.x - x, h.y - y) < h.r)
          .sort((a, b) => Math.hypot(a.x - x, a.y - y) - Math.hypot(b.x - x, b.y - y))[0];
      };
      canvas.addEventListener("pointermove", (e) => {
        const hit = hitAt(e);
        state.hover = hit?.jobId ?? null;
        canvas.style.cursor = hit ? "pointer" : "default";
      });
      canvas.addEventListener("pointerleave", () => {
        state.hover = null;
      });
      canvas.addEventListener("click", (e) => {
        const hit = hitAt(e);
        if (hit) dash.openConversation(hit.conversationId);
      });

      const labelFor = (creature) => titles.get(creature.conversationId) ?? "conversation";

      function frameLoop(ms) {
        const now = clock();
        prune(brood, now);
        if (size.w > 0) {
          ctx.setTransform(size.dpr, 0, 0, size.dpr, 0, 0);
          state.hits = drawScene(ctx, {
            w: size.w,
            h: size.h,
            t: (ms / 1000) * (reduced.matches ? 0.2 : 1),
            now,
            brood,
            mood: state.mother.mood,
            waiting: state.mother.waiting,
            hover: state.hover,
            labelFor,
          });
        }
        const text = describe(state.mother.mood, tally(brood, now), state.mother.waiting);
        if (text !== status.textContent) status.textContent = text;
        requestAnimationFrame(frameLoop);
      }
      requestAnimationFrame(frameLoop);
    },
  });

  dash.onActivity((event) => {
    apply(brood, event, clock());
    if (!titles.has(event.conversation_id)) refreshTitles();
  });

  refreshMother();
  refreshTitles();
  setInterval(refreshMother, MOTHER_MS);
  setInterval(refreshTitles, TITLES_MS);
}
