# The crate-digger team

A small engineering team that wakes every five hours, argues about what would make
crate-digger better at finding music, builds one thing, gates it, and opens a PR.

Eight roles, each a separate `claude -p` process with its own system prompt. They read the
same charter, share one transcript, and have real decision rights — the Architect can veto a
design, QA and the Reviewer can block a merge, and the Tech Lead settles everything else.

## Running it

```bash
team/tools/run-cycle.sh                        # start a cycle only if the window has reset
team/tools/run-cycle.sh --now                  # start one right now regardless
team/tools/run-cycle.sh --now --dry-run        # ... and never push or open a PR
team/tools/run-cycle.sh --now --phases 1-3     # just the meeting: standup, debate, design
```

Without `--now` it almost always exits immediately and costs nothing. That is the normal
case: launchd calls it every 20 minutes and it only starts work when the five-hour usage
window has actually turned over.

Every cycle leaves three things behind:

| where | what |
|---|---|
| an email to you | a short summary: what was decided, what shipped, what blocked, what it cost |
| `transcripts/<cycle>.md` | the meeting, readable top to bottom |
| `memory/decisions/ADR-NNNN-*.md` | why the design is what it is |
| a PR on GitHub | the diff, with the decision and every verdict in the body |

Install the heartbeat with `tools/ai.crate-digger.team.plist` — see **Where this stands**.

## How a cycle goes

Seven phases, in `protocol/ceremony.md`. In short: the script gathers the situation with no
model involved, then Product proposes one to three items and the Architect, QA and Researcher
challenge them. The Lead orchestrates — deciding after every round whether to continue and who's
still needed, no fixed round count — then picks **exactly one**, names the runner-up and sets a
scope limit. The Architect writes an ADR. A dev implements it in a git
worktree — never in your working tree. Two reviewers and QA then run in parallel and none of
them sees the others' output: one reads the diff for wrong results, one checks it against the
ADR's invariants and scope, and QA actually runs the gates. Up to three repair passes if any
of them blocks, then the item ships or gets parked. The retro writes down what survives.

## What they can and cannot do

The rules are in `charter.md`; these are the ones that matter most.

**Never touches production.** The runner scrubs the inherited environment and loads
`.env.team` instead, so the repo's real `.env` — with the live Nimble key and the Neon
connection string — is never in scope. It refuses to start if `DATABASE_URL` points at a
hosted database or if `NIMBLE_API_KEY` is set. `.claude/settings.json` denies reading `.env`
outright, and that holds even for a turn running unattended.

**Never spends Nimble credits.** No `/extract`, no crawl, no scan. "Can we scrape this?" is
answered by opening the real page in a browser and saving the HTML as a fixture. The crawler
stays yours to run.

**Always stops for you** on anything irreversible — altering existing data, touching a key,
force-pushing, spending money, or a change that is not one `git revert` away. It writes
`memory/needs-roy.md` and exits. That file blocks the next cycle from building until you
answer it. Research and grooming still run.

**Spends the usage window, not money.** What is scarce on a subscription is the rolling
five-hour window, not dollars. Every `claude -p` run reports on it through a
`rate_limit_event`, so the cycle knows how much is left and works until roughly 85% of it is
gone (`TEAM_WINDOW_CEILING`). That budget buys **depth on one item**: as many grooming rounds
as the debate needs (capped by `TEAM_MAX_GROOMING_ROUNDS`), two reviewers on different lenses,
up to three repair passes. When it runs out mid-build the
work is committed to its branch with a handoff note and picked up at the next standup.

Paid overage is refused outright — the charter forbids spending real money, and the cycle
stops the moment `isUsingOverage` turns true.

## Which account it spends

Roy switches between a personal Pro plan and Qodo's team plan during the day, and `claude`
bills whichever one is signed in. `claude auth` has no `switch`, but **`CLAUDE_CONFIG_DIR`
gives a config directory its own independent auth state** — so the team keeps its own login
and the two coexist without either disturbing the other.

Set it up once, in a terminal (it opens a browser):

```bash
CLAUDE_CONFIG_DIR=~/.claude-team claude auth login
```

Sign in as **royee.livne6@gmail.com**. From then on `run-cycle.sh` uses that login no matter
what your interactive session is switched to, and there is nothing to remember or switch back.

If that directory has no login yet, the runner falls back to the default config — and refuses
to start unless it is signed in as the team's account, so a cycle can never quietly bill the
wrong plan. Both the account and the directory are overridable: `TEAM_CLAUDE_ACCOUNT`,
`TEAM_CLAUDE_CONFIG_DIR`.

## Reports

After every session `run-cycle.sh` emails a short summary to **royee.livne6@gmail.com** —
what the team decided and why, the verdicts, any blocking findings, the PR link, and what the
window cost. It is written to `logs/<cycle>-summary.md` first, inside a `finally`, so a cycle
that crashed or ran out of window still reports.

Mail goes out over Gmail SMTP with an **app password held in the macOS Keychain** — never in
this repo. Store it once:

```bash
security add-generic-password -a royee.livne6@gmail.com -s crate-digger-team-smtp -w
```

Use an app password from https://myaccount.google.com/apppasswords (needs 2-step
verification). Without that entry the cycle still runs and still writes the summary; it just
prints where to find it instead of sending. `notify.py` runs from the shell rather than
inside an agent turn, and `security` is on the agents' deny list, so no agent can reach the
credential.

## Files

| | |
|---|---|
| `charter.md` | the north star and the hard rules. Read by every agent, every turn |
| `roster/*.md` | the eight roles — who they are, what they own, how they argue |
| `protocol/` | the ceremony and the rules for vetoes, deadlock and stopping |
| `schema/*.toml` | output contracts; `tools/toml2schema.py` turns them into JSON Schema |
| `memory/` | backlog, ADRs, research notes, what failed, metrics, cycle state |
| `tools/cycle.py` | the orchestrator |
| `tools/run-cycle.sh` | the entry point: window check, lock, sandbox env, teardown, logs |
| `tools/notify.py` | emails the summary; reads SMTP credentials from the Keychain |

`memory/` is the only thing that survives a cycle. An agent three days from now has no
recollection of any of this except those files, which is why the retro spends real effort on
them.

## Changing the rules

The charter, roster, protocol and schemas are just files in the repo, and the team is allowed
to change them — through the normal ceremony, with an ADR, in a PR. Two exceptions: a change
to the charter's **Hard rules** always needs you, and a gate can never be weakened in the same
PR as the change that gate is failing.

## Where this stands

The bootstrap is done: the team can hold a meeting, write an ADR, build in a worktree, gate
itself and open a PR. What it does not have yet is an environment to work in — no sandbox
database, no CI, no browser test harness. So QA will honestly mark most gates `skipped` and
say why.

That is deliberate. **Sprint 0 is the team building its own environment** (`memory/backlog.md`,
items E0-1 to E0-7), through the same ceremony and the same review it will use forever.
Autonomous building stays off until E0-7 — a full dry-run cycle end to end — passes.

Two items are blocked on you and cannot be automated:

- **E0-3 (CI)** needs the `workflow` scope. `roylivnegit` is the active account now and can
  see the repo, but its token still lacks that scope, so it cannot push a file under
  `.github/workflows/`. Fix with `gh auth refresh -h github.com -s workflow`.
- **E0-5 (branch protection)** needs admin on the repo.
- **Email** needs the Keychain entry above, or summaries are written to disk but not sent.
