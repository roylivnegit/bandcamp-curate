# Disagreement, vetoes and stopping

## Who can block what

| Role | Can block | On what grounds |
|---|---|---|
| Architect | a design, in phase 3 | it breaks a documented invariant or seam |
| Reviewer | a merge, in phase 5 | the diff is wrong, unsafe, or not what the ADR asked for |
| QA | a merge, in phase 5 | a gate failed, or the change cannot be tested |
| Tech Lead | nothing — the Lead decides instead | — |
| Product, Researcher, Devs | nothing. They argue; they do not block | — |

## The evidence rule

**A block must cite evidence.** One of:

- a `file:line` in this repo
- the output of a command that was actually run
- a written invariant from `CLAUDE.md`, `frontend/CLAUDE.md`, or an ADR
- a screenshot or trace path from the E2E run
- a number in `memory/metrics.md`

A block with no evidence is not a block. The Lead overrules it, in one sentence, in the
transcript. This is on purpose: it keeps the team from stalling on taste.

Taste is still allowed — say "I do not like this and here is why" as an **argument**. Just do
not dress it up as a veto.

## Deadlock

1. The blocker states the objection with evidence.
2. The author responds once: fix it, or explain why it is not a problem.
3. The blocker either lifts the block or restates it.
4. **The Lead rules.** That is the end of it inside this cycle.

If the Lead's ruling turns out to be wrong, it gets written into
`memory/tried-and-failed.md` and the team is smarter next time. We do not relitigate a closed
ruling in a later cycle unless new evidence appears.

## When we stop and ask Roy

Autonomy is real: a new data source can ship without Roy seeing it first. These are the
exceptions. On any of them, **halt the cycle**, write `team/memory/needs-roy.md` with the
question and what is blocked, and exit cleanly.

- Dropping, truncating or altering existing data in any database.
- Anything involving a key, a token or a secret — reading, printing, rotating, moving.
- `git push --force`. Deleting a branch the team does not own. Rewriting published history.
- Spending money: a paid API, a new subscription, Nimble credits, hosting.
- A change that cannot be undone with a single `git revert`.
- The team disagrees about the **charter itself** — what the product should be. That is Roy's
  call, not the Lead's.

A `needs-roy.md` file blocks the next cycle from building until it is deleted or answered.
Research and grooming still run. This is deliberate: an unanswered question should slow us
down, not be quietly forgotten.

## Changing our own rules

The charter, roster, protocol and schemas are files in the repo. The team may change them —
through the normal ceremony, with an ADR, in a PR, like any other change. Two extra rules:

- A change to `charter.md` **Hard rules** section always needs Roy. See above.
- Never weaken a gate in the same PR as the change that gate is failing.
