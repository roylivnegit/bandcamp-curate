---
name: dark-factory
description: The process every code change in this repo goes through — green the gates, run up to 3 `qodo review --deep` rounds with a judge agent deciding fix/dismiss/defer each round, then open the PR. Use for any code change, from a one-line fix to a feature. Also use for "ship this", "run the factory", "take this to a PR".
---

# Dark factory

Named by Roy, 2026-10-06. A dark factory runs without the lights on. The end goal is building,
shipping and documenting a change with no hand-holding. It is not there yet, so the job for now is
to run the loop honestly and record where it falls short.

**Apply this to any code change.** Do not ask first.

---

## 1. Implement

Normal work. Nothing special.

## 2. Green every gate

Run all of these before any review round. A review on red gates burns a round.

Run from the repo root. Each line returns you there, so the whole block can be pasted at once —
the earlier version left the shell in `backend/` and the next `cd frontend` then failed, silently
skipping every frontend gate.

```bash
(cd backend && . .venv/bin/activate && ruff check . && pytest -q)
(cd frontend && npm test && npx tsc -b && npm run lint && npm run build)
```

`ruff` is easy to forget and CI will not forget it. CI (`.github/workflows/ci.yml`) runs `pytest` +
`ruff check` for the backend and `npm test` + `npm run lint` + `npx tsc -b` for the frontend. The
list above is a deliberate superset: it adds `npm run build`, which `frontend/CLAUDE.md` requires
before pushing and which catches a static import that undid a route's code split.

Then two checks the gates do not cover:

```bash
# Any file the diff treats as binary — a stray NUL byte makes review tools skip the
# file entirely and then report its contents as missing.
git diff origin/main...HEAD --numstat | awk '$1=="-" {print "BINARY: " $3}'
```

**And use the feature in the real app.** Start it, click it, read the strings. Tests do not catch a
search box that drops characters or a count line reading "1 item match". Both shipped past a full
green suite.

## 3. Review rounds — up to 3, `--deep` by default

Each round:

### a. Review

```bash
qodo review --base origin/main --deep --context-file - <<'EOF'
{
  "summary": "what changed and why, in two or three sentences",
  "decisions": [
    "every choice made on purpose that a reviewer would otherwise raise as a finding"
  ]
}
EOF
```

The `decisions` block is the highest-value part. Without it the reviewer re-litigates deliberate
trade-offs and the real findings get lost in the noise.

### b. Judge

Spawn a **separate agent** to rule on the findings. The author should not mark their own homework.
Give it the findings, the diff, and the decisions block, and require a verdict per finding:

- **fix** — correctness, security, data integrity, accessibility, or anything failing a gate.
- **dismiss** — only with evidence. Run the test, read the code, prove it. "Looks fine to me" is not
  a dismissal. Defensive code for a state that cannot occur is a fair dismissal.
- **defer** — real, but genuinely outside this change. It must land somewhere durable.

Each verdict needs a one-line reason that would survive being read back in a week.

> A reviewer can be confidently wrong. On the first run it twice claimed a test asserted the wrong
> count; the test passed both times. Acting on every finding breaks working code. Ignoring findings
> ships real bugs. The judge is the step that separates the two.

### c. Apply and re-green

Apply the fixes, re-run the gates, and keep the dismiss and defer reasons for the PR body.

### d. Stop early

If a round produces nothing worth fixing, stop. Three is a cap, not a target.

## 4. Open the PR

The body says what was fixed, what was dismissed and why, and what was deferred. Name anything the
process could not complete — a service outage, a blocked check — rather than quietly skipping it.

Pre-existing problems found along the way go in a "not in this change" section. Do not fold
unrelated fixes into the diff.

## 5. After the PR

Qodo reviews the pushed branch too, and finds different things from the local rounds. Read and
record those with the **`qodo-review-resolver`** skill, which talks to Qodo's own tools. Do not
scrape the PR comments with `gh` or `curl` — that is lossy and easy to read stale against head.

Check CI as well; the local gates and CI are not identical.

---

## Notes for improving this

Keep a short record of what each run cost and caught, so the process can be tuned rather than
guessed at. Worth tracking: how many rounds were actually needed, which findings the judge
dismissed and whether that held up, and what CI or the PR review caught that the local rounds
missed.

### Never write off a failure as "flaky" without diagnosing it

This cost a CI failure on the first run. Two tests in `feed.test.tsx` were failing before the
change, so a third failure got waved through under the same label — and that one was caused by the
change: a new command-palette action tipped a latent race, where the test read options
synchronously that only appear after a fetch.

"It also fails on main" means *this* failure is not yours. It does not mean the next one isn't. Get
the actual error text per failure and compare, rather than comparing counts.

Useful triage: a test that **passes in isolation but fails in a full run** is cross-test pollution,
not slowness. Confirm by raising the async budget — if it still fails at the higher limit, time was
never the problem.

### Revert a speculative fix that does not deliver

While chasing the above, two plausible shared-config fixes (a bigger async timeout, then restoring
real timers after every test) each failed to help. Both were reverted rather than left in. An
unproven change to shared test setup is worse than the bug it was aimed at, because the next person
reads it as load-bearing.

Known gaps today:
- The judge is a prompt, not a measured thing. No calibration on how often it is right. On the runs
  so far it has been worth it: it overruled the reviewer twice and overruled the author twice,
  including catching a regression the author had shipped the day before.
- **Qodo is a single point of failure.** It has been down for a whole round (`503 Auth upstream
  unreachable` on the review, the findings API and `whoami` alike), and flaky before that. An
  outage is a blocked step to report, never a reason to skip the gate. **Open question: should a
  round with no machine findings count toward the three?** Right now it does not, by default.
- The PR-side findings listing reports `status: open` even for findings that were dismissed or
  marked implemented, while the PR itself renders them correctly. Do not gate anything on that
  field.
- Browser verification can be blocked by the environment (Chrome showed an error page while `curl`
  got 200; the dev server was listening on IPv6-only `localhost`). Bind to `127.0.0.1` if that
  happens, and if it still fails, say the check did not run rather than implying it passed.
- `gh` reverts to the wrong account between pushes here, so each push needs `gh auth switch`. Worth
  fixing properly before any of this runs unattended.
- Nothing yet writes the run record automatically.
