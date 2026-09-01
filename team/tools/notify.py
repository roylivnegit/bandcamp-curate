#!/usr/bin/env python3
"""Email the cycle summary.

    python3 team/tools/notify.py team/logs/<cycle-id>-summary.md

Run by `run-cycle.sh` after every session, from the shell — never from inside an agent turn.
That separation is the point: the SMTP credential lives in the macOS Keychain and only this
script reads it, so no agent ever has a path to it.

Storing the credential (one time, and it never touches the repo):

    security add-generic-password -a royee.livne6@gmail.com -s crate-digger-team-smtp -w

Gmail rejects an account password over SMTP, so that has to be an **app password** from
https://myaccount.google.com/apppasswords (needs 2-step verification switched on).

If the Keychain entry is missing this exits 0 and says so. A cycle's work is not lost because
the mail failed — the summary is on disk either way.
"""

from __future__ import annotations

import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

TO = "royee.livne6@gmail.com"
KEYCHAIN_SERVICE = "crate-digger-team-smtp"
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465


def keychain_password(account: str) -> tuple[str | None, str]:
    """Return (password, why-not). An entry holding an empty password is its own failure
    mode — it happens when the interactive prompt is answered with a bare Enter — and it
    needs a different fix (`-U` to update) than a missing entry, so say which it is."""
    proc = subprocess.run(
        ["security", "find-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None, f"no Keychain entry for {account} / {KEYCHAIN_SERVICE}"
    if not proc.stdout.strip():
        return None, (
            f"the Keychain entry for {account} / {KEYCHAIN_SERVICE} exists but is empty; "
            f"re-enter it with the -U flag to overwrite"
        )
    # Google displays an app password as four spaced groups and rejects the spaced form,
    # so a copy-paste that keeps them would fail login for no visible reason.
    return "".join(proc.stdout.split()), ""


def subject_from(summary: str) -> str:
    """First heading is written to work as a subject line on its own."""
    for line in summary.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "crate-digger team — cycle report"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: notify.py <summary.md>", file=sys.stderr)
        return 2

    path = Path(argv[0])
    if not path.is_file():
        print(f"notify: no summary at {path}; nothing to send", file=sys.stderr)
        return 0

    summary = path.read_text()
    password, why = keychain_password(TO)
    if not password:
        print(
            f"notify: {why} — not sending.\n"
            f"        the summary is at {path}\n"
            f"        to fix, run this in a terminal (it prompts twice):\n"
            f"        security add-generic-password -U -a {TO} -s {KEYCHAIN_SERVICE} -w",
            file=sys.stderr,
        )
        return 0

    message = EmailMessage()
    message["From"] = TO
    message["To"] = TO
    message["Subject"] = subject_from(summary)
    message.set_content(summary)

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.login(TO, password)
            smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001 — a failed email must never fail the cycle
        print(f"notify: send failed ({exc}); the summary is at {path}", file=sys.stderr)
        return 0

    print(f"notify: emailed {TO} — {message['Subject']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
