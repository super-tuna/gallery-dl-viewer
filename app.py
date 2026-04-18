"""
gallery-dl-viewer — FastAPI web server

Usage:
    uvicorn app:app --host 0.0.0.0 --port 8090
  or:
    python app.py
"""

import logging
import sqlite3
import sys
from pathlib import Path

import yaml
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import log_setup

log_setup.configure()
logger = logging.getLogger(__name__)

try:
    cfg = yaml.safe_load(open("config.yaml"))
except FileNotFoundError:
    logging.critical("config.yaml not found. Copy config.example.yaml to config.yaml.")
    sys.exit(1)

DB_PATH = cfg["db_path"]
DATA_DIRS = [Path(d).resolve() for d in cfg["data_dirs"]]

# Ensure schema is up to date (safe on existing DBs — all CREATE IF NOT EXISTS)
_con = db.init(DB_PATH)
_con.close()

logger.info("DB: %s", DB_PATH)
logger.info("Data dirs: %s", [str(d) for d in DATA_DIRS])

app = FastAPI(title="gallery-dl-viewer")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    db._configure(con)
    return con


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/")
async def gallery(
    request: Request,
    tags: str = Query(default=""),
    q: str = Query(default=""),
    from_date: str = Query(default=""),
    to_date: str = Query(default=""),
    order: str = Query(default="desc"),
    fav_only: bool = Query(default=False),
    fav_tags_only: bool = Query(default=False),
    categories: str = Query(default=""),
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    cat_list = [c.strip() for c in categories.split(",") if c.strip()]
    con = get_con()
    try:
        tag_list_norm = tag_list or None
        cat_list_norm = cat_list or None
        q_norm = q or None
        from_norm = from_date or None
        to_norm = to_date or None
        order_norm = "asc" if order == "asc" else "desc"

        items = db.get_gallery(
            con,
            tags=tag_list_norm,
            q=q_norm,
            from_date=from_norm,
            to_date=to_norm,
            order=order_norm,
            fav_only=fav_only,
            categories=cat_list_norm,
            offset=0,
            limit=24,
        )
        all_tags = db.get_all_tags(
            con,
            tags=tag_list_norm,
            q=q_norm,
            from_date=from_norm,
            to_date=to_norm,
            fav_tags_only=fav_tags_only,
            categories=cat_list_norm,
        )
        min_date, max_date = db.get_date_range(
            con, tags=tag_list_norm, q=q_norm, categories=cat_list_norm
        )
        fav_media_ids = db.get_favorite_media_ids(con)
        all_categories = db.get_all_categories(con)
        return templates.TemplateResponse(
            request=request,
            name="gallery.html",
            context={
                "items": [dict(i) for i in items],
                "all_tags": [dict(t) for t in all_tags],
                "all_categories": all_categories,
                "min_date": min_date or "",
                "max_date": max_date or "",
                "fav_media_ids": list(fav_media_ids),
                "filters": {
                    "tags": tags,
                    "q": q,
                    "from_date": from_date,
                    "to_date": to_date,
                    "order": order_norm,
                    "fav_only": fav_only,
                    "fav_tags_only": fav_tags_only,
                    "categories": categories,
                },
            },
        )
    finally:
        con.close()


@app.get("/post/{tweet_id}")
async def post_detail(request: Request, tweet_id: str):
    con = get_con()
    try:
        post, media, tags = db.get_post(con, tweet_id)
        if not post:
            return JSONResponse({"error": "not found"}, status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="post.html",
            context={
                "post": dict(post),
                "media": [dict(m) for m in media],
                "tags": tags,
            },
        )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# API (for infinite scroll)
# ---------------------------------------------------------------------------

@app.get("/api/gallery")
async def api_gallery(
    tags: str = Query(default=""),
    q: str = Query(default=""),
    from_date: str = Query(default=""),
    to_date: str = Query(default=""),
    order: str = Query(default="desc"),
    fav_only: bool = Query(default=False),
    categories: str = Query(default=""),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, le=100),
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    cat_list = [c.strip() for c in categories.split(",") if c.strip()]
    con = get_con()
    try:
        items = db.get_gallery(
            con,
            tags=tag_list or None,
            q=q or None,
            from_date=from_date or None,
            to_date=to_date or None,
            order="asc" if order == "asc" else "desc",
            fav_only=fav_only,
            categories=cat_list or None,
            offset=offset,
            limit=limit,
        )
        return JSONResponse([dict(i) for i in items])
    finally:
        con.close()


@app.post("/api/favorite/media/{media_id}")
async def toggle_fav_media(media_id: int):
    con = get_con()
    try:
        favorited = db.toggle_favorite_media(con, media_id)
        return JSONResponse({"favorited": favorited})
    finally:
        con.close()


@app.post("/api/favorite/tag/{tag}")
async def toggle_fav_tag(tag: str):
    con = get_con()
    try:
        favorited = db.toggle_favorite_tag(con, tag)
        return JSONResponse({"favorited": favorited})
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Media serving
# ---------------------------------------------------------------------------

@app.get("/media/{media_id}")
async def serve_media(media_id: int):
    con = get_con()
    try:
        file_path = db.get_media_path(con, media_id)
    finally:
        con.close()

    if not file_path:
        logger.warning("serve_media: media_id=%d not found in DB", media_id)
        return JSONResponse({"error": "not found"}, status_code=404)

    rel = Path(file_path)
    for d in DATA_DIRS:
        p = (d / rel).resolve()
        if p.is_relative_to(d) and p.exists():
            return FileResponse(p)

    logger.warning("serve_media: file missing on disk for media_id=%d path=%s", media_id, file_path)
    return JSONResponse({"error": "file missing"}, status_code=404)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=cfg.get("host", "0.0.0.0"), port=cfg.get("port", 8090), reload=False)
