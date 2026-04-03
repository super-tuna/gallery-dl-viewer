"""
Index gallery-dl sidecar JSONs into SQLite.

Usage:
    python indexer.py [--config config.yaml] [--verbose]
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

import yaml
import db
import log_setup

logger = logging.getLogger(__name__)

MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm", ".mov"}


def index_dir(con: sqlite3.Connection, data_dir: Path, verbose: bool = False) -> tuple[int, int]:
    added = skipped = 0

    for json_path in sorted(data_dir.rglob("*.json")):
        media_path = json_path.with_suffix("")  # strip .json → actual media file
        if media_path.suffix.lower() not in MEDIA_SUFFIXES:
            continue
        if not media_path.exists():
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("skip %s: %s", json_path.name, e)
            skipped += 1
            continue

        tweet_id = str(data.get("tweet_id", ""))
        if not tweet_id or tweet_id == "0":
            logger.debug("skip %s: no tweet_id", json_path.name)
            skipped += 1
            continue

        db.upsert_post(con, data)
        is_new = db.upsert_media(con, tweet_id, str(media_path.relative_to(data_dir)), data)
        db.upsert_tags(con, tweet_id, data.get("hashtags") or [])
        if is_new:
            added += 1
            logger.debug("indexed: %s", media_path.name)
        else:
            skipped += 1

    return added, skipped


def main():
    parser = argparse.ArgumentParser(description="Index gallery-dl sidecar JSONs into SQLite")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    log_setup.configure(verbose=args.verbose)

    try:
        cfg = yaml.safe_load(open(args.config))
    except FileNotFoundError:
        logger.critical("Config file not found: %s — copy config.example.yaml to config.yaml.", args.config)
        sys.exit(1)

    con = db.init(cfg["db_path"])
    total_added = 0

    for data_dir in cfg["data_dirs"]:
        p = Path(data_dir)
        if not p.exists():
            logger.warning("data_dir not found, skipping: %s", p)
            continue
        logger.info("Indexing %s ...", p)
        added, skipped = index_dir(con, p, args.verbose)
        logger.info("  added: %d, skipped: %d", added, skipped)
        total_added += added

    con.commit()
    con.close()
    logger.info("Done. Total indexed: %d", total_added)


if __name__ == "__main__":
    main()
