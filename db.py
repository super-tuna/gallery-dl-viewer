import logging
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    tweet_id    TEXT PRIMARY KEY,
    author_name TEXT,
    author_nick TEXT,
    content     TEXT,
    date        TEXT,
    category    TEXT,
    subcategory TEXT,
    source_query TEXT,
    lang        TEXT,
    favorite_count  INTEGER DEFAULT 0,
    retweet_count   INTEGER DEFAULT 0,
    reply_count     INTEGER DEFAULT 0,
    view_count      INTEGER DEFAULT 0,
    sensitive       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id    TEXT REFERENCES posts(tweet_id),
    file_path   TEXT UNIQUE,
    width       INTEGER,
    height      INTEGER,
    media_type  TEXT,
    num         INTEGER,
    count       INTEGER
);

CREATE TABLE IF NOT EXISTS tags (
    id  INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS post_tags (
    tweet_id TEXT REFERENCES posts(tweet_id),
    tag_id   INTEGER REFERENCES tags(id),
    PRIMARY KEY (tweet_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_date        ON posts(date);
CREATE INDEX IF NOT EXISTS idx_media_tweet_id    ON media(tweet_id);
CREATE INDEX IF NOT EXISTS idx_post_tags_tweet   ON post_tags(tweet_id);
CREATE INDEX IF NOT EXISTS idx_post_tags_tag     ON post_tags(tag_id);

CREATE TABLE IF NOT EXISTS favorite_media (
    media_id INTEGER PRIMARY KEY REFERENCES media(id)
);

CREATE TABLE IF NOT EXISTS favorite_tags (
    tag TEXT PRIMARY KEY
);
"""


def _configure(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.row_factory = sqlite3.Row


def init(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    _configure(con)
    con.executescript(SCHEMA)
    con.commit()
    logger.debug("DB initialised: %s (WAL mode)", db_path)
    return con


@contextmanager
def connect(db_path: str):
    con = sqlite3.connect(db_path)
    _configure(con)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def upsert_post(con: sqlite3.Connection, data: dict):
    author = data.get("author") or data.get("user") or {}
    con.execute(
        """
        INSERT OR REPLACE INTO posts
            (tweet_id, author_name, author_nick, content, date,
             category, subcategory, source_query, lang,
             favorite_count, retweet_count, reply_count, view_count, sensitive)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(data.get("tweet_id", "")),
            author.get("name", ""),
            author.get("nick", ""),
            data.get("content", ""),
            data.get("date", ""),
            data.get("category", ""),
            data.get("subcategory", ""),
            data.get("search", "") or author.get("name", ""),
            data.get("lang", ""),
            data.get("favorite_count", 0),
            data.get("retweet_count", 0),
            data.get("reply_count", 0),
            data.get("view_count", 0),
            1 if data.get("sensitive") else 0,
        ),
    )


def upsert_media(con: sqlite3.Connection, tweet_id: str, file_path: str, data: dict) -> bool:
    """Returns True if a new row was inserted, False if already existed."""
    cur = con.execute(
        """
        INSERT OR IGNORE INTO media
            (tweet_id, file_path, width, height, media_type, num, count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tweet_id,
            file_path,
            data.get("width", 0),
            data.get("height", 0),
            data.get("type", "photo"),
            data.get("num", 1),
            data.get("count", 1),
        ),
    )
    return cur.rowcount > 0


def upsert_tags(con: sqlite3.Connection, tweet_id: str, hashtags: list):
    for tag in hashtags:
        tag = tag.lower()
        con.execute("INSERT OR IGNORE INTO tags (tag) VALUES (?)", (tag,))
        row = con.execute("SELECT id FROM tags WHERE tag = ?", (tag,)).fetchone()
        con.execute(
            "INSERT OR IGNORE INTO post_tags (tweet_id, tag_id) VALUES (?, ?)",
            (tweet_id, row["id"]),
        )


def get_gallery(
    con: sqlite3.Connection,
    tags: list | None = None,
    q: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    order: str = "desc",
    fav_only: bool = False,
    offset: int = 0,
    limit: int = 24,
) -> list[sqlite3.Row]:
    conditions: list[str] = []
    params: list = []

    if fav_only:
        conditions.append("m.id IN (SELECT media_id FROM favorite_media)")

    if tags:
        ph = ",".join("?" * len(tags))
        conditions.append(f"""
            m.tweet_id IN (
                SELECT pt.tweet_id FROM post_tags pt
                JOIN tags t ON pt.tag_id = t.id
                WHERE t.tag IN ({ph})
                GROUP BY pt.tweet_id
                HAVING COUNT(DISTINCT t.tag) = {len(tags)}
            )
        """)
        params.extend(t.lower() for t in tags)

    if q:
        conditions.append("p.content LIKE ?")
        params.append(f"%{q}%")

    if from_date:
        conditions.append("p.date >= ?")
        params.append(from_date)

    if to_date:
        conditions.append("p.date <= ?")
        params.append(to_date + " 23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT m.id, m.file_path, m.media_type, m.tweet_id,
               m.width, m.height, m.num,
               p.author_name, p.author_nick, p.date, p.content
        FROM media m
        JOIN posts p ON m.tweet_id = p.tweet_id
        {where}
        ORDER BY p.date {"DESC" if order == "desc" else "ASC"}, m.num ASC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    return con.execute(sql, params).fetchall()


def get_post(con: sqlite3.Connection, tweet_id: str):
    post = con.execute("SELECT * FROM posts WHERE tweet_id = ?", (tweet_id,)).fetchone()
    media = con.execute(
        "SELECT * FROM media WHERE tweet_id = ? ORDER BY num", (tweet_id,)
    ).fetchall()
    tags = con.execute(
        """
        SELECT t.tag FROM tags t
        JOIN post_tags pt ON t.id = pt.tag_id
        WHERE pt.tweet_id = ?
        ORDER BY t.tag
        """,
        (tweet_id,),
    ).fetchall()
    return post, media, [r["tag"] for r in tags]


def get_all_tags(
    con: sqlite3.Connection,
    tags: list | None = None,
    q: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    fav_tags_only: bool = False,
    limit: int = 200,
) -> list[sqlite3.Row]:
    conditions: list[str] = []
    params: list = []

    if fav_tags_only:
        conditions.append("ft.tag IS NOT NULL")

    if tags:
        ph = ",".join("?" * len(tags))
        conditions.append(f"""
            pt.tweet_id IN (
                SELECT pt2.tweet_id FROM post_tags pt2
                JOIN tags t2 ON pt2.tag_id = t2.id
                WHERE t2.tag IN ({ph})
                GROUP BY pt2.tweet_id
                HAVING COUNT(DISTINCT t2.tag) = {len(tags)}
            )
        """)
        params.extend(t.lower() for t in tags)

    if q:
        conditions.append("p.content LIKE ?")
        params.append(f"%{q}%")

    if from_date:
        conditions.append("p.date >= ?")
        params.append(from_date)

    if to_date:
        conditions.append("p.date <= ?")
        params.append(to_date + " 23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT t.tag, COUNT(DISTINCT pt.tweet_id) as cnt,
               CASE WHEN ft.tag IS NOT NULL THEN 1 ELSE 0 END as is_fav
        FROM tags t
        JOIN post_tags pt ON t.id = pt.tag_id
        JOIN posts p ON pt.tweet_id = p.tweet_id
        LEFT JOIN favorite_tags ft ON t.tag = ft.tag
        {where}
        GROUP BY t.tag
        ORDER BY cnt DESC
        LIMIT ?
    """
    params.append(limit)
    return con.execute(sql, params).fetchall()


def get_date_range(
    con: sqlite3.Connection,
    tags: list | None = None,
    q: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (min_date, max_date) for posts matching tags and q (YYYY-MM-DD)."""
    conditions: list[str] = []
    params: list = []

    if tags:
        ph = ",".join("?" * len(tags))
        conditions.append(f"""
            p.tweet_id IN (
                SELECT pt.tweet_id FROM post_tags pt
                JOIN tags t ON pt.tag_id = t.id
                WHERE t.tag IN ({ph})
                GROUP BY pt.tweet_id
                HAVING COUNT(DISTINCT t.tag) = {len(tags)}
            )
        """)
        params.extend(t.lower() for t in tags)

    if q:
        conditions.append("p.content LIKE ?")
        params.append(f"%{q}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"SELECT MIN(p.date) as min_d, MAX(p.date) as max_d FROM posts p {where}"
    row = con.execute(sql, params).fetchone()
    if not row or not row["min_d"]:
        return None, None
    return row["min_d"][:10], row["max_d"][:10]


def get_media_path(con: sqlite3.Connection, media_id: int) -> str | None:
    row = con.execute("SELECT file_path FROM media WHERE id = ?", (media_id,)).fetchone()
    return row["file_path"] if row else None


def get_favorite_media_ids(con: sqlite3.Connection) -> set[int]:
    rows = con.execute("SELECT media_id FROM favorite_media").fetchall()
    return {r["media_id"] for r in rows}


def toggle_favorite_media(con: sqlite3.Connection, media_id: int) -> bool:
    if con.execute("SELECT 1 FROM favorite_media WHERE media_id = ?", (media_id,)).fetchone():
        con.execute("DELETE FROM favorite_media WHERE media_id = ?", (media_id,))
        con.commit()
        return False
    con.execute("INSERT INTO favorite_media (media_id) VALUES (?)", (media_id,))
    con.commit()
    return True


def toggle_favorite_tag(con: sqlite3.Connection, tag: str) -> bool:
    tag = tag.lower()
    if con.execute("SELECT 1 FROM favorite_tags WHERE tag = ?", (tag,)).fetchone():
        con.execute("DELETE FROM favorite_tags WHERE tag = ?", (tag,))
        con.commit()
        return False
    con.execute("INSERT INTO favorite_tags (tag) VALUES (?)", (tag,))
    con.commit()
    return True
