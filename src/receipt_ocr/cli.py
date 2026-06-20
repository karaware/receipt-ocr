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

    parser.error(f"unknown command: {args.command}")
    return 2
