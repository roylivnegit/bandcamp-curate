# React guidelines — crate-digger frontend

Applies to everything under `frontend/`. Derived from Vercel's
[react-best-practices](https://github.com/vercel-labs/agent-skills/tree/main/skills/react-best-practices)
skill (MIT, 70 rules in 8 categories), filtered down to what actually holds for **this** app and
annotated with where each rule bites here.

Rule ids below (`rerender-memo`, `async-parallel`, …) are that skill's. The full skill is installed
globally, so for the general explanation of any id either invoke the `react-best-practices` skill or
read the file directly:

```
~/.claude/skills/react-best-practices/rules/<id>.md   # one rule, with incorrect/correct examples
~/.claude/skills/react-best-practices/AGENTS.md       # all 70 expanded, ~108 KB
```

That copy is a machine-local install, **not** vendored into this repo — a fresh clone won't have it.
Re-fetch with:

```bash
curl -sL https://codeload.github.com/vercel-labs/agent-skills/tar.gz/refs/heads/main \
  | tar xz --strip-components=3 -C ~/.claude/skills/react-best-practices '*/skills/react-best-practices/*'
```

This document is the part that must stay in the repo, because it's the part that's about *our* code.

## What this app is, and which categories therefore apply

Vite + React 19 SPA, client-rendered, react-router, no framework. It talks to a separate FastAPI
origin over CORS with a bearer token. There is no SSR, no RSC, no server actions, no `next/*`.

| Category | Applies? |
|---|---|
| `async-` eliminating waterfalls | **Yes** — every screen is client fetches |
| `bundle-` bundle size | **Yes** — Vite splits on `import()` the same way |
| `server-` server-side perf | **No** — no server rendering. Skip all 10 rules |
| `client-` client data fetching | Partly — no SWR here (see deviations) |
| `rerender-` re-render | **Yes** — the highest-value category for the feed |
| `rendering-` rendering perf | Partly — hydration rules are moot, the rest apply |
| `js-` JS perf | **Yes** where a loop is per-row or per-keystroke |
| `advanced-` | Rarely — reach for it only with a measured problem |

No React Compiler is configured, so manual `memo`/`useCallback`/`useMemo` still carry weight. If the
compiler is ever enabled, revisit the memoization rules — most become unnecessary, but the
functional-`setState` and stale-response rules stay (they're correctness, not perf).

## Standing rules for new code here

**1. A list component that can grow past ~50 rows is `memo`'d, and its callbacks take the item.**
(`rerender-memo`, `rerender-functional-setstate`.) `memo` alone does nothing if the parent passes
`onLike={() => like(r)}` — that arrow is a new prop identity every render, so every card re-renders
on every unrelated parent state change. The pattern, as in `FeedCard` / `ScanFeedPage`:

- child props are the item, per-row primitives, and callbacks typed `(item) => void`
- the child does `onClick={() => onLike(rec)}` internally, where it costs nothing
- parent handlers are `useCallback` with **no unstable deps** — reach that via functional
  `setState` (`setRows(prev => …)`), never by depending on the state you're updating
- helpers those handlers call (`keyOf`) live at **module scope**, not in the component body

**2. Destructure hook return objects before depending on them.** `useFeedFilters` returns a fresh
object each render, so `[filters.setLabel]` as a dep list is a lint error and `[filters]` would
defeat the memoization. Pull out the individual stable callbacks: `const { includeTag, setLabel } =
filters`.

**3. In-flight guards go in a ref; only what renders goes in state.**
(`rerender-use-ref-transient-values`.) `ScanFeedPage` keeps `inFlight` (a ref, re-entry guard) and
`busyKeys` (state, drives `disabled`). Merging them into state would put `busyKeys` in every
handler's dep list and un-memoize the whole list on each click.

**4. Every fetch whose inputs can change while it's in flight takes a ticket.** Not from the skill —
from a bug this codebase had. `loadFirstPage` does `const req = ++feedSeq.current` and checks
`feedSeq.current === req` before each `setState`; `loadMore` reads the ticket without claiming one, so
a filter change discards its page instead of appending it to a different query's list. Two quick
genre-pill toggles are enough to reorder responses. Covered by the *"ignores a page that lands after
the filters moved on"* test — keep it green.

**5. Independent requests go through `Promise.all`.** (`async-parallel`.) Already the shape of
`loadFirstPage` (page + count), `like` (liked list + facets), and the scan-list poll (scans + `me`).
Two sequential `await`s on unrelated endpoints is the bug this rule exists to catch.

**6. Derive during render; don't mirror state into an effect.** (`rerender-derived-state-no-effect`.)
`ready`, `anyActive`, `kindWord`, `active` are all plain expressions. An effect whose only job is
`setX(f(y))` is always wrong here.

**7. Effect-scoped timers live in the effect closure, not a ref.** StrictMode double-invokes effects;
a shared `useRef` holds only the second timer id, so cleanup leaks the first. Use `const id =
window.setTimeout(…)` and clear `id`. Both pollers do this — note that `scan` / `scans` in those dep
arrays is the *re-arm signal* (the loader sets a fresh object), not a stray dependency; removing it
stops the poll after one tick.

**8. Per-keystroke work over a list gets memoized and deferred.** (`rerender-use-deferred-value`,
`js-cache-property-access`.) The genre dropdown filters thousands of facet tags: lowercase the search
keys once per list in `useMemo`, filter against `useDeferredValue(query)`, and render the message
from the deferred value so text and rows agree.

**9. Hoist regexes and other per-call allocations out of functions on a hot path.**
(`js-hoist-regexp`.) A regex *literal* is a new object per call — `BANDCAMP_HOST` in `lib/format.ts`
is at module scope because `bandcampHandle` runs once per card. Only hoist non-`/g` patterns;
a global regex carries mutable `lastIndex`.

**10. Long lists get `content-visibility: auto` + `contain-intrinsic-size`.**
(`rendering-content-visibility`.) On `.card` in `feed.css`. Cheaper than virtualization and needs no
library; the `auto` length keyword self-corrects after first render.

**11. New routes are `lazy()` + `Suspense`.** (`bundle-dynamic-imports`.) `App.tsx` splits on the
auth boundary so a signed-out visitor doesn't download the feed page or its 8 KB of CSS. Two
consequences: keep new pages behind `lazy()`, and **tests must `await findBy*`** for anything on a
lazy route — a synchronous `getBy*` on first paint sees the Suspense fallback.

**12. `useState` initializers: function form only for real work.** (`rerender-lazy-state-init`.)
`useState(() => parse(localStorage…))` yes; `useState(new Set())` no — the rule explicitly exempts
cheap literals, and the function form there is noise.

**13. Ternaries over `&&` when the left side is a number.** (`rendering-conditional-render`.)
`{n && <X/>}` renders a literal `0`. Strings and objects are safe and the existing `{error && …}`
sites are fine, so this is a rule for new code, not a cleanup task.

## Deliberate deviations

- **No SWR / react-query** (`client-swr-dedup`). `api/client.ts` is a deliberately small hand-rolled
  layer with centralized 401 handling; the app's requests are few and mostly not duplicated across
  components. If two components ever fetch the same endpoint independently, revisit — that's the
  cache's actual job.
- **Token in `localStorage`, unversioned key** (`client-localstorage-schema`). The trade is argued at
  length at the top of `api/client.ts`. It stores one opaque string, so there is no schema to
  version; the reads/writes are already `try`-wrapped for private mode. Version the key if it ever
  holds a structured value.
- **Static JSX not hoisted** (`rendering-hoist-jsx`). The brand mark in `AppHeader` / `AuthLayout`
  renders once per navigation; hoisting would trade readability for nothing measurable. Worth doing
  only inside something that re-renders in a loop.
- **`passive: true` not set on the dropdown's listeners**
  (`client-passive-event-listeners`). That rule is about scroll/touch/wheel, where a non-passive
  listener blocks scrolling. `mousedown`/`keydown` gain nothing. Do apply it if a scroll listener is
  ever added.

---

# UI/UX guidelines

Second source: [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) (MIT) — a
CSV database of ~98 UX guidelines across 10 priority categories, plus a Python search tool. Also
installed globally:

```bash
python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain ux
cat ~/.claude/skills/ui-ux-pro-max/references/quick-reference.md   # all 10 categories, scannable
```

**Do not run `--design-system` against this app.** That mode is for greenfield projects: asked about
this one it returned a *newsletter landing-page* pattern with a new palette and Righteous/Poppins
fonts. `styles/tokens.css` is the design system, and it's deliberate and documented. Use the
`--domain ux` / quick-reference **audit** path instead.

## Already satisfied — don't "fix" these

`tokens.css` + `base.css` cover a lot of the checklist already, and it's not obvious from a glance:
semantic color tokens (no raw hex in components), a 4px spacing scale, a type scale, `:focus-visible`
rings, a `prefers-reduced-motion` block, `font-variant-numeric: tabular-nums` on `.num`,
`cursor: pointer` + `opacity` on disabled, status encoded as **shape + text + color** (never colour
alone), viewport meta without zoom-disabling, real `<label for>` on every input, `autoComplete`
(`username` / `current-password` / `new-password`), and thought-through empty states. Single-theme
dark is a stated choice, not a missing light mode.

## Rules that apply on new UI

1. **Errors get `role="alert"`.** Every `.err` paragraph. A red string appearing on screen is
   invisible to a screen reader otherwise. Locked in by a test in `auth.test.tsx`.
2. **Icon-only controls need an accessible name**, with the glyph `aria-hidden`. The `↗` links in
   `SidePanels` announced as "↗" before. Buttons carrying visible text (`♥ like`, `⊘ block`) are
   already fine — don't add redundant labels there.
3. **Heading levels don't skip.** `.eyebrow` / `.card-title` carry the styling, so pick the tag by
   position in the document, not by how big you want the text. Feed page: h1 scan title → h2 card
   titles. Scans page: h1 "Your scans".
4. **Touch-target minimums go behind `@media (pointer: coarse)`.** See the block in `base.css` for
   why: this is a dense desktop tool, the ✕ controls are destructive, and they sit in flex rows where
   an expanded invisible hit area would steal a neighbour's taps.
5. **`inputMode` over `type="url"`** on URL fields — the mobile keyboard without native validation
   fighting the Enter-to-add handlers.
6. **Long lists**: the rule says virtualize at 50+ items. We use `content-visibility: auto` on
   `.card` instead — no dependency, and it composes with the memoization above. Revisit only if
   profiling says otherwise.
7. **Motion budget**: 150–300ms for micro-interactions, exit ~60–70% of enter, `transform`/`opacity`
   only. Existing transitions are 0.15–0.16s and the card exit is `CARD_EXIT_MS`. Anything new must
   also survive the reduced-motion block, which zeroes durations globally — never put required state
   changes *only* in an animation.

## Known conflicts and deferred items

- **`no-emoji-icons` vs. this app's identity — unresolved, deliberately.** The rule says use SVG
  icons (Heroicons/Lucide), never glyphs. The UI is built on typographic marks: `♥ ⊘ ◈ ★ ◎ ⌖ ◴ ⚠ ＋ ×
  ↗ ✓ ▾`. These aren't emoji (no colour font, they inherit `currentColor`), so the rule's specific
  failure mode — mismatched colour glyphs breaking a monochrome design — doesn't bite. They *do*
  render inconsistently across platforms, which is the real cost. Adopting an icon set means a new
  dependency (against the `bundle-` rules above), a visual pass over every component, and losing the
  terminal-ish character. **Left as-is; a design call, not a bug.**
- **`state-preservation` / `deep-linking` — resolved.** `useFeedFilters` (`features/feed/
  useFeedFilters.ts`) is built on `useSearchParams`, not `useState`: a filtered view is shareable/
  bookmarkable and browser-back restores it.
- **`progressive-loading` — resolved.** `FeedCard.tsx`/`ScanListPage.tsx` render `FeedCardSkeleton`/
  `ScanCardSkeleton` (shimmer via a shared `.sk` class in `base.css`) while the first page loads,
  instead of text `Loading…`.
- **`skip-links`, `focus-on-route-change` — resolved.** `App.tsx` has a `<a href="#main-content">
  Skip to content</a>` ahead of `AppHeader`, landing on `<main id="main-content">`. Both page
  headings (`ScanListPage`, `ScanFeedPage`) move focus to themselves on route change.
- **Contrast — measured, and the one failure fixed.** `--faint` on `--surface`/`--surface-2` was
  below the 4.5:1 AA minimum (3.56:1 / 3.23:1); retuned to `#7e889c` (4.97:1 / 4.51:1). See
  `lib/contrast.ts`/`lib/contrast.test.ts`, which reads `tokens.css` directly so a regression back
  below 4.5:1 fails the test rather than needing another manual measurement.

## Where the two skills overlap

`ui-ux-pro-max/data/react-performance.csv` (44 rows) re-encodes the same Vercel material as the
`react-best-practices` skill, in a lossier form — one CSV line per rule instead of a file with
worked examples. **For anything React-performance-shaped, use `react-best-practices`**; treat
`--domain react` as a search index at best. The two don't contradict each other, they just duplicate.
The one place they pull in opposite directions is icons: `no-emoji-icons` wants an icon library,
`bundle-barrel-imports` / `bundle-dynamic-imports` want fewer and smaller dependencies. If that ever
gets resolved in favour of SVGs, import each icon by direct path — never from a package barrel.

---

## Before pushing frontend changes

```bash
cd frontend && npm test && npx tsc -b && npm run lint && npm run build
```

`npm run build` also prints the chunk table — glance at it when you touch imports. A route chunk
collapsing back into `index-*.js` means a static import crept in and undid the split.
