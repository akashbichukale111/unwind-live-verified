# web/

## What is actually here

`web/static/` — **the operator interface. [BUILT].** Three files: `index.html`,
`style.css`, `app.js`. Served by FastAPI at `/`, canvas-rendered, no build step,
no bundler, no external JavaScript.

```bash
make ui          # http://127.0.0.1:8000
make ui-check    # drives it in a real browser and asserts the numbers
```

## What is here and is NOT used

`app/`, `package.json`, `next.config.ts`, `tsconfig.json` — **a Next.js 15
skeleton reserved in Task 1 and never built on.** It is dead. Nothing imports
it, `npm install` has never been run, and the interface does not touch it.

It is left in place rather than deleted so the record of the decision survives,
but it should not be read as a component of the system.

## Why static files instead

Three reasons, in order of weight:

1. **The demo has to survive bad wifi.** A single origin with no bundle, no
   hydration and no CDN dependency has fewer ways to fail in front of a judge.
   The one external request — the Google Fonts stylesheet — is non-blocking, and
   the field renders correctly without it.
2. **The field is a canvas, not a component tree.** 4,206 nodes at 60 fps is a
   `requestAnimationFrame` loop writing `fillRect`. A framework would sit beside
   that loop contributing nothing to it.
3. **No npm.** The build container has no route to the npm registry, so a
   Next.js app could not have been installed, let alone verified. Shipping an
   unbuilt, unrun frontend would have been exactly the kind of claim this
   repository refuses to make.

## The seven colours and the contrast problem

The palette and the 4.5:1 floor are in tension, and the resolution is recorded
in `style.css` and enforced by `scripts/check_contrast.py`: against the dark
field only `--bone` (14.98:1) and `--amber` (6.21:1) clear the floor, so
`--graphite`, `--oxide` and `--verdigris` are used for lines, fills and the
paper — where `--oxide` reads at 6.24:1 — and never for text on the field.

`make contrast` recomputes all of it and fails the build.
