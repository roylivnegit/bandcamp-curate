"""Set (or reset) a user's password directly in the DB.

Usage:
    python -m scripts.set_password <username> <new_password>

Needed once right after applying migration 0008 (users_and_ownership): the
backfilled "operator" user gets an unusable placeholder password hash (a
migration can't securely hash a real one), so this is the only way to log in
as that account until you use it. Also handy for any account whose password
you've lost, since there's no email-based reset flow.
"""

import asyncio
import sys

from sqlalchemy import select

from app.auth.security import hash_password
from app.db.models import User
from app.db.session import get_sessionmaker


async def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m scripts.set_password <username> <new_password>")
        return 2
    username, password = sys.argv[1], sys.argv[2]

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if user is None:
            print(f"no user named {username!r}")
            return 1
        try:
            user.password_hash = hash_password(password)
        except ValueError as exc:
            print(f"couldn't hash that password: {exc}")
            return 1
        await session.commit()
        print(f"password set for {username!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
