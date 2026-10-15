# loopy

`<loopy-animation>` is a web component that shows what an agent is doing.

```html
<script type="module" src="./dist/loopy.js"></script>
<loopy-animation state="thinking" detail="planning"></loopy-animation>
```

```ts
const el = document.querySelector("loopy-animation")!;
el.setState("tool", "web_search");
el.addEventListener("loopy-change", (e) => console.log(e.detail));
```

States: `idle`, `thinking`, `searching`, `reading`, `tool`, `writing`, `waiting`, `done`, `error`.

```sh
npm install
npm run build
```

Open `demo.html` to try each state.
