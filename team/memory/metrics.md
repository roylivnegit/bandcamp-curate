# Metrics

One row per cycle, appended by the retro. This is the only place the team can see whether it
is getting anywhere over weeks rather than hours.

| date | cycle | item | reviewer/qa | spend | closer to goal? |
|---|---|---|---|---|---|

## Product numbers worth tracking

Not collected automatically yet — item **E0-6** builds the tool that does it. Until then,
treat any claim about these as a guess and label it as one.

- **recommendations in the feed** — around 1,600 at bootstrap. High is not good; precision is.
- **tag coverage** — share of recommended albums carrying any tag. Tags live on album pages,
  which the crawl mostly does not fetch, so this is low and it caps tag-affinity.
- **Nimble credits per new recommendation** — the real cost number.
- **exclusion correctness** — recommended items Roy already owns, has wishlisted, or whose
  artist he follows. This should be zero. Anything above zero is the worst bug this product
  can have.
- **tests** — 142 backend, 17 frontend at bootstrap.
