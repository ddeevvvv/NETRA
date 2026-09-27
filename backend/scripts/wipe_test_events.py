#!/usr/bin/env python3
"""
wipe_test_events.py — Delete accumulated test/dev events from the DB.

Preserves: cameras, zones, sites, watchlist_entries.
Deletes:   ALL rows in the `events` table.

Usage (run inside the backend container or with DATABASE_URL set):
    python scripts/wipe_test_events.py [--dry-run] [--yes]

Environment:
    DATABASE_URL  — PostgreSQL DSN (defaults to docker-compose default)
"""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Wipe test events from the IBVAP database")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count rows that would be deleted without touching the DB")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt (for scripted use)")
    args = parser.parse_args()

    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://ibvap:ibvap_secret@ibvap_postgres:5432/ibvap_db",
    )

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("ERROR: sqlalchemy not installed. Run inside the backend container.", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(db_url)

    # --- Count phase (separate connection, auto-committed) ---
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM events")).scalar()
        print(f"Found {total} row(s) in the events table.")

        for tbl in ("cameras", "zones", "sites", "watchlist_entries"):
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                print(f"  {tbl}: {n} row(s) — will be preserved")
            except Exception:
                pass  # table may not exist in all schema versions

    if args.dry_run:
        print("\n[DRY RUN] No rows deleted. Re-run without --dry-run to proceed.")
        return

    if total == 0:
        print("Nothing to delete.")
        return

    if not args.yes:
        confirm = input(f"\nAre you sure you want to permanently delete {total} event row(s)? [yes/no]: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    # --- Delete phase (fresh connection) ---
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM events"))

    print(f"Deleted {total} event row(s). events table is now empty.")


if __name__ == "__main__":
    main()
