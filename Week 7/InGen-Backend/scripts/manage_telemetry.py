"""Manually audit or purge telemetry on a migrated database."""

import argparse
import json

from app.services.telemetry_store import audit, purge


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("audit", "purge"))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete expired rows (purge defaults to dry run).",
    )
    args = parser.parse_args()
    if args.apply and args.operation != "purge":
        parser.error("--apply requires purge")
    print(
        json.dumps(
            audit() if args.operation == "audit" else purge(dry_run=not args.apply)
        )
    )


if __name__ == "__main__":
    main()
