"""
Perceptual duplicate detection for re-uploaded images.

Authors often re-post the same picture in a new post. The platform re-encodes
it, so the bytes (and the media key) differ — only the pixels are the same.
Detection has two stages, both limited to images of the same author with the
same dimensions:

1. Candidates — a gradient hash (dHash) and a coarse colour grid, stored per
   image. Cheap, but blind to small local edits: a copy with added text or a
   doodle can hash identically.
2. Verification — both files are compared pixel by pixel (see
   local_difference). Results are cached in `media_pairs`, so each pair is
   read from disk only once.

The oldest post's image becomes the canonical copy; newer copies get
`media.canonical_id` pointing at it.

Moving the newer files out of the way is a separate, explicit step:

    python duplicates.py [--config config.yaml]           # dry-run report
    python duplicates.py [--config config.yaml] --apply   # move to .trash

`--apply` moves each duplicate file to `<data_dir>/.trash/<same path>` and
leaves a `<file>.dup` marker (containing the canonical file's relative path)
next to the kept sidecar JSON, so the mapping survives a DB rebuild.
"""

import argparse
import logging
import shutil
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from PIL import Image, ImageChops, ImageFilter, ImageStat

import db
import log_setup

logger = logging.getLogger(__name__)

# Animated GIFs would be judged by their first frame only; videos are not hashed.
HASHABLE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

HASH_SIZE = 16             # dHash grid → 256-bit hash
CANDIDATE_DISTANCE = 20    # Hamming distance (of 256 bits) worth verifying.
                           # Re-encodes of flat backgrounds reach ~15.
COLOR_GRID = 4             # 4x4 RGB averages; the other checks are grayscale
MAX_COLOR_DELTA = 24       # per-channel difference (0-255); tone edits reach ~17

COMPARE_SIZE = 128         # verification thumbnail
COMPARE_GRID = 16          # 8px blocks
Z_SCALE = 48               # 8-bit levels per standard deviation
MAX_LOCAL_DIFF = 0.09      # see local_difference(); calibrated on labelled pairs

TRASH_DIR = ".trash"
MARKER_SUFFIX = ".dup"

# Tumblr occasionally serves huge images; we only ever look at a thumbnail.
Image.MAX_IMAGE_PIXELS = None


def locate(data_dirs: list[Path], rel: str) -> tuple[Path, Path] | None:
    """Return (data_dir, absolute path) of an existing file."""
    for d in data_dirs:
        d = d.resolve()
        p = (d / rel).resolve()
        if p.is_relative_to(d) and p.exists():
            return d, p
    return None


# ---------------------------------------------------------------------------
# Stage 1: fingerprints
# ---------------------------------------------------------------------------

def signature(path: Path) -> tuple[str, str]:
    """Return (dhash_hex, colorsig_hex) for an image file."""
    with Image.open(path) as im:
        # JPEG: decode at a reduced scale — much faster over NFS/large files.
        im.draft("RGB", (HASH_SIZE * 8, HASH_SIZE * 8))
        rgb = im.convert("RGB")

    gray = rgb.convert("L").resize((HASH_SIZE + 1, HASH_SIZE), Image.LANCZOS)
    px = gray.load()
    bits = 0
    for y in range(HASH_SIZE):
        for x in range(HASH_SIZE):
            bits = (bits << 1) | (px[x, y] > px[x + 1, y])

    color = rgb.resize((COLOR_GRID, COLOR_GRID), Image.BOX).tobytes()
    return f"{bits:0{HASH_SIZE * HASH_SIZE // 4}x}", color.hex()


def is_candidate(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    if (int(a["phash"], 16) ^ int(b["phash"], 16)).bit_count() > CANDIDATE_DISTANCE:
        return False
    ca, cb = bytes.fromhex(a["colorsig"]), bytes.fromhex(b["colorsig"])
    return max(abs(x - y) for x, y in zip(ca, cb)) <= MAX_COLOR_DELTA


def compute_signatures(con: sqlite3.Connection, data_dirs: list[Path], workers: int = 8) -> int:
    """Fingerprint every hashable image that has no fingerprint yet."""
    ext_cond = " OR ".join("lower(file_path) LIKE ?" for _ in HASHABLE_SUFFIXES)
    rows = con.execute(
        f"SELECT id, file_path FROM media WHERE phash IS NULL AND ({ext_cond})",
        [f"%{s}" for s in HASHABLE_SUFFIXES],
    ).fetchall()
    if not rows:
        return 0
    logger.info("Fingerprinting %d images ...", len(rows))

    def work(row):
        found = locate(data_dirs, row["file_path"])
        if found is None:
            return row["id"], None          # not on disk (yet) — retry next run
        try:
            return row["id"], signature(found[1])
        except Exception as e:
            logger.warning("fingerprint failed %s: %s", row["file_path"], e)
            return row["id"], ("", "")      # undecodable — don't retry forever

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for media_id, sig in pool.map(work, rows):
            if sig is None:
                continue
            con.execute(
                "UPDATE media SET phash = ?, colorsig = ? WHERE id = ?",
                (sig[0], sig[1], media_id),
            )
            done += 1
            if done % 1000 == 0:
                con.commit()
                logger.info("  fingerprinted %d / %d", done, len(rows))
    con.commit()
    return done


# ---------------------------------------------------------------------------
# Stage 2: pixel verification
# ---------------------------------------------------------------------------

def comparison_thumb(path: Path) -> Image.Image:
    """Small, slightly blurred, contrast-normalised grayscale thumbnail."""
    with Image.open(path) as im:
        im.draft("L", (COMPARE_SIZE * 2, COMPARE_SIZE * 2))
        g = im.convert("L").resize((COMPARE_SIZE, COMPARE_SIZE), Image.BOX)
    g = g.filter(ImageFilter.GaussianBlur(1))   # tolerate sub-pixel resampling shifts
    stat = ImageStat.Stat(g)
    mu, sd = stat.mean[0], stat.stddev[0] or 1.0
    return g.point(lambda v: max(0, min(255, round(128 + (v - mu) / sd * Z_SCALE))))


def local_difference(a: Image.Image, b: Image.Image) -> float:
    """How far the most different 8px block stands out from the median block,
    in standard deviations of image brightness.

    Re-encoding, brightness/contrast edits and resampling spread a small
    difference over the whole picture, so the most different block is close
    to the median one. Added text, doodles, stickers or retouching concentrate
    the difference in a few blocks.
    """
    blocks = sorted(ImageChops.difference(a, b).resize((COMPARE_GRID, COMPARE_GRID), Image.BOX).tobytes())
    return (blocks[-1] - blocks[len(blocks) // 2]) / Z_SCALE


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def resolve_duplicates(con: sqlite3.Connection, data_dirs: list[Path], markers: dict[str, str]) -> int:
    """Recompute media.canonical_id.

    `markers` maps a moved duplicate's file_path to its canonical file_path
    (read from `.dup` files by the indexer). Returns the number of duplicates.
    """
    rows = con.execute(
        """
        SELECT m.id, m.file_path, m.phash, m.colorsig, m.width, m.height, m.num, m.canonical_id,
               p.date, p.tweet_id, p.category, p.author_name
        FROM media m JOIN posts p ON m.tweet_id = p.tweet_id
        WHERE m.phash IS NOT NULL AND m.phash != ''
        """
    ).fetchall()
    checked = {
        (r["a_id"], r["b_id"]): r["local_diff"]
        for r in con.execute("SELECT a_id, b_id, local_diff FROM media_pairs")
    }

    buckets: dict[tuple, list[sqlite3.Row]] = {}
    for r in rows:
        buckets.setdefault((r["category"], r["author_name"], r["width"], r["height"]), []).append(r)

    canon: dict[int, int] = {}
    verified = 0
    for items in buckets.values():
        if len(items) < 2:
            continue

        candidates = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if is_candidate(items[i], items[j]):
                    hd = (int(items[i]["phash"], 16) ^ int(items[j]["phash"], 16)).bit_count()
                    candidates.append((hd, i, j))
        if not candidates:
            continue
        candidates.sort()   # likeliest first, so transitive merges skip more checks

        parent = list(range(len(items)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        thumbs: dict[int, Image.Image | None] = {}

        def thumb(r):
            if r["id"] not in thumbs:
                found = locate(data_dirs, r["file_path"])
                try:
                    thumbs[r["id"]] = comparison_thumb(found[1]) if found else None
                except Exception as e:
                    logger.warning("compare failed %s: %s", r["file_path"], e)
                    thumbs[r["id"]] = None
            return thumbs[r["id"]]

        for _, i, j in candidates:
            if find(i) == find(j):
                continue
            a, b = items[i], items[j]
            key = (min(a["id"], b["id"]), max(a["id"], b["id"]))
            diff = checked.get(key)
            if diff is None:
                ta, tb = thumb(a), thumb(b)
                if ta is None or tb is None:
                    continue    # can't verify now (file moved/missing) — not a duplicate
                diff = checked[key] = local_difference(ta, tb)
                con.execute(
                    "INSERT OR REPLACE INTO media_pairs (a_id, b_id, local_diff) VALUES (?, ?, ?)",
                    (*key, diff),
                )
                verified += 1
                if verified % 1000 == 0:
                    con.commit()
                    logger.info("  verified %d pairs", verified)
            if diff <= MAX_LOCAL_DIFF:
                parent[find(j)] = find(i)

        clusters: dict[int, list[sqlite3.Row]] = {}
        for i, r in enumerate(items):
            clusters.setdefault(find(i), []).append(r)
        for members in clusters.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda r: (r["date"] or "", r["tweet_id"], r["num"] or 0, r["id"]))
            for r in members[1:]:
                canon[r["id"]] = members[0]["id"]

    # .dup markers are authoritative (the file is gone, so it can't be verified)
    if markers:
        ids = {r["file_path"]: r["id"] for r in con.execute("SELECT id, file_path FROM media")}
        for dup_path, canonical_path in markers.items():
            if dup_path in ids and canonical_path in ids and ids[dup_path] != ids[canonical_path]:
                canon[ids[dup_path]] = ids[canonical_path]

    # Flatten chains (a later backfill can make yesterday's canonical a duplicate)
    for k in list(canon):
        seen = {k}
        target = canon[k]
        while target in canon and target not in seen:
            seen.add(target)
            target = canon[target]
        canon[k] = target

    # Only touch rows we have evidence for: hashed rows and marker rows.
    # Rows with neither (e.g. data dir unmounted) keep their previous value.
    current = {r["id"]: r["canonical_id"] for r in rows}
    for r in con.execute("SELECT id, canonical_id FROM media WHERE canonical_id IS NOT NULL"):
        current.setdefault(r["id"], r["canonical_id"])
    evidence = {r["id"] for r in rows} | set(canon)

    changed = 0
    for media_id in evidence:
        new = canon.get(media_id)
        if current.get(media_id) != new:
            con.execute("UPDATE media SET canonical_id = ? WHERE id = ?", (new, media_id))
            changed += 1

    # Favorites on a duplicate carry over to the canonical copy
    con.execute(
        """
        INSERT OR IGNORE INTO favorite_media (media_id)
        SELECT m.canonical_id FROM favorite_media f
        JOIN media m ON m.id = f.media_id
        WHERE m.canonical_id IS NOT NULL
        """
    )
    con.commit()
    logger.info(
        "Duplicates: %d (verified %d new pairs, canonical_id changed on %d rows)",
        len(canon), verified, changed,
    )
    return len(canon)


# ---------------------------------------------------------------------------
# CLI: move duplicate files to .trash
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Move re-uploaded duplicate images to .trash")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--apply", action="store_true", help="Actually move files (default: dry-run)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    log_setup.configure(verbose=args.verbose)

    try:
        cfg = yaml.safe_load(open(args.config))
    except FileNotFoundError:
        logger.critical("Config file not found: %s", args.config)
        sys.exit(1)

    data_dirs = [Path(d).resolve() for d in cfg["data_dirs"]]
    con = db.init(cfg["db_path"])
    rows = con.execute(
        """
        SELECT m.file_path, c.file_path AS canonical_path
        FROM media m JOIN media c ON c.id = m.canonical_id
        JOIN posts p ON p.tweet_id = m.tweet_id
        ORDER BY p.date, m.file_path
        """
    ).fetchall()
    con.close()

    moved = already = no_canonical = 0
    for r in rows:
        dup = locate(data_dirs, r["file_path"])
        if dup is None:
            already += 1
            continue
        # Never remove a copy unless the one we keep is really there
        if locate(data_dirs, r["canonical_path"]) is None:
            logger.warning("canonical missing, keeping %s (canonical %s)", r["file_path"], r["canonical_path"])
            no_canonical += 1
            continue

        data_dir, src = dup
        dst = data_dir / TRASH_DIR / r["file_path"]
        if not args.apply:
            logger.info("[dry-run] %s  (same as %s)", r["file_path"], r["canonical_path"])
            moved += 1
            continue

        # Marker first: if the move fails the mapping is still correct
        src.with_name(src.name + MARKER_SUFFIX).write_text(r["canonical_path"] + "\n", encoding="utf-8")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)
        logger.debug("moved %s -> %s", src, dst)
        moved += 1

    verb = "moved" if args.apply else "would move"
    logger.info(
        "%s %d files to %s/ (already moved: %d, skipped because canonical missing: %d)",
        verb, moved, TRASH_DIR, already, no_canonical,
    )


if __name__ == "__main__":
    main()
