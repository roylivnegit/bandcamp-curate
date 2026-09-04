#!/usr/bin/env python3
"""The crate-digger agent team orchestrator.

One invocation = one cycle = at most one shipped item. Seven phases, in order; see
team/protocol/ceremony.md. Each agent turn is its own `claude -p` process carrying that
role's system prompt and the transcript so far, and returning structured output validated
against a TOML contract in team/schema/.

    python3 team/tools/cycle.py --dry-run          # everything except push and PR
    python3 team/tools/cycle.py --phases 1-3       # just the meeting, no code
    python3 team/tools/cycle.py                    # a real cycle

Normally launched by team/tools/run-cycle.sh, which sets up the sandbox environment first.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toml2schema

ROOT = Path(__file__).resolve().parents[2]
TEAM = ROOT / "team"
ROSTER = TEAM / "roster"
MEMORY = TEAM / "memory"
TRANSCRIPTS = TEAM / "transcripts"
DECISIONS = MEMORY / "decisions"
WORKTREES = Path(os.environ.get("TEAM_WORKTREE_ROOT", "/tmp/crate-team-worktrees"))

# The only account the team is allowed to spend. Roy switches between a personal Pro plan
# and Qodo's team plan during the day, and a cycle that fires while he is switched to work
# would quietly bill the team's quota for a side project. Checked before anything is spent.
TEAM_ACCOUNT = os.environ.get("TEAM_CLAUDE_ACCOUNT", "royee.livne6@gmail.com")

# How much of the subscription's five-hour window the team may take. Full send: the cycle is
# meant to run until the window is nearly gone, not until some dollar figure.
WINDOW_CEILING = float(os.environ.get("TEAM_WINDOW_CEILING", "0.85"))

# Not a budget — a runaway guard, so one wedged turn cannot eat the whole window on its own.
PER_TURN_CAP_USD = float(os.environ.get("TEAM_TURN_CAP_USD", "3.00"))

# A turn can fail for reasons that have nothing to do with the work — the machine sleeping
# mid-response, a dropped connection. Retrying one turn is far cheaper than losing a cycle.
TURN_ATTEMPTS = int(os.environ.get("TEAM_TURN_ATTEMPTS", "3"))
RETRY_BACKOFF_SECONDS = 5

# Grooming has no fixed round count — the Lead ends it once the debate is settled. This is a
# runaway guard, not a target: a pathological debate that never converges still cannot eat the
# whole window on its own.
MAX_GROOMING_ROUNDS = int(os.environ.get("TEAM_MAX_GROOMING_ROUNDS", "6"))
MAX_REPAIR_PASSES = int(os.environ.get("TEAM_REPAIR_PASSES", "3"))

# Two reviewers read the same diff through different lenses. Redundancy finds the same things
# twice; different lenses find different things.
REVIEW_LENSES = {
    "correctness": (
        "Hunt for code that produces a wrong result. For each finding, name the input, the "
        "state, and the wrong output. Ignore style and scope — another reviewer has those."
    ),
    "integrity": (
        "Check the diff against the ADR's invariants one by one, then look for work the ADR "
        "did not ask for, anything that can fail silently with no error or log or counter, "
        "and anything that could not be undone with a single `git revert`."
    ),
}

# Which model each role runs on. Judgement roles get the strong model; the rest do not need it.
MODELS = {
    "product": "opus",
    "architect": "opus",
    "lead": "opus",
    "reviewer": "opus",
    "backend-dev": "sonnet",
    "frontend-dev": "sonnet",
    "qa": "sonnet",
    "researcher": "sonnet",
}

ROLE_FILES = {
    "product": "00-head-of-product.md",
    "architect": "01-architect.md",
    "lead": "02-tech-lead.md",
    "backend-dev": "03-backend-dev.md",
    "frontend-dev": "04-frontend-dev.md",
    "qa": "05-qa.md",
    "reviewer": "06-reviewer.md",
    "researcher": "07-researcher.md",
}

# `dontAsk` runs unattended without prompting, and unlike a blanket bypass it still refuses
# anything the deny list in team/.claude/settings.json names. Verified: a turn in this mode
# runs ordinary git and test commands and can edit files, but cannot read the repo's .env.
PERMISSION_MODE = os.environ.get("TEAM_PERMISSION_MODE", "dontAsk")

# Read-only roles never need to write. Giving them Edit anyway is how a "reviewer" quietly
# fixes the thing it was supposed to report.
READ_TOOLS = "Read Grep Glob Bash WebFetch"
WRITE_TOOLS = "Read Grep Glob Bash Edit Write NotebookEdit WebFetch"

DENY_TOOLS = [
    "Bash(git push --force*)",
    "Bash(git push -f*)",
    "Bash(rm -rf /*)",
    "Bash(*scripts.crawl*)",
    "Bash(*scripts/crawl*)",
    "Bash(*dump_extract*)",
    "Bash(*verify_nimble*)",
    "Read(./.env)",
    "Read(../.env)",
    "Read(//Users/roylivne/crate-digger/.env)",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")


def run(cmd: list[str] | str, cwd: Path | None = None, check: bool = False) -> str:
    """Run a shell command and return its combined output, trimmed."""
    proc = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        shell=isinstance(cmd, str),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {proc.stderr[-2000:]}")
    return (proc.stdout + proc.stderr).strip()


def _branch_exists(name: str) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).returncode == 0


def _find_worktree_for_branch(branch: str) -> Path | None:
    """Path of an existing worktree already checked out on `branch`, if any. A parked cycle's
    worktree is deliberately left on disk (see the `finally` block at the bottom of this file)
    so a later cycle can resume it instead of redoing the work in a fresh one."""
    path = None
    for line in run(["git", "worktree", "list", "--porcelain"]).splitlines():
        if line.startswith("worktree "):
            path = line.removeprefix("worktree ")
        elif line == f"branch refs/heads/{branch}" and path:
            return Path(path)
    return None


class BudgetExhausted(RuntimeError):
    pass


@dataclass
class Window:
    """What is actually scarce: the subscription's rolling five-hour usage window.

    Dollars are not the constraint on a subscription — `total_cost_usd` is a notional
    API-equivalent price, not money anyone pays. The binding limit is the window, and every
    `claude -p` run reports on it through a `rate_limit_event`:

        {"status": "allowed", "resetsAt": 1787353800, "rateLimitType": "five_hour",
         "overageStatus": "rejected", "isUsingOverage": false}

    `utilization` only appears once usage passes a threshold — a fresh window omits it
    entirely — so absence means "plenty left", not "zero used".
    """

    ceiling: float = WINDOW_CEILING
    utilization: float = 0.0
    status: str = "allowed"
    resets_at: int | None = None
    spend_usd: float = 0.0  # notional; recorded in metrics.md, not a limit

    #: Statuses that mean the window is gone, whatever `utilization` says.
    BLOCKED = frozenset({"rejected", "blocked", "exceeded", "rate_limited"})

    def observe(self, info: dict) -> None:
        self.status = info.get("status") or self.status
        if (util := info.get("utilization")) is not None:
            self.utilization = float(util)
        if (resets := info.get("resetsAt")) is not None:
            self.resets_at = int(resets)
        # Overage is real money. The charter forbids spending it without asking, and on this
        # account it is unavailable anyway ("overageStatus": "rejected").
        if info.get("isUsingOverage"):
            raise BudgetExhausted("the account has moved into paid overage — stopping")

    def check(self) -> None:
        if self.status in self.BLOCKED:
            raise BudgetExhausted(f"the usage window is exhausted (status {self.status!r})")
        if self.utilization >= self.ceiling:
            raise BudgetExhausted(
                f"usage window at {self.utilization:.0%}, ceiling is {self.ceiling:.0%}"
            )

    def headroom(self) -> str:
        # `utilization` is only reported once usage crosses a threshold, so an unset value
        # means "still below it", not "nothing used". Do not dress that up as 0%.
        if not self.utilization:
            return "window usage below the reporting threshold"
        left = max(0.0, self.ceiling - self.utilization)
        return f"{self.utilization:.0%} used, {left:.0%} of this window still available"

    def charge(self, amount: float) -> None:
        self.spend_usd += amount


@dataclass
class Transcript:
    path: Path
    lines: list[str] = field(default_factory=list)

    def write(self, text: str = "") -> None:
        self.lines.append(text)
        self.path.write_text("\n".join(self.lines) + "\n")

    def heading(self, text: str) -> None:
        self.write(f"\n## {text}\n")

    def note(self, text: str) -> None:
        self.write(f"_{text}_\n")

    def turn(self, speaker: str, data: dict) -> None:
        """Render one debate turn so the file reads like a meeting."""
        stance = data.get("stance", "")
        header = f"**[{speaker}]**" + (f" — _{stance}_" if stance else "")
        self.write(header)
        self.write()
        self.write(textwrap.fill(data.get("argument", "").strip(), 92))
        for label, key in (("Evidence", "evidence"), ("Asks", "asks")):
            items = data.get(key) or []
            if items:
                self.write(f"\n{label}:")
                for item in items:
                    self.write(f"- {item}")
        self.write()

    def block(self, title: str, data: dict) -> None:
        """Render a structured artifact (ruling, ADR, verdict) as readable markdown."""
        self.write(f"**{title}**\n")
        for key, value in data.items():
            label = key.replace("_", " ")
            if isinstance(value, list):
                if not value:
                    continue
                self.write(f"- _{label}_:")
                for item in value:
                    if isinstance(item, dict):
                        inner = "; ".join(f"{k}={v}" for k, v in item.items() if v)
                        self.write(f"    - {textwrap.shorten(inner, 400)}")
                    else:
                        self.write(f"    - {item}")
            elif value not in (None, ""):
                self.write(f"- _{label}_: {value}")
        self.write()


@dataclass
class Cycle:
    cycle_id: str
    number: int
    window: Window
    transcript: Transcript
    dry_run: bool
    state: dict
    worktree: Path | None = None
    branch: str | None = None
    #: Commit the branch was cut from. Everything the team wrote is `base_sha..HEAD` —
    #: HEAD~1 would only show the last repair commit once a repair pass lands on top.
    base_sha: str | None = None
    pr_url: str | None = None
    #: The running, Lead-curated essence of grooming so far. Empty until the first round
    #: closes. Once set, later grooming turns read this instead of the raw transcript.
    digest: str = ""

    def log(self, message: str) -> None:
        print(f"[{self.cycle_id}] {message}", flush=True)


# --------------------------------------------------------------------------------------
# the agent call
# --------------------------------------------------------------------------------------


def ask(
    cycle: Cycle,
    role: str,
    prompt: str,
    contract: str | None = None,
    tools: str = READ_TOOLS,
    cwd: Path | None = None,
    role_file_override: Path | None = None,
) -> dict | str:
    """Run one agent turn as its own `claude -p` process. Returns validated structured output.

    Runs in `stream-json` because that is the only output format that emits
    `rate_limit_event`, which is how the cycle knows how much of the usage window is left.
    The final `result` event carries the same fields the plain `json` format would.
    """
    cycle.window.check()
    role_file = role_file_override or (ROSTER / ROLE_FILES[role])

    argv = [
        "claude",
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--model", MODELS[role],
        "--max-budget-usd", f"{PER_TURN_CAP_USD:.2f}",
        "--append-system-prompt-file", str(role_file),
        "--settings", str(TEAM / ".claude" / "settings.json"),
        "--permission-mode", PERMISSION_MODE,
        "--disable-slash-commands",
        "--allowedTools", *tools.split(),
        "--disallowedTools", *DENY_TOOLS,
        "--add-dir", str(TEAM),
    ]
    if contract:
        argv += ["--json-schema", json.dumps(toml2schema.build(contract))]

    last_error = ""
    for attempt in range(1, TURN_ATTEMPTS + 1):
        suffix = "" if attempt == 1 else f"  retry {attempt - 1}/{TURN_ATTEMPTS - 1}"
        cycle.log(f"  {role} ({MODELS[role]}) …{suffix}")
        proc = subprocess.run(
            argv, cwd=cwd or ROOT, input=prompt, capture_output=True, text=True, check=False
        )

        payload: dict = {}
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "rate_limit_event":
                cycle.window.observe(event.get("rate_limit_info") or {})
            elif event.get("type") == "result":
                payload = event

        if payload:
            cost = float(payload.get("total_cost_usd") or 0.0)
            cycle.window.charge(cost)
            reason = payload.get("terminal_reason")
            cycle.log(f"    ${cost:.3f} ({reason}) — {cycle.window.headroom()}")

            if denials := payload.get("permission_denials"):
                cycle.log(f"    permission denials: {json.dumps(denials)[:400]}")
            if reason == "budget_exhausted":
                cycle.transcript.note(f"{role} hit its per-turn cap and was cut short.")

            if not contract:
                return payload.get("result") or ""
            if isinstance(out := payload.get("structured_output"), dict):
                return out
            last_error = (
                f"expected structured output for contract {contract!r}, got "
                f"{payload.get('subtype')}: {str(payload.get('result'))[:400]}"
            )
        else:
            last_error = f"no result event.\n{proc.stdout[-800:]}\n{proc.stderr[-600:]}"

        # The window is the thing worth protecting: one bad response should not throw away a
        # cycle's worth of turns. The first dry run died exactly here — the Mac slept
        # mid-response and eleven completed turns went in the bin.
        if attempt < TURN_ATTEMPTS:
            cycle.window.check()
            cycle.log(f"    transient failure ({last_error[:120]}); retrying")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise RuntimeError(f"{role}: failed after {TURN_ATTEMPTS} attempts — {last_error}")


# Roles that reason about the code itself are told to consult CLAUDE.md; the rest are not,
# because it is long and re-reading it on every turn is most of what a cheap turn costs.
CODE_FACING = {"architect", "backend-dev", "frontend-dev", "reviewer", "qa"}


def brief(cycle: Cycle, role: str, task: str, meeting_override: str | None = None) -> str:
    """The shared preamble every turn receives.

    The charter and the escalation rules are inlined rather than linked. They are short, every
    role needs all of them, and a `Read` round-trip per turn is both slower and less reliable
    than just putting the text in front of the model.

    `meeting_override`, when given, replaces a full re-read of the transcript file with this
    text instead — grooming uses it to hand later turns the Lead's curated digest rather than
    the raw, ever-growing back-and-forth. Left `None`, every other phase is unaffected.
    """
    charter = (TEAM / "charter.md").read_text()
    rules = (TEAM / "protocol" / "escalation.md").read_text()
    if meeting_override is not None:
        transcript_so_far = meeting_override
    else:
        transcript_so_far = cycle.transcript.path.read_text() if cycle.transcript.path.exists() else ""

    code_note = (
        f"\n{ROOT / 'CLAUDE.md'} is the project's real engineering record — every trap this\n"
        "codebase already fell into is written down there. Read the parts relevant to your\n"
        "task before you answer.\n"
        if role.lower().replace(" ", "-") in CODE_FACING or role in CODE_FACING
        else ""
    )

    return textwrap.dedent(f"""
        You are the **{role}** on the crate-digger team. Cycle {cycle.cycle_id}.
        The repository is at {ROOT}.
        {code_note}
        ## Charter (binding)

        {charter}

        ## Disagreement and stopping (binding)

        {rules}

        ## The meeting so far

        {transcript_so_far if transcript_so_far.strip() else "(nothing yet — you are opening it)"}

        ---

        Respond to what was actually said above. Do not restate it, and do not repeat a point
        someone has already made. Usage window: {cycle.window.headroom()}.
        Be brief and spend your tool calls on evidence, not on re-reading these instructions.

        ## Your task now

        {task}
        """).strip()


# --------------------------------------------------------------------------------------
# phases
# --------------------------------------------------------------------------------------


def phase1_standup(cycle: Cycle) -> str:
    """Gather the situation. No model involved — this is just facts."""
    cycle.log("phase 1 — standup")
    last_sha = cycle.state.get("last_main_sha", "")
    since = f"{last_sha}..HEAD" if last_sha else "-15"

    parts = {
        "commits on main since last cycle": run(["git", "log", "--oneline", since]) or "(none)",
        "open team PRs": run(
            "gh pr list --author @me --limit 10 "
            "--json number,title,headRefName,statusCheckRollup 2>&1"
        ) or "(none)",
        "parked work": json.dumps(cycle.state.get("parked") or {}, indent=2),
        "backlog": (MEMORY / "backlog.md").read_text()[:6000],
        "tried and failed": (MEMORY / "tried-and-failed.md").read_text()[:4000],
        "metrics": (MEMORY / "metrics.md").read_text()[:3000],
        # Tail, not head — this file is append-only and grows, so the recent entries are the
        # ones worth reading. A head-slice would eventually only ever show the oldest debates.
        "past debates, distilled": (
            (MEMORY / "digests.md").read_text()[-6000:]
            if (MEMORY / "digests.md").exists() else "(none yet)"
        ),
        "research notes on file": "\n".join(
            p.name for p in sorted(MEMORY.glob("research/*.md"))
        ) or "(none)",
    }
    situation = "\n\n".join(f"### {k}\n\n{v}" for k, v in parts.items())

    cycle.transcript.heading("1 · Standup")
    cycle.transcript.write("```")
    cycle.transcript.write(parts["commits on main since last cycle"])
    cycle.transcript.write("```")
    if parked := cycle.state.get("parked"):
        cycle.transcript.note(
            f"Parked from a previous cycle: {parked.get('title')} — finishing beats starting."
        )
    return situation


def phase2_grooming(cycle: Cycle, situation: str) -> dict:
    """The debate. Product proposes, roles challenge, the Lead orchestrates.

    There is no fixed round count. After every round the Lead decides: another round (and who's
    actually still needed), or rule now. Rounds 2+ hand challengers the Lead's curated digest
    instead of the raw, ever-growing transcript — that digest is what makes later rounds cheap
    regardless of how many already happened.
    """
    cycle.log("phase 2 — grooming")
    cycle.transcript.heading("2 · Grooming")

    proposals = ask(cycle, "product", brief(cycle, "Head of Product", f"""
        Open grooming. Propose **one to three** candidate items for this cycle.

        Problem first, in plain words, before any solution. Bring evidence.
        Read memory/tried-and-failed.md before you propose anything — do not re-propose a
        disproved idea without new evidence.

        Here is the situation:

        {situation}
        """), contract="proposals")

    cycle.transcript.block("Proposals", {"": ""})
    for p in proposals.get("proposals", []):
        cycle.transcript.block(p.get("title", "untitled"), p)

    proposal_text = json.dumps(proposals, indent=2)
    participants = ["architect", "qa", "researcher"]
    round_no = 0

    while participants and round_no < MAX_GROOMING_ROUNDS:
        round_no += 1
        cycle.transcript.write(f"\n### Round {round_no}\n")
        instruction = (
            "Challenge them from your seat. Be specific about what would change your mind."
            if round_no == 1 else
            "Respond to what changed since your last turn. You are allowed to change your "
            "position — say so if you do. If you have nothing new, say so in one line and "
            "stop there."
        )
        round_turns = []
        for role in participants:
            task = (
                f"Round {round_no} of grooming (no fixed limit — the Lead ends it once the "
                f"debate is settled). The proposals are:\n\n{proposal_text}\n\n{instruction}"
            )
            turn = ask(cycle, role, brief(cycle, role, task, meeting_override=cycle.digest), contract="turn")
            cycle.transcript.turn(role, turn)
            round_turns.append((role, turn))

        round_text = "\n\n".join(
            f"[{role}] {t.get('stance')}: {t.get('argument')}" for role, t in round_turns
        )
        check = ask(cycle, "lead", brief(cycle, "Tech Lead", f"""
            You just ran round {round_no} of grooming. Running digest so far:

            {cycle.digest or "(nothing yet — this was the first round)"}

            What was just said in round {round_no}:

            {round_text}

            Decide: does the debate need another round, and if so, who from
            [architect, qa, researcher] should speak next (drop anyone with nothing left to
            add)? Update the digest to fold this round in.
            """, meeting_override=cycle.digest), contract="round_check")
        cycle.transcript.block(f"[lead] round {round_no} check", check)

        cycle.digest = check.get("digest") or cycle.digest
        if not check.get("continue_grooming"):
            break
        participants = [
            p for p in (check.get("next_participants") or [])
            if p in ("architect", "qa", "researcher")
        ]

    ruling = ask(cycle, "lead", brief(cycle, "Tech Lead", f"""
        Close grooming. Pick **exactly one** item, or rule research-only / no-work.

        The proposals were:

        {proposal_text}

        The debate is distilled in the digest above. Name the runner-up and why it lost.
        Overrule any objection that carried no evidence, and say so in one sentence. Set a
        scope limit the dev will be held to — this is what stops the cycle running out of
        budget.

        Parked work from a previous cycle beats a new idea. Check the standup — if you are
        picking up parked work, set `resume_branch` to its exact branch name so the dev builds
        on what already exists instead of redoing it. Leave it empty for genuinely new work.

        Resuming means shipping it, not growing it: if a proposal bundles "finish the parked
        thing" with a new capability, rule on finishing it and send the new idea to `deferred`
        for its own cycle. scope_limit must rule out anything not already needed to make the
        existing diff mergeable.
        """, meeting_override=cycle.digest), contract="ruling")

    cycle.transcript.write("\n### Ruling\n")
    cycle.transcript.block(f"[lead] {ruling.get('decision')}", ruling)

    # Written here, not only in retro, because both real cycles so far stopped before phase 7 —
    # if this only happened at retro, the digest would be lost exactly when it matters most.
    with (MEMORY / "digests.md").open("a") as fh:
        fh.write(f"\n## {cycle.cycle_id} · {ruling.get('chosen') or ruling.get('decision')}\n\n")
        fh.write(f"{(cycle.digest or '').strip()}\n\n")
        fh.write(f"Ruling: {ruling.get('decision')} — {(ruling.get('why') or '').strip()[:300]}\n")

    return ruling


SCREENSHOTS = TEAM / "artifacts" / "screenshots"


def capture_ui_screenshots(cycle: Cycle) -> list[Path]:
    """Run team/tools/ui-screenshot.sh so design/build turns can Read what the UI actually
    looks like today, instead of guessing. Frontend-only, since it boots the sandbox + a
    real browser — skip it for a backend-only item. Non-fatal: a broken sandbox shouldn't
    sink the whole cycle over a nice-to-have; the roles just design/build without it.
    """
    cycle.log("  capturing UI screenshots …")
    proc = subprocess.run(
        [str(TEAM / "tools" / "ui-screenshot.sh")], cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        cycle.log(f"    screenshot capture failed ({proc.returncode}) — continuing without it")
        cycle.transcript.note("UI screenshot capture failed; design/build proceeded without it.")
        return []
    paths = sorted(SCREENSHOTS.glob("*.png"))
    cycle.log(f"    {len(paths)} screenshot(s)")
    return paths


def _screenshot_note(paths: list[Path]) -> str:
    if not paths:
        return ""
    listed = "\n".join(f"- {p}" for p in paths)
    return f"""
        Before you go further, look at what the UI actually looks like right now (sandbox
        data, same styles/components as production). Read each of these image files:
        {listed}
        """


def phase3_design(cycle: Cycle, ruling: dict) -> dict:
    """Architect writes the ADR, Product sanity-checks it, Lead approves."""
    cycle.log("phase 3 — design")
    cycle.transcript.heading("3 · Design")

    adr_number = 1 + max(
        (int(p.name.split("-")[1]) for p in DECISIONS.glob("ADR-*.md")), default=0
    )
    slug = ruling.get("slug") or "untitled"
    adr_path = DECISIONS / f"ADR-{adr_number:04d}-{slug}.md"

    screenshots = (
        capture_ui_screenshots(cycle)
        if ruling.get("assignee") in ("frontend-dev", "both") else []
    )

    design = ask(cycle, "architect", brief(cycle, "Architect", f"""
        The Lead chose: **{ruling.get('chosen')}**

        Why: {ruling.get('why')}
        Explicitly out of scope: {ruling.get('scope_limit')}
        {_screenshot_note(screenshots)}
        Write the ADR. The `invariants` field matters most — write each one so a reviewer can
        check it against a diff, one by one. Also fill in `rejected`: in three months that is
        the most valuable part of the file.
        """), contract="design")

    cycle.transcript.block(f"[architect] ADR-{adr_number:04d}", design)

    check = ask(cycle, "product", brief(cycle, "Head of Product", f"""
        The Architect's design for **{ruling.get('chosen')}**:

        {json.dumps(design, indent=2)}

        Does this still solve the user problem you raised? If it has drifted into something
        easier but less useful, say so now — after the build is too late. Stance `support`,
        `amend` or `object`.
        """), contract="turn")
    cycle.transcript.turn("product", check)

    body = [
        f"# ADR-{adr_number:04d} — {design.get('title', slug)}",
        "",
        f"_Cycle {cycle.cycle_id}._",
        "",
    ]
    for key in ("problem", "approach", "rollback"):
        body += [f"## {key.title()}", "", str(design.get(key, "")).strip(), ""]
    for key in ("invariants", "changes", "tests", "rejected", "risks"):
        items = design.get(key) or []
        if items:
            body += [f"## {key.title()}", "", *[f"- {i}" for i in items], ""]
    adr_path.write_text("\n".join(body))
    cycle.log(f"  wrote {adr_path.relative_to(ROOT)}")

    design["_adr_path"] = str(adr_path.relative_to(ROOT))
    design["_adr_number"] = adr_number
    design["_screenshot_paths"] = [str(p) for p in screenshots]
    return design


def phase4_build(cycle: Cycle, ruling: dict, design: dict) -> None:
    """Implement the ADR in an isolated worktree, never in Roy's working tree.

    If the Lead named a parked branch to resume (`ruling['resume_branch']`), the dev builds on
    top of what's already there instead of starting over. Without this, a cycle that parks
    mid-review throws its commits away: the next cycle cuts a brand new branch from main and
    the dev re-implements the same feature from scratch — confirmed happening between cycle 4
    and cycle 5 on the same co-ownership work.
    """
    cycle.log("phase 4 — build")
    cycle.transcript.heading("4 · Build")

    slug = ruling.get("slug") or "untitled"
    resume_branch = ruling.get("resume_branch") or ""

    # `origin/main`, not `HEAD` — HEAD is whatever's checked out in Roy's own working copy,
    # which is routinely a long-running local branch that never touches `main`. Basing a cycle's
    # branch on that silently bundles in everything on it: cycles 3-6 all did this, so their
    # branches (and the eventual PR against `main`) carried thousands of unrelated lines.
    run(["git", "fetch", "origin", "main"], check=True)
    main_tip = run(["git", "rev-parse", "origin/main"])

    if resume_branch and _branch_exists(resume_branch):
        cycle.branch = resume_branch
        cycle.base_sha = run(["git", "merge-base", "origin/main", resume_branch]) or main_tip
        if (existing := _find_worktree_for_branch(resume_branch)) and existing.exists():
            cycle.worktree = existing
        else:
            cycle.worktree = WORKTREES / slug
            WORKTREES.mkdir(parents=True, exist_ok=True)
            run(["git", "worktree", "add", str(cycle.worktree), resume_branch], check=True)
        cycle.log(f"  resuming {resume_branch} in {cycle.worktree} (parked, not restarted)")
    else:
        if resume_branch:
            cycle.log(f"  {resume_branch} named to resume but no longer exists — starting fresh")
        cycle.branch = f"team/{cycle.cycle_id}-{slug}"
        cycle.worktree = WORKTREES / f"{cycle.cycle_id}-{slug}"
        WORKTREES.mkdir(parents=True, exist_ok=True)
        cycle.base_sha = main_tip
        run(
            ["git", "worktree", "add", "-b", cycle.branch, str(cycle.worktree), cycle.base_sha],
            check=True,
        )
        cycle.log(f"  worktree {cycle.worktree} on {cycle.branch}")

    assignee = ruling.get("assignee", "backend-dev")
    devs = ["backend-dev", "frontend-dev"] if assignee == "both" else [assignee]

    resume_note = (
        f"\nThis branch already has committed work from a previous cycle (`git log` to see\n"
        f"it) — you are finishing it, not starting over. Build on what's there.\n"
        if resume_branch and cycle.branch == resume_branch else ""
    )

    screenshot_note = (
        _screenshot_note([Path(p) for p in design.get("_screenshot_paths") or []])
        if "frontend-dev" in devs else ""
    )

    for dev in devs:
        if dev in ("none", "researcher"):
            continue
        result = ask(cycle, dev, brief(cycle, dev, f"""
            Implement this ADR. You are in a git worktree at {cycle.worktree} on branch
            `{cycle.branch}`. Work only there.
            {resume_note}
            {screenshot_note if dev == "frontend-dev" else ""}
            {json.dumps(design, indent=2)}

            Out of scope, per the Lead: {ruling.get('scope_limit')}
            Anything else you find broken goes to team/memory/backlog.md, not into this diff.

            Ship tests in the same change. Run them. Then `git add -A` and commit with a
            message that says what changed and why.

            Return a short plain-text summary of what you did and anything you could not do.
            """), tools=WRITE_TOOLS, cwd=cycle.worktree)
        cycle.transcript.write(f"**[{dev}]**\n")
        cycle.transcript.write(textwrap.fill(str(result).strip()[:3000], 92))
        cycle.transcript.write()

    diffstat = run(["git", "diff", "--stat", f"{cycle.base_sha}..HEAD"], cwd=cycle.worktree)
    cycle.transcript.write("```\n" + (diffstat or "(no commit was made)") + "\n```\n")


def _merge_reviews(reviews: list[dict]) -> dict:
    """Fold the lens reviews into one verdict. Any block blocks; findings are concatenated."""
    return {
        "verdict": "block" if any(r.get("verdict") == "block" for r in reviews) else "pass",
        "summary": " · ".join(f"[{r['_lens']}] {r.get('summary', '')}" for r in reviews),
        "findings": [f for r in reviews for f in (r.get("findings") or [])],
        "invariants_checked": [i for r in reviews for i in (r.get("invariants_checked") or [])],
    }


def phase5_review(cycle: Cycle, ruling: dict, design: dict) -> tuple[dict, dict]:
    """Two reviewers and QA run in parallel; none of them reads the others' output.

    Every turn here gets the grooming digest plus the scope limit instead of the full
    transcript — by this point that transcript also carries all of design and build, and
    none of these roles were ever told to read it: reviewers and QA work from the ADR and a
    freshly re-read diff, the repair-pass dev works from the findings handed to it directly.
    Review was the phase actually dying from usage exhaustion every real cycle so far; this is
    the same fix that took grooming from 11 calls to 6, applied to the phase that needed it most.
    """
    cycle.log("phase 5 — review")
    cycle.transcript.heading("5 · Review")

    adr = json.dumps(design, indent=2)
    review_context = f"{cycle.digest}\n\nScope limit: {ruling.get('scope_limit', '')}"

    def reviewer_turn(lens: str) -> dict:
        # Re-read the diff each pass; a repair commit moves HEAD underneath us.
        diff = run(["git", "diff", f"{cycle.base_sha}..HEAD"], cwd=cycle.worktree)[:60000]
        out = ask(cycle, "reviewer", brief(cycle, "Reviewer", f"""
            Read this diff cold, against the ADR. You are adversarial. Do not run the test
            suites — QA is doing that in parallel.

            **Your lens this pass is `{lens}`.** {REVIEW_LENSES[lens]}

            Another reviewer is reading the same diff through the other lens, so stay in
            yours rather than covering everything shallowly.

            ADR:
            {adr}

            The branch is checked out at {cycle.worktree}. The diff:

            ```diff
            {diff}
            ```

            A `block` finding needs a concrete failure scenario; without one it will be
            overruled.
            """, meeting_override=review_context), cwd=cycle.worktree, contract="review")
        out["_lens"] = lens
        return out

    def qa_turn() -> dict:
        return ask(cycle, "qa", brief(cycle, "QA", f"""
            Gate this change. You are in the worktree at {cycle.worktree}.

            ADR:
            {adr}

            Actually run the gates and paste the real output — never assert a result you did
            not observe. If a gate cannot run yet (the sandbox or the E2E harness does not
            exist), mark that check `skipped` and say why in its `output`. Do not invent
            passes, and do not weaken a test to reach green.

            Then answer `does_what_adr_said` honestly. Green tests on the wrong feature is
            still a block.
            """, meeting_override=review_context), tools=WRITE_TOOLS, cwd=cycle.worktree, contract="qa")

    def gate() -> tuple[dict, dict]:
        jobs = [lambda ln=ln: reviewer_turn(ln) for ln in REVIEW_LENSES] + [qa_turn]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            results = [f.result() for f in [pool.submit(j) for j in jobs]]
        return _merge_reviews(results[:-1]), results[-1]

    dev = ruling.get("assignee", "backend-dev")
    dev = "backend-dev" if dev in ("both", "none", "researcher") else dev

    for attempt in range(MAX_REPAIR_PASSES + 1):
        review, qa = gate()
        label = "" if attempt == 0 else f" (after repair {attempt})"
        cycle.transcript.block(f"[reviewers]{label}", review)
        cycle.transcript.block(f"[qa]{label}", qa)

        if review.get("verdict") != "block" and qa.get("verdict") != "block":
            return review, qa
        if attempt == MAX_REPAIR_PASSES:
            break

        cycle.log(f"  blocked — repair pass {attempt + 1} of {MAX_REPAIR_PASSES}")
        ask(cycle, dev, brief(cycle, dev, f"""
            Your change is blocked. This is repair pass {attempt + 1} of {MAX_REPAIR_PASSES}.

            Reviewers: {json.dumps(review, indent=2)}
            QA: {json.dumps(qa, indent=2)}

            Fix what is cited. If you believe a finding is wrong, say why with evidence in
            your commit message rather than silently ignoring it — the Lead will rule. Amend
            or commit on top, then stop.
            """, meeting_override=review_context), tools=WRITE_TOOLS, cwd=cycle.worktree)

    cycle.transcript.note(
        f"Still blocked after {MAX_REPAIR_PASSES} repair passes. Parking the item with the "
        f"branch intact rather than looping."
    )
    return review, qa


PARKED_NOTE = "**PARKED.** A gate still blocks this. The branch is left intact for the next cycle."
GREEN_NOTE = "Both agent gates pass. CI decides."


def phase6_ship(cycle: Cycle, ruling: dict, design: dict, review: dict, qa: dict) -> str:
    """Push and open the PR. CI is the judge from here."""
    cycle.log("phase 6 — ship")
    cycle.transcript.heading("6 · Ship")

    parked = review.get("verdict") == "block" or qa.get("verdict") == "block"
    transcript_rel = cycle.transcript.path.relative_to(ROOT)

    body = textwrap.dedent(f"""
        ## Decision

        {ruling.get('why', '')}

        Runner-up: {ruling.get('runner_up') or '—'}
        Out of scope: {ruling.get('scope_limit', '')}

        ## Design

        [{design.get('_adr_path')}]({design.get('_adr_path')})

        ## Verdicts

        - **Reviewer:** {review.get('verdict')} — {review.get('summary', '')}
        - **QA:** {qa.get('verdict')} — {len(qa.get('checks') or [])} checks run

        ## Transcript

        [{transcript_rel}]({transcript_rel})

        ---
        {PARKED_NOTE if parked else GREEN_NOTE}

        🤖 opened by the crate-digger agent team, cycle {cycle.cycle_id}
        """).strip()

    if cycle.dry_run:
        cycle.log("  dry run — not pushing, not opening a PR")
        cycle.transcript.note("Dry run. Nothing was pushed.")
        (TEAM / "logs" / f"{cycle.cycle_id}-pr-body.md").write_text(body)
        return "(dry run)"

    run(["git", "push", "-u", "origin", cycle.branch], check=True)
    out = run([
        "gh", "pr", "create",
        "--title", f"{ruling.get('chosen')}",
        "--body", body,
        "--head", cycle.branch,
        "--base", "main",
    ])
    cycle.log(f"  {out}")
    cycle.transcript.write(out)

    if not parked:
        cycle.log("  " + run(["gh", "pr", "merge", "--squash", "--auto", cycle.branch]))
    else:
        run(["gh", "pr", "edit", cycle.branch, "--add-label", "parked"])
    return out


def phase7_retro(cycle: Cycle, ruling: dict, review: dict, qa: dict) -> dict:
    """Write down what survives the cycle."""
    cycle.log("phase 7 — retro")
    cycle.transcript.heading("7 · Retro")

    retro = ask(cycle, "lead", brief(cycle, "Tech Lead", f"""
        Close the cycle. Item: {ruling.get('chosen')}.
        Reviewer {review.get('verdict')}, QA {qa.get('verdict')}.
        The usage window is {cycle.window.headroom()}.

        Be honest in `closer_to_goal`. "No, but we learned X" is a good cycle. What you put in
        `learned` and `failed` is the only thing that survives — an agent in three days has no
        memory of this except those files.
        """), contract="retro")
    cycle.transcript.block("[lead] retro", retro)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if failed := retro.get("failed"):
        with (MEMORY / "tried-and-failed.md").open("a") as fh:
            fh.write(f"\n## {stamp} · cycle {cycle.cycle_id} · {ruling.get('chosen')}\n\n")
            fh.writelines(f"- {item}\n" for item in failed)
    if added := retro.get("backlog_add"):
        with (MEMORY / "backlog.md").open("a") as fh:
            fh.write(f"\n<!-- added by cycle {cycle.cycle_id} -->\n")
            fh.writelines(f"- [ ] {item}\n" for item in added)
    # metrics.md itself is written unconditionally in main()'s `finally` block — every
    # cycle leaves a row there, not only ones that reach this phase.
    return retro


# --------------------------------------------------------------------------------------
# preflight and entry point
# --------------------------------------------------------------------------------------


def write_summary(
    cycle: Cycle,
    ruling: dict,
    design: dict,
    review: dict,
    qa: dict,
    retro: dict,
    outcome: str,
    parked: bool,
) -> Path:
    """Write the short report Roy gets by email. Written for someone who has never seen this
    project — no jargon, no phase-by-phase account, no code. Full detail always stays in the
    transcript on disk and in memory/; this is just: what happened, and what it means, in a
    few sentences. Every prior version of this grew a new section every time someone wanted
    one more fact in it — resist that. If it needs a heading, it is not simple enough."""
    chosen = ruling.get("chosen") if ruling else None
    plain = (ruling.get("plain_summary") if ruling else None) or ""
    plain_shipped = (retro.get("plain_shipped") if retro else None) or ""

    if not ruling:
        headline = "Nothing decided"
        body = "The team's meeting didn't reach a decision this time."
    elif ruling.get("decision") == "no-work":
        headline = "Nothing needed doing"
        body = plain or "Nothing looked worth fixing this time."
    elif ruling.get("decision") == "research-only":
        headline = "Just research today, no changes"
        body = plain or "The team spent this round learning, not building."
    elif cycle.pr_url:
        headline = f"Ready for you to look at: {chosen}"
        body = f"{plain_shipped or plain}\n\nOpen for you to review: {cycle.pr_url}"
    elif parked:
        headline = f"Still working on: {chosen}"
        body = (
            f"{plain}\n\nIt ran out of time partway through, so nothing has changed yet. "
            f"It'll pick back up automatically and finish this next time."
        )
    else:
        headline = f"Didn't finish: {chosen}"
        body = f"{plain}\n\nSomething stopped it partway through — nothing changed."

    lines = [
        f"# crate-digger — {headline}",
        "",
        body.strip(),
        "",
        f"Details if you want them: {cycle.transcript.path.relative_to(ROOT)}",
    ]

    path = TEAM / "logs" / f"{cycle.cycle_id}-summary.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def active_claude_account() -> str:
    """Whichever account `claude` would bill right now, or "" if that cannot be read."""
    try:
        return json.loads(run(["claude", "auth", "status"])).get("email") or ""
    except (json.JSONDecodeError, KeyError, TypeError):
        return ""


def preflight(will_push: bool) -> list[str]:
    """Refuse to run against anything real. Returns a list of fatal problems."""
    problems = []

    account = active_claude_account()
    if account != TEAM_ACCOUNT:
        problems.append(
            f"`claude` is signed in as {account or 'nobody'}, not {TEAM_ACCOUNT}. A cycle now "
            f"would spend that account's quota. Run: claude auth login"
        )

    if will_push:
        # `gh` resolves the repo from the git remote and answers an unauthorised query with an
        # empty list rather than an error, so a wrong account looks like "no open PRs" all the
        # way to phase 6 — after the whole cycle's budget has been spent. Check it up front.
        if '"name"' not in run(["gh", "repo", "view", "--json", "name"]):
            problems.append(
                "`gh` cannot see this repository, so phase 6 could not open a PR. The active "
                "account is likely wrong: `gh auth switch -u roylivnegit`. Pushing workflow "
                "files also needs `gh auth refresh -h github.com -s workflow`."
            )

    db = os.environ.get("DATABASE_URL", "")
    if any(marker in db.lower() for marker in ("neon", "render", "amazonaws")):
        host = db.split("@")[-1][:40]
        problems.append(f"DATABASE_URL points at a hosted database ({host}). Sandbox only.")
    if os.environ.get("NIMBLE_API_KEY"):
        problems.append("NIMBLE_API_KEY is set. The team must never be able to spend credits.")
    if (MEMORY / "needs-roy.md").exists():
        problems.append(
            f"{MEMORY / 'needs-roy.md'} exists — a previous cycle needs an answer first."
        )
    if not shutil.which("claude"):
        problems.append("the `claude` CLI is not on PATH")

    dirty = run(["git", "status", "--porcelain"])
    if dirty:
        problems.append(
            f"the working tree is dirty; the team will not build on it:\n{dirty[:500]}"
        )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one crate-digger team cycle.")
    ap.add_argument("--dry-run", action="store_true", help="run everything except push and PR")
    ap.add_argument("--phases", default="1-7", help="how far to go, e.g. 1-3 for the meeting only")
    ap.add_argument(
        "--ceiling",
        type=float,
        default=WINDOW_CEILING,
        help="stop when this share of the five-hour usage window is gone (default 0.85)",
    )
    ap.add_argument("--force", action="store_true", help="run despite preflight problems")
    args = ap.parse_args()

    # A range always starts at 1: every later phase consumes an earlier one's output, so
    # there is no honest way to start at phase 4 without a ruling and an ADR to build from.
    lo, _, hi = args.phases.partition("-")
    first, last = int(lo), int(hi or lo)
    if first != 1 or not 1 <= last <= 7:
        ap.error(f"--phases must be 1-N where N is 1..7, got {args.phases!r}")

    if problems := preflight(will_push=last >= 6 and not args.dry_run):
        for p in problems:
            print(f"PREFLIGHT: {p}", file=sys.stderr)
        if not args.force:
            print("\nRefusing to start. Fix the above, or pass --force.", file=sys.stderr)
            return 1

    state_path = MEMORY / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    number = state.get("cycle_number", 0) + 1
    cycle_id = f"{now_iso()}-c{number:03d}"

    # Claim the number now rather than in the retro. run-cycle.sh holds a pid lock so two
    # cycles should never overlap, but a cycle started by hand bypasses it — and a crashed
    # run should still consume its number instead of letting the next one reuse it.
    state["cycle_number"] = number
    state_path.write_text(json.dumps(state, indent=2) + "\n")

    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    transcript = Transcript(TRANSCRIPTS / f"{cycle_id}.md")
    transcript.write(f"# Cycle {number} — {cycle_id}")
    transcript.write(
        f"\nDraining the five-hour usage window to {args.ceiling:.0%}. "
        f"Phases {first}–{last}.{' Dry run.' if args.dry_run else ''}\n"
    )

    cycle = Cycle(
        cycle_id=cycle_id,
        number=number,
        window=Window(ceiling=args.ceiling),
        transcript=transcript,
        dry_run=args.dry_run,
        state=state,
    )

    ruling: dict = {}
    design: dict = {}
    review: dict = {"verdict": "skipped"}
    qa: dict = {"verdict": "skipped"}
    retro: dict = {}
    outcome = "did not finish"
    exit_code = 0

    try:
        situation = phase1_standup(cycle)
        if last >= 2:
            ruling = phase2_grooming(cycle, situation)
            if ruling.get("decision") != "build":
                cycle.log(f"lead ruled '{ruling.get('decision')}' — no code this cycle")
                transcript.note(f"No build this cycle: {ruling.get('why', '')}")
                last = min(last, 2)
        if last >= 3:
            design = phase3_design(cycle, ruling)
        if last >= 4:
            phase4_build(cycle, ruling, design)
        if last >= 5:
            review, qa = phase5_review(cycle, ruling, design)
        if last >= 6:
            cycle.pr_url = phase6_ship(cycle, ruling, design, review, qa)
        if last >= 7:
            retro = phase7_retro(cycle, ruling, review, qa)
        outcome = "finished"
    except BudgetExhausted as exc:
        cycle.log(f"BUDGET: {exc}")
        transcript.note(f"Cycle ended early: {exc}. Work is parked on `{cycle.branch}`.")
        outcome = f"stopped early — {exc}"
        exit_code = 2
    except Exception as exc:  # noqa: BLE001 — a cycle must always leave clean state behind
        cycle.log(f"FAILED: {exc}")
        transcript.note(f"Cycle failed: {exc}")
        outcome = f"failed — {exc}"
        exit_code = 1
    finally:
        parked = bool(cycle.branch) and (
            exit_code != 0 or review.get("verdict") == "block" or qa.get("verdict") == "block"
        )
        state.update({
            "cycle_number": number,
            "last_cycle_id": cycle_id,
            "last_main_sha": run(["git", "rev-parse", "HEAD"]),
            "last_spend_usd": round(cycle.window.spend_usd, 3),
            "resets_at": cycle.window.resets_at,
            "last_utilization": round(cycle.window.utilization, 3),
            "parked": {"title": ruling.get("chosen"), "branch": cycle.branch} if parked else None,
        })
        state_path.write_text(json.dumps(state, indent=2) + "\n")

        # Written here, not only in phase7_retro, because most real cycles so far have
        # stopped before reaching it — a metrics table only the rare finished cycle can
        # write to is useless to the dashboard (E0-6). Every cycle leaves a row.
        with (MEMORY / "metrics.md").open("a") as fh:
            fh.write(
                f"| {datetime.now(timezone.utc).strftime('%Y-%m-%d')} | {cycle_id} | "
                f"{ruling.get('chosen', '—')} | {review.get('verdict')}/{qa.get('verdict')} | "
                f"${cycle.window.spend_usd:.2f} | {retro.get('closer_to_goal') or outcome} |\n"
            )

        if cycle.worktree and cycle.worktree.exists() and not parked:
            run(["git", "worktree", "remove", "--force", str(cycle.worktree)])

        # Written last, and in `finally`, so a crashed or budget-stopped cycle still reports.
        # run-cycle.sh emails whatever this leaves behind.
        write_summary(cycle, ruling, design, review, qa, retro, outcome, parked)

        cycle.log(
            f"done — {cycle.window.headroom()}, ${cycle.window.spend_usd:.2f} notional, "
            f"transcript at {transcript.path.relative_to(ROOT)}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
