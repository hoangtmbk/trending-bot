from __future__ import annotations
import json
import logging
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db.database import Database
from db.queries import get_items, get_item_by_id, get_score_history, enqueue_task

logger = logging.getLogger(__name__)


def create_app(db: Database, config: dict) -> FastAPI:
    app = FastAPI(title="TrendBot", description="Personal AI Trends Assistant")
    app.state.db = db
    app.state.config = config

    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    templates = Jinja2Templates(directory=str(templates_dir))

    # ── API Endpoints ──

    @app.get("/api/health")
    async def api_health():
        import os
        return {
            "ok": True,
            "version": os.environ.get("TRENDBOT_GIT_SHA", "dev"),
        }

    @app.get("/api/items")
    async def api_items(
        source: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = Query(default=30, le=100),
    ):
        items = get_items(db, source=source, status=status, since=since, limit=limit,
                         order_by="normalized_score DESC")
        for item in items:
            if item.get("raw_metrics"):
                item["raw_metrics"] = json.loads(item["raw_metrics"])
        return {"items": items, "count": len(items)}

    @app.get("/api/items/{item_id}")
    async def api_item_detail(item_id: int):
        item = get_item_by_id(db, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        if item.get("raw_metrics"):
            item["raw_metrics"] = json.loads(item["raw_metrics"])
        return item

    @app.get("/api/items/{item_id}/analysis")
    async def api_item_analysis(item_id: int):
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM item_analysis WHERE item_id=? ORDER BY created_at DESC",
                (item_id,),
            ).fetchall()
        analyses = []
        for row in rows:
            a = dict(row)
            if a.get("content"):
                a["content"] = json.loads(a["content"])
            analyses.append(a)
        return {"analyses": analyses}

    @app.get("/api/items/{item_id}/scores")
    async def api_item_scores(item_id: int):
        history = get_score_history(db, item_id)
        for h in history:
            if h.get("raw_metrics"):
                h["raw_metrics"] = json.loads(h["raw_metrics"])
        return {"scores": history}

    @app.post("/api/items/{item_id}/action")
    async def api_item_action(item_id: int, request: Request):
        body = await request.json()
        action = body.get("action")
        valid_actions = {"bookmarked", "dismissed", "deep_dive_requested", "feedback"}
        if action not in valid_actions:
            raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of: {valid_actions}")

        with db.connect() as conn:
            conn.execute(
                "INSERT INTO user_actions (item_id, action, payload, created_at) VALUES (?, ?, ?, datetime('now'))",
                (item_id, action, json.dumps(body.get("payload", {}))),
            )
            conn.commit()

        if action == "deep_dive_requested":
            enqueue_task(db, agent_type="deep_diver", payload={"item_id": item_id})

        return {"status": "ok", "action": action}

    @app.post("/api/research/deepdive")
    async def api_request_deepdive(request: Request):
        body = await request.json()
        item_id = body.get("item_id")
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id required")
        enqueue_task(db, agent_type="deep_diver", payload={"item_id": item_id})
        return {"status": "queued", "item_id": item_id}

    @app.get("/api/topics")
    async def api_topics():
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT t.*, COALESCE(ui.weight, 1.0) as weight, "
                "(SELECT COUNT(*) FROM item_topics WHERE topic_id = t.id) as item_count "
                "FROM topics t LEFT JOIN user_interests ui ON t.id = ui.topic_id "
                "WHERE t.is_active = 1 ORDER BY weight DESC"
            ).fetchall()
        return {"topics": [dict(r) for r in rows]}

    @app.post("/api/topics")
    async def api_create_topic(request: Request):
        body = await request.json()
        name = body.get("name", "").strip().lower()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        weight = body.get("weight", 2.0)
        with db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO topics (name, source, created_at) VALUES (?, 'user', datetime('now'))",
                (name,),
            )
            topic = conn.execute("SELECT id FROM topics WHERE name=?", (name,)).fetchone()
            if topic:
                conn.execute(
                    "INSERT OR REPLACE INTO user_interests (topic_id, weight, source, updated_at) "
                    "VALUES (?, ?, 'explicit', datetime('now'))",
                    (topic["id"], weight),
                )
            conn.commit()
        return {"status": "ok", "topic": name, "weight": weight}

    @app.get("/api/connections")
    async def api_connections(item_id: int | None = None):
        with db.connect() as conn:
            if item_id:
                rows = conn.execute(
                    "SELECT c.*, ia.title as title_a, ib.title as title_b "
                    "FROM item_connections c "
                    "JOIN items ia ON c.item_a_id = ia.id "
                    "JOIN items ib ON c.item_b_id = ib.id "
                    "WHERE c.item_a_id = ? OR c.item_b_id = ?",
                    (item_id, item_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT c.*, ia.title as title_a, ib.title as title_b "
                    "FROM item_connections c "
                    "JOIN items ia ON c.item_a_id = ia.id "
                    "JOIN items ib ON c.item_b_id = ib.id "
                    "ORDER BY c.created_at DESC LIMIT 50"
                ).fetchall()
        return {"connections": [dict(r) for r in rows]}

    @app.get("/api/digests")
    async def api_digests():
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM digests ORDER BY created_at DESC LIMIT 30"
            ).fetchall()
        digests = []
        for r in rows:
            d = dict(r)
            if d.get("item_ids"):
                d["item_ids"] = json.loads(d["item_ids"])
            digests.append(d)
        return {"digests": digests}

    # ── HTML Pages ──

    @app.get("/", response_class=HTMLResponse)
    async def page_home(request: Request):
        items = get_items(db, limit=30, order_by="normalized_score DESC")
        for item in items:
            if item.get("raw_metrics"):
                item["raw_metrics"] = json.loads(item["raw_metrics"])
        return templates.TemplateResponse(request, "index.html", {"items": items})

    @app.get("/item/{item_id}", response_class=HTMLResponse)
    async def page_item(request: Request, item_id: int):
        item = get_item_by_id(db, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        if item.get("raw_metrics"):
            item["raw_metrics"] = json.loads(item["raw_metrics"])

        with db.connect() as conn:
            analyses = [dict(r) for r in conn.execute(
                "SELECT * FROM item_analysis WHERE item_id=? ORDER BY created_at DESC", (item_id,)
            ).fetchall()]
            for a in analyses:
                if a.get("content"):
                    a["content"] = json.loads(a["content"])

        scores = get_score_history(db, item_id)
        return templates.TemplateResponse(request, "item.html", {
            "item": item, "analyses": analyses, "scores": scores,
        })

    @app.get("/topics", response_class=HTMLResponse)
    async def page_topics(request: Request):
        with db.connect() as conn:
            topics = [dict(r) for r in conn.execute(
                "SELECT t.*, COALESCE(ui.weight, 1.0) as weight, "
                "(SELECT COUNT(*) FROM item_topics WHERE topic_id = t.id) as item_count "
                "FROM topics t LEFT JOIN user_interests ui ON t.id = ui.topic_id "
                "WHERE t.is_active = 1 ORDER BY weight DESC"
            ).fetchall()]
        return templates.TemplateResponse(request, "topics.html", {"topics": topics})

    return app
