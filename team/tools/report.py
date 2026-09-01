#!/usr/bin/env python3
"""team/tools/report.py — the cycle dashboard (E0-6).

One static HTML page built from what's already on disk: team/memory/metrics.md (one row per
cycle, written unconditionally now — see cycle.py's top-level `finally`), team/memory/decisions/
(an ADR per shipped design), and team/memory/state.json (the latest window/spend numbers).
Stdlib only — team/tools/ scripts run under bare system python3, and nothing in the backend's
declared dependencies provides templating (no jinja2/markdown/rich to lean on).

    python3 team/tools/report.py            # writes team/logs/dashboard.html
"""

from __future__ import annotations

import json
import re
import sys
from html import escape
from pathlib import Path

TEAM = Path(__file__).resolve().parent.parent
MEMORY = TEAM / "memory"
DECISIONS = MEMORY / "decisions"
LOGS = TEAM / "logs"

METRICS_ROW = re.compile(r"^\|(.+)\|\s*$")


def read_metrics() -> list[dict[str, str]]:
    """Parse metrics.md's table. Skips the header and the `|---|---|...` separator row."""
    path = MEMORY / "metrics.md"
    if not path.exists():
        return []
    columns = ["date", "cycle", "item", "reviewer/qa", "spend", "closer to goal?"]
    rows: list[dict[str, str]] = []
    for line in path.read_text().splitlines():
        m = METRICS_ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != len(columns) or cells[0] in ("date", "---"):
            continue
        rows.append(dict(zip(columns, cells)))
    return rows


def read_decisions() -> list[dict[str, str]]:
    """One entry per ADR: its number, title, and the cycle that wrote it (if the file says)."""
    if not DECISIONS.exists():
        return []
    adrs = []
    for path in sorted(DECISIONS.glob("ADR-*.md")):
        lines = path.read_text().splitlines()
        title = lines[0].lstrip("# ").strip() if lines else path.stem
        cycle_line = next((l for l in lines[1:4] if l.strip().startswith("_Cycle")), "")
        cycle = cycle_line.strip("_ ").removeprefix("Cycle ").rstrip(".")
        adrs.append({"file": path.name, "title": title, "cycle": cycle})
    return adrs


def read_state() -> dict:
    path = MEMORY / "state.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def render(metrics: list[dict[str, str]], decisions: list[dict[str, str]], state: dict) -> str:
    total_spend = 0.0
    for row in metrics:
        try:
            total_spend += float(row["spend"].lstrip("$"))
        except ValueError:
            pass

    metrics_rows = "\n".join(
        f"<tr><td>{escape(r['date'])}</td><td>{escape(r['cycle'])}</td>"
        f"<td>{escape(r['item'])}</td><td>{escape(r['reviewer/qa'])}</td>"
        f"<td>{escape(r['spend'])}</td><td>{escape(r['closer to goal?'])}</td></tr>"
        for r in reversed(metrics)
    ) or '<tr><td colspan="6"><em>No cycles recorded yet.</em></td></tr>'

    decisions_rows = "\n".join(
        f'<li><a href="../memory/decisions/{escape(d["file"])}">{escape(d["title"])}</a>'
        f' <span class="dim">{escape(d["cycle"])}</span></li>'
        for d in decisions
    ) or "<li><em>No decisions recorded yet.</em></li>"

    parked = state.get("parked")
    parked_html = (
        f'<span class="warn">parked: {escape(parked.get("title", ""))} '
        f'(<code>{escape(parked.get("branch", ""))}</code>)</span>'
        if parked else '<span class="ok">nothing parked</span>'
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>crate-digger team — dashboard</title>
<style>
  body {{ font: 15px/1.5 -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1, h2 {{ font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #ddd; }}
  th {{ background: #f5f5f5; }}
  .dim {{ color: #888; font-size: 0.9em; }}
  .warn {{ color: #a15c00; }}
  .ok {{ color: #1a7d3c; }}
  code {{ background: #f0f0f0; padding: 0.1em 0.3em; border-radius: 3px; }}
  .stat {{ display: inline-block; margin-right: 2rem; }}
  .stat b {{ font-size: 1.3em; display: block; }}
</style></head>
<body>
<h1>crate-digger team — dashboard</h1>

<div class="stat"><b>{len(metrics)}</b>cycles recorded</div>
<div class="stat"><b>${total_spend:.2f}</b>total notional spend</div>
<div class="stat"><b>{len(decisions)}</b>decisions (ADRs)</div>
<p>{parked_html}</p>

<h2>Cycles</h2>
<table>
<tr><th>date</th><th>cycle</th><th>item</th><th>reviewer/qa</th><th>spend</th><th>closer to goal?</th></tr>
{metrics_rows}
</table>

<h2>Decisions</h2>
<ul>
{decisions_rows}
</ul>

</body></html>
"""


def main() -> int:
    metrics = read_metrics()
    decisions = read_decisions()
    state = read_state()

    LOGS.mkdir(parents=True, exist_ok=True)
    out = LOGS / "dashboard.html"
    out.write_text(render(metrics, decisions, state))
    print(f"report: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
