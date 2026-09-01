# The cycle

One cycle = one wake-up = at most one shipped item. Seven phases, in order.

| # | Phase | Who speaks | Shape | Ends when |
|---|---|---|---|---|
| 1 | Standup | nobody (script) | — | the situation file is written |
| 2 | Grooming | product → architect → qa → researcher, adaptive rounds → lead | debate | the Lead names exactly one item |
| 3 | Design | architect → product → lead | write + challenge | the Lead approves the ADR |
| 4 | Build | backend and/or frontend dev | pipeline | tests pass locally and the work is committed |
| 5 | Review | 2 reviewers ‖ qa (parallel, different lenses) | adversarial | all verdicts `pass`, or 3 repair passes are spent |
| 6 | Ship | nobody (script) | — | the PR is open with auto-merge enabled |
| 7 | Retro | lead → product → qa | short debate | `memory/` is updated |

## 1. Standup

The script gathers, with no model involved:

- commits on `main` since the last cycle
- open PRs the team owns, and their CI state
- the last cycle's retro and any parked work
- `memory/backlog.md`, `memory/tried-and-failed.md`, `memory/metrics.md`
- budget remaining

If a parked item exists, it is the default choice for this cycle and grooming only has to
confirm it. Finishing beats starting.

## 2. Grooming — the debate

**Round 1.**
- **Product** proposes one to three candidates. Each names the user problem first, the
  solution second. Ideas from `memory/research/` and the backlog are fair game.
- **Architect** challenges feasibility and system integrity. Names the seam each idea lives
  behind and any invariant it threatens.
- **QA** says whether it can be tested and gated. "No fixture exists" is a real objection.
- **Researcher** supplies what is already known. If a question is open and needs a browser,
  it says so — it does not guess.

**The Lead orchestrates from here.** There is no fixed round count. After every round, the Lead
decides: another round, or rule now — and who from Architect/QA/Researcher is actually still
needed (drop anyone who already said they have nothing to add). The Lead also rewrites a running
digest after each round; that digest, not the raw back-and-forth, is what later turns read. A
speaker with nothing to add says so in one line and stops — an empty round does not have to be
filled. Runaway debates are capped by `TEAM_MAX_GROOMING_ROUNDS` (default 6) so one that never
converges still cannot eat the whole cycle.

**The Lead rules.** Picks exactly one item. States why, in one paragraph, naming the runner-up
and why it lost. Everything not picked goes back to `memory/backlog.md` with the reason. The
digest is also appended to `memory/digests.md`, so the reasoning survives even if the cycle
stops before the retro.

The Lead may also rule **"no build this cycle"** and spend it on research or a metrics review.
That is a legitimate outcome, not a failure.

## 3. Design

**Architect** writes an ADR into `memory/decisions/ADR-NNNN-<slug>.md`:

- the problem, in one paragraph
- the chosen approach and the seam it lives behind
- **invariants it must not break** — this is the part reviewers check against
- what changes: files, tables, endpoints
- how to roll it back
- what was rejected and why

**Product** confirms the design still solves the user problem. If the design has drifted into
something easier but less useful, it says so now, not after the build.

**Lead** approves, or sends it back once. Two rounds maximum, then the Lead decides.

## 4. Build

The dev works in a git worktree on branch `team/<cycle-id>-<slug>`, never in Roy's working
tree. It implements the ADR — not more, not less. Scope creep found mid-build goes to the
backlog, not into the diff.

Tests ship in the same commit. Backend follows `CLAUDE.md`; frontend follows
`frontend/CLAUDE.md`, which is binding.

## 5. Review

**Two reviewers** and **QA** run at the same time and none of them reads the others' output.
The reviewers get the same diff through **different lenses**, because redundancy finds the
same things twice while different lenses find different things:

- **correctness** — code that produces a wrong result. Each finding names the input, the
  state, and the wrong output. Ignores style and scope.
- **integrity** — the ADR's invariants one by one, then work the ADR did not ask for, silent
  failure modes, and anything that could not be undone with a single `git revert`.

Each returns `pass` or `block`, with evidence per finding. Any block blocks.
- **QA** runs the real gates: `pytest -q`, `npm test`, `ruff check`, `npx oxlint`, `tsc -b`,
  and the Playwright E2E against the sandbox. Verdict: `pass` or `block`, with the actual
  output.

If any of them blocks, the dev gets a repair pass and everyone re-checks — up to **three**
times. After that the item is parked with the branch intact and the reason written to the
backlog. We do not loop forever.

## 6. Ship

Push the branch. Open a PR whose body carries:

- the decision and why (from phase 2)
- a link to the ADR
- a link to the transcript
- both verdicts, verbatim
- a handoff note if the item is parked or partial

Enable auto-merge. CI decides. A red PR is left open — the next standup will see it.

## 7. Retro

Short, three speakers.

- **Lead**: what moved, what it cost, what to do next cycle.
- **Product**: did this get us closer to better music faster? Honestly.
- **QA**: what nearly slipped through, and what gate would have caught it.

The orchestrator then updates `memory/metrics.md`, `memory/backlog.md`,
`memory/tried-and-failed.md` and `memory/state.json`, and writes the transcript.
