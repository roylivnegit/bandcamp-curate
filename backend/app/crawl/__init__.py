"""Crawl layer (M3): a resumable frontier over Bandcamp's supporter→collection graph.

`frontier`  — enqueue/claim/complete rows in `crawl_frontier` (idempotent, resumable).
`service`   — the crawl operations (fetch → parse → map → enqueue follow-ups).
`runner`    — drive the frontier to completion (used by the CLI and the ARQ worker).
`seed`      — enqueue the initial fan-collection crawl from BANDCAMP_FAN_URL.
"""
