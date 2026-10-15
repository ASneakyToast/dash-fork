export const LOOPY_STATES = [
  "idle",
  "thinking",
  "searching",
  "reading",
  "tool",
  "writing",
  "waiting",
  "done",
  "error",
] as const;

export type LoopyState = (typeof LOOPY_STATES)[number];

export interface LoopySnapshot {
  state: LoopyState;
  detail: string;
  since: number;
}

export type LoopyListener = (snapshot: LoopySnapshot) => void;

interface StateStyle {
  label: string;
  color: string;
  motion: string;
}

const STYLES: Record<LoopyState, StateStyle> = {
  idle: { label: "Idle", color: "#8a8f98", motion: "breathe 3s ease-in-out infinite" },
  thinking: { label: "Thinking", color: "#7c5cff", motion: "spin 1.2s linear infinite" },
  searching: { label: "Searching", color: "#2fa8ff", motion: "spin 0.7s linear infinite" },
  reading: { label: "Reading", color: "#20c997", motion: "pulse 1s ease-in-out infinite" },
  tool: { label: "Using a tool", color: "#ffb020", motion: "wobble 0.6s ease-in-out infinite" },
  writing: { label: "Writing", color: "#ff6bb5", motion: "spin 2s linear infinite" },
  waiting: { label: "Waiting for you", color: "#c0c4cc", motion: "breathe 1.6s ease-in-out infinite" },
  done: { label: "Done", color: "#2ecc71", motion: "pop 0.4s ease-out 1" },
  error: { label: "Error", color: "#ff4d4f", motion: "shake 0.4s ease-in-out 2" },
};

const CSS = `
:host { display: inline-flex; align-items: center; gap: 0.6em; font: 500 14px/1.2 system-ui, sans-serif; color: inherit; }
.ring { width: var(--loopy-size, 28px); height: var(--loopy-size, 28px); flex: none; transition: color 0.25s; }
.ring circle { fill: none; stroke: currentColor; stroke-width: 3; stroke-linecap: round; }
.track { opacity: 0.2; }
.arc { stroke-dasharray: 60 100; transform-origin: 50% 50%; }
.text { display: flex; flex-direction: column; min-width: 0; }
.detail { opacity: 0.65; font-weight: 400; font-size: 0.85em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.detail:empty { display: none; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes breathe { 50% { opacity: 0.4; } }
@keyframes pulse { 50% { transform: scale(0.8); } }
@keyframes wobble { 25% { transform: rotate(-20deg); } 75% { transform: rotate(20deg); } }
@keyframes pop { 0% { transform: scale(0.6); } 70% { transform: scale(1.15); } }
@keyframes shake { 25% { transform: translateX(-3px); } 75% { transform: translateX(3px); } }
@media (prefers-reduced-motion: reduce) { .arc { animation: none !important; } }
`;

const TEMPLATE = `
<style>${CSS}</style>
<svg class="ring" viewBox="0 0 40 40" part="ring" aria-hidden="true">
  <circle class="track" cx="20" cy="20" r="16" />
  <circle class="arc" part="arc" cx="20" cy="20" r="16" pathLength="160" />
</svg>
<span class="text">
  <span class="label" part="label"></span>
  <span class="detail" part="detail"></span>
</span>
`;

export function isLoopyState(value: unknown): value is LoopyState {
  return typeof value === "string" && (LOOPY_STATES as readonly string[]).includes(value);
}

export class Loopy {
  private snapshot: LoopySnapshot = { state: "idle", detail: "", since: Date.now() };
  private readonly listeners = new Set<LoopyListener>();
  private readonly root: ShadowRoot | HTMLElement;
  private readonly ring: SVGElement;
  private readonly arc: SVGElement;
  private readonly label: HTMLElement;
  private readonly detailEl: HTMLElement;

  constructor(root: ShadowRoot | HTMLElement) {
    this.root = root;
    this.root.innerHTML = TEMPLATE;
    this.ring = this.part<SVGElement>("ring");
    this.arc = this.part<SVGElement>("arc");
    this.label = this.part<HTMLElement>("label");
    this.detailEl = this.part<HTMLElement>("detail");
    this.render();
  }

  private part<T extends Element>(name: string): T {
    const el = this.root.querySelector<T & Element>(`[part="${name}"]`);
    if (!el) throw new Error(`loopy template is missing part ${name}`);
    return el as T;
  }

  get state(): LoopyState {
    return this.snapshot.state;
  }

  get detail(): string {
    return this.snapshot.detail;
  }

  setState(state: LoopyState, detail = ""): void {
    if (!isLoopyState(state)) throw new TypeError(`unknown loopy state: ${String(state)}`);
    if (state === this.snapshot.state && detail === this.snapshot.detail) return;
    this.snapshot = { state, detail, since: Date.now() };
    this.render();
    this.listeners.forEach((listener) => listener(this.snapshot));
  }

  subscribe(listener: LoopyListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  render(): void {
    const { state, detail } = this.snapshot;
    const style = STYLES[state];
    this.ring.style.color = style.color;
    this.arc.style.animation = "none";
    void this.arc.getBoundingClientRect();
    this.arc.style.animation = style.motion;
    this.label.textContent = style.label;
    this.detailEl.textContent = detail;
    const host = this.root instanceof ShadowRoot ? this.root.host : this.root;
    host.setAttribute("role", "status");
    host.setAttribute("aria-live", "polite");
    host.setAttribute("aria-label", detail ? `${style.label}: ${detail}` : style.label);
  }
}

export class LoopyAnimation extends HTMLElement {
  static observedAttributes = ["state", "detail"];

  readonly loopy: Loopy;
  private syncing = false;

  constructor() {
    super();
    this.loopy = new Loopy(this.attachShadow({ mode: "open" }));
    this.loopy.subscribe((snapshot) =>
      this.dispatchEvent(new CustomEvent("loopy-change", { detail: snapshot, bubbles: true, composed: true })),
    );
  }

  attributeChangedCallback(): void {
    if (this.syncing) return;
    const state = this.getAttribute("state") ?? "idle";
    this.loopy.setState(isLoopyState(state) ? state : "idle", this.getAttribute("detail") ?? "");
  }

  setState(state: LoopyState, detail = ""): void {
    this.syncing = true;
    this.setAttribute("state", state);
    this.setAttribute("detail", detail);
    this.syncing = false;
    this.loopy.setState(state, detail);
  }
}

if (!customElements.get("loopy-animation")) customElements.define("loopy-animation", LoopyAnimation);

declare global {
  interface HTMLElementTagNameMap {
    "loopy-animation": LoopyAnimation;
  }
}
