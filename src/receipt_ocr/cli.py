from __future__ import annotations

import argparse

from .config import ensure_dirs, load_config
from .drive_client import sync_drive_folder
from .pipeline import run_local
from .review_server import run_review_server


def main() -> int:
    parser = argparse.ArgumentParser(prog="receipt-ocr")
    parser.add_argument("--config", default="config/config.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Process local inbox images")
    run_parser.add_argument(
        "--payer",
        help="Fallback payer for legacy filenames. App filenames embed this value.",
    )
    run_parser.add_argument(
        "--sync-drive",
        action="store_true",
        help="Import images from configured Drive sync folder before OCR",
    )

    subparsers.add_parser(
        "sync-drive",
        help="Import images from configured Drive sync folder into local inbox",
    )

    review_parser = subparsers.add_parser(
        "review",
        help="Start a local web UI for categorizing uncategorized items",
    )
    review_parser.add_argument("--host", default="127.0.0.1")
    review_parser.add_argument("--port", type=int, default=8765)

    subparsers.add_parser("sync-cloud", help="Sync pending local receipts to Firestore")
    migrate_parser = subparsers.add_parser("migrate-cloud", help="Upload existing receipts as review-required")
    bootstrap_parser = subparsers.add_parser("bootstrap-cloud", help="Create household, allowlist, and default categories")
    bootstrap_parser.add_argument("--email", action="append", required=True, help="Allowed Google account (repeatable)")

    worker_parser = subparsers.add_parser("cloud-worker", help="Run the OCI Cloud Vision PoC worker")
    worker_parser.add_argument("worker_action", nargs="?", choices=("status", "retry"))
    worker_parser.add_argument("drive_file_id", nargs="?")
    worker_parser.add_argument("--poc", action="store_true", required=True)
    worker_parser.add_argument("--once", action="store_true")
    worker_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    config = load_config(args.config)
    ensure_dirs(config)

    if args.command == "run":
        if args.sync_drive:
            imported = sync_drive_folder(config)
            print(f"imported={imported}")
        count = run_local(config, payer=args.payer)
        print(f"processed={count}")
        return 0

    if args.command == "sync-drive":
        count = sync_drive_folder(config)
        print(f"imported={count}")
        return 0

    if args.command == "review":
        run_review_server(args.config, host=args.host, port=args.port)
        return 0

    if args.command in {"sync-cloud", "migrate-cloud"}:
        from .cloud import sync_cloud
        result = sync_cloud(config, include_existing_as_review=args.command == "migrate-cloud")
        print(f"synced={result['synced']} failed={result['failed']}")
        return 1 if result["failed"] else 0

    if args.command == "bootstrap-cloud":
        from .cloud import bootstrap_cloud
        bootstrap_cloud(config, args.email)
        print("bootstrap=complete")
        return 0

    if args.command == "cloud-worker":
        import json
        from .cloud_worker import create_worker

        worker = create_worker(config)
        if args.worker_action == "status":
            print(json.dumps(worker._writer.list_jobs(), ensure_ascii=False, default=str))
            return 0
        if args.worker_action == "retry":
            if not args.drive_file_id:
                parser.error("cloud-worker retry requires a Drive file ID")
            retried = worker._writer.retry_unknown(args.drive_file_id)
            print(f"retry_ready={str(retried).lower()} drive_file_id={args.drive_file_id}")
            return 0 if retried else 1
        if not args.once and not args.dry_run:
            parser.error("cloud-worker requires --once or --dry-run")
        result = worker.run_once(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["status"] in {"failed", "unknown_after_request", "invalid_source"} else 0

    parser.error(f"unknown command: {args.command}")
    return 2
