"""Seed the `whitelist` collection from existing `users` collection.

Usage:
    python scripts/seed_whitelist.py                 # list users, prompt confirmation, seed all
    python scripts/seed_whitelist.py --yes           # seed all without prompting
    python scripts/seed_whitelist.py --list          # only list existing users, don't seed
    python scripts/seed_whitelist.py --add <userId>  # add one userId manually
    python scripts/seed_whitelist.py --remove <userId>
    python scripts/seed_whitelist.py --show          # show current whitelist
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import whitelist_repo
from app.db.client import get_db


def list_users() -> list[dict]:
    db = get_db()
    return list(db["users"].find({}, {"_id": 1, "display_name": 1}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    ap.add_argument("--list", action="store_true", help="only list users, don't seed")
    ap.add_argument("--show", action="store_true", help="show current whitelist")
    ap.add_argument("--add", metavar="USER_ID", help="add a single userId")
    ap.add_argument("--remove", metavar="USER_ID", help="remove a userId")
    args = ap.parse_args()

    if args.show:
        entries = whitelist_repo.list_all()
        print(f"Whitelist ({len(entries)} entries):")
        for e in entries:
            print(f"  - {e['id']}  {e.get('display_name', '')}")
        return

    if args.add:
        whitelist_repo.add(args.add)
        print(f"Added {args.add} to whitelist.")
        return

    if args.remove:
        removed = whitelist_repo.remove(args.remove)
        print(f"{'Removed' if removed else 'Not found'}: {args.remove}")
        return

    users = list_users()
    print(f"Found {len(users)} existing users in `users` collection:")
    for u in users:
        print(f"  - {u['_id']}  {u.get('display_name', '')}")

    if args.list:
        return

    if not users:
        print("Nothing to seed.")
        return

    if not args.yes:
        ans = input(f"\nSeed all {len(users)} userIds into whitelist? [y/N] ").strip().lower()
        if ans != "y":
            print("Aborted.")
            return

    for u in users:
        whitelist_repo.add(u["_id"], u.get("display_name", ""))
    print(f"Seeded {len(users)} users into whitelist.")


if __name__ == "__main__":
    main()
