"""Create a console user.

    uv run python -m pramana_core.auth.bootstrap --email ops@example.test \\
        --name "Site operator" --roles operator,approver

The password is read from ``PRAMANA_NEW_USER_PASSWORD`` when set (for scripted setup), or
prompted for without echo. It is never taken from the command line, where shells keep history.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from pramana_contracts import StaffRole

from ..db import Database, make_engine
from ..errors import ApiError
from ..settings import get_settings
from .passwords import MIN_PASSWORD_LEN
from .service import AuthService, LoginThrottle


async def _create(email: str, name: str, password: str, roles: list[StaffRole]) -> str:
    cfg = get_settings()
    db = Database(make_engine(cfg))
    try:
        svc = AuthService(db, cfg.session_ttl_s, LoginThrottle(1, 1.0))
        row = await svc.create_user(email, name, password, roles)
        return row.id
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--roles", default="operator", help="comma-separated: operator,approver")
    ap.add_argument(
        "--if-missing", action="store_true", help="succeed quietly when the user already exists"
    )
    args = ap.parse_args(argv)
    try:
        roles = [StaffRole(r.strip()) for r in args.roles.split(",") if r.strip()]
    except ValueError:
        print(f"roles must be from {[r.value for r in StaffRole]}", file=sys.stderr)
        return 2
    password = os.environ.get("PRAMANA_NEW_USER_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD_LEN:
        print(f"the password needs at least {MIN_PASSWORD_LEN} characters", file=sys.stderr)
        return 2
    try:
        uid = asyncio.run(_create(args.email, args.name, password, roles))
    except ApiError as exc:
        if exc.code == "USER_EXISTS" and args.if_missing:
            print(f"{args.email} already exists")
            return 0
        print(exc.message, file=sys.stderr)
        return 1
    print(f"created {uid} ({args.email}) with roles {','.join(r.value for r in roles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
