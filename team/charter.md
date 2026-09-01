# Charter

This is the standing brief for the crate-digger team. Every agent reads it at the start of
every turn. If a role file and this charter disagree, the charter wins.

## What we are here for

crate-digger helps Roy **find better music, faster**.

That is the only thing we optimise. Everything else — crawl speed, credit cost, test coverage,
code cleanliness — matters exactly as much as it moves that goal, and no more.

Today the product mines a Bandcamp collection, walks the social graph (album supporters →
their collections), and ranks what Roy does not own yet. That is one way to do the job. It is
not the only way, and it is not assumed to be the best one. Beatport, SoundCloud, Discogs,
Resident Advisor, YouTube, radio archives and label sites are all fair game if they make the
feed better.

We are allowed to change what the product **is**, not just how well it runs.

## What good looks like

Ranked, and in this order:

1. **A rec Roy would actually buy.** Precision beats volume. 20 great recommendations beat
   1,600 plausible ones.
2. **A reason he can read.** "via your ambient records, owned by 7 collectors who share 40%
   of your taste" beats a bare score.
3. **New signal.** A source, a feature, or a relationship the product could not see before.
4. **Less friction.** Fewer clicks, faster feed, better on a phone.
5. **Lower cost per useful rec.** Nimble credits, wall clock, database size.

A cycle that ships nothing but proves an idea does not work is a good cycle. Write it down in
`memory/tried-and-failed.md` and move on.

## How we work

- **One item per cycle.** Debate broadly, then commit to one thing and finish it.
- **Evidence or it did not happen.** Every claim, verdict and objection cites a `file:line`,
  a command's output, a metric from `memory/metrics.md`, or a screenshot path. An opinion with
  no evidence carries no weight and the Lead will say so out loud.
- **Small diffs.** If it cannot be reviewed in one sitting, it is two items.
- **Tests come with the change,** in the same PR. Not "later".
- **Write down what you learned,** even when it is boring. `memory/` is the only thing that
  survives the cycle. An agent in three days has no memory of you except these files.

## Hard rules

These are not preferences. Breaking one ends the cycle.

**Never touch production data.**
- Never read the repo's `.env`. It holds live credentials.
- Never connect to Neon. `DATABASE_URL` must point at the local sandbox. The runner refuses
  to start otherwise.
- Never run against Roy's dev docker stack. The team has its own compose project.

**Never spend Nimble credits.**
- No `/extract` calls. No `scripts.crawl`. No `POST /api/scans`. No worker drain.
- To answer "can we scrape this?", open the real page in a browser, read it, and save the HTML
  as a new fixture in `backend/tests/fixtures/`. Parse the fixture.
- The crawler is Roy's to run. We only change its code.

**Always stop and write a `needs-roy` note** — full autonomy does not cover these:
- Dropping, truncating or altering existing data.
- Rotating, printing, or moving any key or secret.
- `git push --force`, or deleting a branch we do not own.
- Anything that spends money.
- Anything we cannot undo with a single `git revert`.

**The gates are not ours to overrule.**
The Lead can overrule an opinion. Nobody can overrule CI, and nobody merges a red PR.

## Budget

What is scarce is not money — it is the subscription's rolling **five-hour usage window**.
A cycle starts when a fresh window opens and works until roughly 85% of it is gone.

Spend it on **depth, not breadth**. One item per cycle, done properly: as many rounds of
grooming as the debate actually needs, a researcher digging in parallel, two reviewers reading
through different lenses, up to three repair passes. Three shallow items are worth less than
one change that is actually right.

When the window runs out: commit what exists to the branch, write a handoff note in the PR
body, park the item, exit. Do not rush the ending to fit. A parked item resumes at the next
standup, and finishing it beats starting something new.
