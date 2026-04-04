"""
Generate demo fixture data for gallery-dl-viewer screenshots.

Creates placeholder images (colored rectangles) + gallery-dl-style sidecar
JSONs in demo/data/, then writes demo_config.yaml.

Usage:
    pip install Pillow
    python tools/generate_demo.py
    python indexer.py --config demo_config.yaml
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "demo" / "data"
DB_PATH = ROOT / "demo" / "demo.db"
CONFIG_PATH = ROOT / "demo_config.yaml"

COLORS = [
    "#B5C7E7", "#C7E7B5", "#E7C7B5", "#D5B5E7", "#E7E7B5",
    "#B5E7D5", "#E7B5C7", "#B5D5E7", "#E7D5B5", "#C7B5E7",
    "#A8D5A2", "#F4C7A8", "#A8C7F4", "#F4A8C7", "#C7F4A8",
    "#D4A5A5", "#A5D4C7", "#C7A5D4", "#D4C7A5", "#A5A5D4",
]

AUTHORS = [
    {"name": "Alice Chen",    "nick": "alice_art"},
    {"name": "Bob Smith",     "nick": "bob_draws"},
    {"name": "Carol Johnson", "nick": "carol_creates"},
    {"name": "David Park",    "nick": "david_pixels"},
    {"name": "Emma Wilson",   "nick": "emma_sketches"},
]

HASHTAGS_POOL = [
    "illustration", "digitalart", "sketch", "anime", "portrait",
    "landscape", "characterdesign", "fanart", "procreate", "oc",
    "art", "drawing", "pixelart", "conceptart", "inktober",
]

CONTENTS = [
    "Working on a new illustration today! Really happy with how the colors turned out.",
    "Quick sketch before bed. Sometimes the simple ones are the best.",
    "Finally finished this piece after three days of work. Worth it!",
    "Experimenting with a new brushset. What do you think?",
    "Commission open! DMs are welcome.",
    "Practice makes perfect. Another figure study done.",
    "Can't believe this got so much love, thank you all!",
    "Redrawing an old piece. The improvement is real.",
    "Inspired by the cherry blossoms outside my window.",
    "WIP — still figuring out the lighting on this one.",
    "Late night drawing session. Coffee is mandatory.",
    "This character has been living rent-free in my head all week.",
    "Background practice. I always neglect backgrounds.",
    "First time trying gouache digitally. Interesting results.",
    "Soft palette study for today.",
    "Monthly art summary! February was productive.",
    "Trying a different approach to shading here.",
    "Rough draft but sharing anyway.",
    "Color theory exploration. Purple and gold are such a good combo.",
    "Character redesign — old vs new.",
]

SIZES = [
    (1024, 768),   # landscape
    (768, 1024),   # portrait
    (1024, 1024),  # square
    (1280, 720),   # widescreen
    (800, 1200),   # tall portrait
]

rng = random.Random(42)


def make_image(path: Path, width: int, height: int, label: str, color: str) -> None:
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)

    # Grid lines for a "placeholder" look
    step = min(width, height) // 8
    line_color = tuple(max(0, c - 40) for c in img.getpixel((0, 0)))
    for x in range(0, width, step):
        draw.line([(x, 0), (x, height)], fill=line_color, width=1)
    for y in range(0, height, step):
        draw.line([(0, y), (width, y)], fill=line_color, width=1)

    # Diagonal cross
    draw.line([(0, 0), (width, height)], fill=line_color, width=2)
    draw.line([(width, 0), (0, height)], fill=line_color, width=2)

    # Label text (centered)
    text = f"{label}\n{width}×{height}"
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (width - tw) // 2
    ty = (height - th) // 2

    # Text shadow
    draw.text((tx + 2, ty + 2), text, fill=(0, 0, 0, 128), font=font)
    draw.text((tx, ty), text, fill=(255, 255, 255), font=font)

    img.save(path, "JPEG", quality=85)


def make_sidecar(
    path: Path,
    tweet_id: int,
    author: dict,
    content: str,
    hashtags: list[str],
    date: str,
    width: int,
    height: int,
    num: int,
    count: int,
) -> None:
    data = {
        "tweet_id": tweet_id,
        "author": author,
        "user": author,
        "content": content + " " + " ".join(f"#{t}" for t in hashtags),
        "hashtags": hashtags,
        "date": date,
        "category": "twitter",
        "subcategory": "tweet",
        "lang": "en",
        "width": width,
        "height": height,
        "type": "photo",
        "num": num,
        "count": count,
        "favorite_count": rng.randint(10, 5000),
        "retweet_count": rng.randint(2, 1000),
        "reply_count": rng.randint(1, 200),
        "view_count": rng.randint(500, 100000),
        "sensitive": False,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def generate() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    base_date = datetime(2024, 1, 1)
    tweet_id = 1800000000000000000

    posts = []
    # 20 single-image posts + 5 multi-image posts (2 images each) = 30 files total
    for i in range(20):
        posts.append({"count": 1, "images": 1})
    for i in range(5):
        posts.append({"count": 2, "images": 2})

    rng.shuffle(posts)

    file_count = 0
    for post_idx, post in enumerate(posts):
        author = rng.choice(AUTHORS)
        content = CONTENTS[post_idx % len(CONTENTS)]
        hashtags = rng.sample(HASHTAGS_POOL, rng.randint(2, 5))
        date = (base_date + timedelta(days=post_idx * 5 + rng.randint(0, 4))).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        count = post["count"]

        for num in range(1, count + 1):
            width, height = rng.choice(SIZES)
            color = rng.choice(COLORS)
            label = f"Post {post_idx + 1}"
            if count > 1:
                label += f" [{num}/{count}]"

            fname = f"{author['nick']}_{tweet_id}_{num}.jpg"
            img_path = DATA_DIR / fname
            json_path = DATA_DIR / f"{fname}.json"

            make_image(img_path, width, height, label, color)
            make_sidecar(
                json_path, tweet_id, author, content, hashtags, date,
                width, height, num, count,
            )
            file_count += 1

        tweet_id += rng.randint(1_000_000, 5_000_000)

    print(f"Generated {file_count} images in {DATA_DIR}")

    config_content = f"""\
# Demo config for screenshot generation — do not commit
data_dirs:
  - {DATA_DIR}
db_path: {DB_PATH}
host: 0.0.0.0
port: 8091
"""
    CONFIG_PATH.write_text(config_content, encoding="utf-8")
    print(f"Config written to {CONFIG_PATH}")
    print()
    print("Next steps:")
    print(f"  python indexer.py --config {CONFIG_PATH}")
    print()
    print("  # app.py reads config.yaml by default, so temporarily swap configs:")
    print(f"  cp config.yaml config.yaml.bak  # save your real config")
    print(f"  cp {CONFIG_PATH} config.yaml")
    print("  python app.py                    # open http://localhost:8091")
    print("  cp config.yaml.bak config.yaml   # restore after screenshots")


if __name__ == "__main__":
    generate()
