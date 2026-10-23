"""HTTP API ПРУФ: приём и анализ, очередь кейсов, карточка, таймлайн пруфа, экспорт, лента для банков.

Ответы в едином конверте: {"success": bool, "data": ..., "error": str | null, "meta": {...}}.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from pruf.api.security import RateLimiter, require_analyst, require_bank, sniff_upload
from pruf.config import ROOT, Settings, load_settings
from pruf.export import build_evidence_package
from pruf.graph.builder import CaseGraph, artifact_timeline
from pruf.normalize.audio import whisper_available
from pruf.normalize.ocr import ocr_available
from pruf.normalize.requisites import extract_requisites
from pruf.pipeline import Pruf, Submission, Upload
from pruf.registry.forensics import ela_heatmap_png
from pruf.registry.hashing import open_image
from pruf.storage.db import CASE_STATUSES

log = logging.getLogger(__name__)
MAX_FILES = 6
MAX_TEXT = 20_000
WEB_DIR = ROOT / "web"


def ok(data: Any, **meta: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "error": None, "meta": meta or None}


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    channel: str | None = Field(default=None, max_length=200)
    posted_at: str | None = Field(default=None, max_length=40)
    store: bool = True


class RequisiteCheck(BaseModel):
    value: str = Field(min_length=5, max_length=64)


def capabilities(p: Pruf) -> dict[str, Any]:
    """Что реально работает: аналитик видит, если OCR, Whisper, ML или LLM недоступны."""
    return {"ocr": ocr_available(), "whisper": whisper_available(), "ml": p.detector.has_classifier,
            "llm": p.detector.llm_state(), "link_resolution": p.settings.resolve_links}


class CaseUpdate(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=2000)


def create_app(settings: Settings | None = None, pruf: Pruf | None = None) -> FastAPI:
    settings = settings or load_settings()
    limiter = RateLimiter(settings.rate_limit_per_minute)
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if int(os.environ.get("WEB_CONCURRENCY", "1")) > 1:
            # Индексы ПРУФ и граф живут в памяти процесса: несколько воркеров не увидят приём друг друга.
            raise RuntimeError("ПРУФ MVP работает в одном процессе: уберите --workers / WEB_CONCURRENCY")
        state["pruf"] = pruf or Pruf(settings)
        state["graph"] = CaseGraph(state["pruf"].db)
        if settings.dev_mode:
            log.warning("PRUF_DEV_MODE=1: токены не обязательны, не используйте в проде")
        yield
        state["pruf"].db.close()

    app = FastAPI(title="ПРУФ API", version="0.1.0", lifespan=lifespan)
    max_body = MAX_FILES * settings.max_upload_bytes + 256 * 1024

    @app.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > max_body):
            return JSONResponse({"success": False, "data": None, "error": "Запрос слишком большой", "meta": None}, status_code=413)
        if request.method in ("POST", "PUT", "PATCH") and length is None and \
                request.headers.get("transfer-encoding", "").lower() == "chunked":
            return JSONResponse({"success": False, "data": None, "error": "Нужен Content-Length", "meta": None}, status_code=411)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'")
        return response

    def analyst(request: Request) -> str:
        return require_analyst(request, settings, limiter)

    def bank(request: Request) -> str:
        return require_bank(request, settings, limiter)

    def core() -> Pruf:
        return state["pruf"]

    def graph() -> CaseGraph:
        g: CaseGraph = state["graph"]
        g.ensure(state["pruf"].version)
        return g

    @app.exception_handler(HTTPException)
    async def http_error(_req: Request, exc: HTTPException):
        return JSONResponse({"success": False, "data": None, "error": exc.detail, "meta": None}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_req: Request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()]
        return JSONResponse({"success": False, "data": None, "error": "Некорректные поля: " + ", ".join(fields), "meta": None},
                            status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_req: Request, exc: Exception):
        log.exception("необработанная ошибка: %s", exc)
        return JSONResponse({"success": False, "data": None, "error": "Внутренняя ошибка", "meta": None}, status_code=500)

    # ---------- приём ----------
    @app.post("/api/v1/analyze/text")
    def analyze_text(body: TextIn, actor: str = Depends(analyst)):
        p = core()
        if not body.store:
            return ok(p.analyze_only(body.text))
        return ok(p.ingest(Submission(text=body.text, channel=body.channel, posted_at=body.posted_at, source="api")))

    @app.post("/api/v1/analyze")
    def analyze(
        text: str | None = Form(default=None, max_length=MAX_TEXT),
        channel: str | None = Form(default=None, max_length=200),
        posted_at: str | None = Form(default=None, max_length=40),
        transcript: str | None = Form(default=None, max_length=MAX_TEXT),
        files: list[UploadFile] = File(default=[]),
        actor: str = Depends(analyst),
    ):
        if len(files) > MAX_FILES:
            raise HTTPException(status_code=413, detail=f"Не больше {MAX_FILES} файлов")
        uploads = []
        for f in files:
            data = f.file.read(settings.max_upload_bytes + 1)
            if len(data) > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Файл слишком большой")
            kind, ext = sniff_upload(data, f.filename, f.content_type)
            uploads.append(Upload(data=data, kind=kind, ext=ext))
        if not text and not uploads and not transcript:
            raise HTTPException(status_code=400, detail="Нужен текст, файл или расшифровка")
        try:
            result = core().ingest(Submission(text=text, uploads=tuple(uploads), transcript=transcript,
                                              channel=channel, posted_at=posted_at, source="dashboard"))
        except Image.DecompressionBombError as exc:
            raise HTTPException(status_code=413, detail="Изображение слишком большое") from exc
        except (UnidentifiedImageError, ValueError, OSError) as exc:  # OSError: обрезанный или битый файл
            log.warning("не удалось обработать файл: %s", exc)
            raise HTTPException(status_code=422, detail="Не удалось прочитать файл") from exc
        return ok(result)

    # ---------- кейсы ----------
    @app.get("/api/v1/cases")
    def list_cases(level: str | None = Query(default=None, pattern="^(medium|high)$"),
                   track: str | None = Query(default=None, pattern="^(lottery|casino|pyramid)$"),
                   status: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=500),
                   offset: int = Query(default=0, ge=0), actor: str = Depends(analyst)):
        statuses = core().db.case_statuses()
        items = []
        for c in graph().cases():
            if level and c.level != level:
                continue
            if track and track not in c.tracks:
                continue
            st = statuses.get(c.key, {}).get("status", "new")
            if status and st != status:
                continue
            items.append({**c.to_dict(), "status": st})
        return ok(items[offset:offset + limit], total=len(items), limit=limit, offset=offset)

    @app.get("/api/v1/cases/{key}")
    def get_case(key: str, actor: str = Depends(analyst)):
        g = graph()
        case = g.case(key)
        if not case:
            raise HTTPException(status_code=404, detail="Кейс не найден")
        p = core()
        posts = []
        for pid in case.post_ids:
            post = p.db.get_post(pid)
            if not post:
                continue
            post.pop("label", None)
            post["artifacts"] = p.db.artifacts_for_post(pid)
            post["requisites"] = p.db.requisites_for_post(pid)
            post["links"] = p.db.links_for_post(pid)
            posts.append(post)
        status = p.db.case_statuses().get(key, {"status": "new", "note": None})
        return ok({"case": case.to_dict(), "status": status, "posts": posts, "graph": g.subgraph(case.post_ids),
                   "families": g.families(case.post_ids)})

    @app.patch("/api/v1/cases/{key}")
    def update_case(key: str, body: CaseUpdate, actor: str = Depends(analyst)):
        if body.status not in CASE_STATUSES:
            raise HTTPException(status_code=400, detail="Статус: " + ", ".join(CASE_STATUSES))
        if not graph().case(key):
            raise HTTPException(status_code=404, detail="Кейс не найден")
        core().db.set_case_status(key, body.status, body.note, actor)
        core().db.audit(actor, "case_status", f"{key}:{body.status}")
        return ok({"key": key, "status": body.status})

    @app.get("/api/v1/cases/{key}/export")
    def export_case(key: str, actor: str = Depends(analyst)):
        g = graph()
        case = g.case(key)
        if not case:
            raise HTTPException(status_code=404, detail="Кейс не найден")
        p = core()
        data, digest = build_evidence_package(p.db, p.blobs, g, case, actor)
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="pruf_{key}.zip"', "X-Manifest-SHA256": digest})

    # ---------- посты и пруфы ----------
    @app.get("/api/v1/posts/{post_id}")
    def get_post(post_id: int, actor: str = Depends(analyst)):
        p = core()
        post = p.db.get_post(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Пост не найден")
        post.pop("label", None)
        post["artifacts"] = p.db.artifacts_for_post(post_id)
        post["case"] = graph().case_for_post(post_id)
        return ok(post)

    @app.get("/api/v1/posts/{post_id}/related")
    def related(post_id: int, actor: str = Depends(analyst)):
        ids = graph().related_posts(post_id)
        rows = [{k: v for k, v in r.items() if k != "label"} for r in core().db.get_posts(ids[:200])]
        return ok(rows, total=len(ids))

    @app.get("/api/v1/artifacts/{artifact_id}/timeline")
    def timeline(artifact_id: int, actor: str = Depends(analyst)):
        if not core().db.get_artifact(artifact_id):
            raise HTTPException(status_code=404, detail="Артефакт не найден")
        data = artifact_timeline(core().db, artifact_id)
        for item in data["items"]:
            item["post"].pop("label", None)
        return ok(data)

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: int, actor: str = Depends(analyst)):
        art = core().db.get_artifact(artifact_id)
        if not art:
            raise HTTPException(status_code=404, detail="Артефакт не найден")
        return ok(art)

    def _artifact_bytes(artifact_id: int) -> tuple[bytes, str]:
        art = core().db.get_artifact(artifact_id)
        if not art or art["kind"] not in ("image", "audio") or not art["ext"]:
            raise HTTPException(status_code=404, detail="Файл не найден")
        data = core().blobs.get(art["sha256"], art["ext"])
        if data is None:
            raise HTTPException(status_code=404, detail="Файл не найден")
        return data, art["ext"]

    @app.get("/api/v1/artifacts/{artifact_id}/file")
    def artifact_file(artifact_id: int, actor: str = Depends(analyst)):
        data, ext = _artifact_bytes(artifact_id)
        media = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "ogg": "audio/ogg",
                 "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav"}.get(ext, "application/octet-stream")
        return Response(data, media_type=media, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})

    @app.get("/api/v1/artifacts/{artifact_id}/ela")
    def artifact_ela(artifact_id: int, actor: str = Depends(analyst)):
        data, ext = _artifact_bytes(artifact_id)
        if ext not in ("jpg", "png", "webp"):
            raise HTTPException(status_code=400, detail="ELA только для изображений")
        return Response(ela_heatmap_png(open_image(data)), media_type="image/png")

    @app.get("/api/v1/stats")
    def stats(actor: str = Depends(analyst)):
        p = core()
        g = graph()
        return ok({"posts": p.db.count_posts(), "levels": p.db.level_counts(), "cases": len(g.cases()),
                   "images_indexed": len(p.registry.images), "texts_indexed": len(p.registry.texts),
                   "capabilities": capabilities(p)})

    # ---------- банки ----------
    @app.get("/api/v1/bank/requisites")
    def bank_feed(since: str | None = Query(default=None, max_length=40),
                  min_level: str = Query(default="medium", pattern="^(medium|high)$"),
                  limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0),
                  actor: str = Depends(bank)):
        rows = core().db.requisite_feed(since, min_level, limit, offset)
        g = graph()
        feed = []
        for r in rows:
            post_ids = core().db.posts_with_requisite(r["key"])
            cases = sorted({c for c in (g.case_for_post(pid) for pid in post_ids) if c})
            feed.append({"id": r["id"], "type": r["kind"], "value": r["display"], "max_score": r["max_score"], "posts": r["posts"],
                         "tracks": sorted(set((r["tracks"] or "").split(",")) - {""}), "cases": cases,
                         "first_seen": r["first_seen"], "last_seen": r["last_seen"],
                         "note": "Найдены признаки использования реквизита в схемах; не является основанием для блокировки без проверки"})
        core().db.audit(actor, "bank_feed", f"{len(feed)} rows")
        return ok(feed, limit=limit, offset=offset)

    @app.post("/api/v1/bank/check")
    def bank_check(body: RequisiteCheck, actor: str = Depends(bank)):
        """Банк проверяет свой реквизит (номер карты, телефон, IBAN) по реестру. Значение не сохраняется."""
        reqs = extract_requisites(body.value, core().settings.effective_hmac_key())
        if not reqs:
            raise HTTPException(status_code=400, detail="Не распознан реквизит: карта, телефон +7, IBAN KZ или ссылка Kaspi")
        found = core().db.lookup_requisite(reqs[0].key)
        core().db.audit(actor, "bank_check", reqs[0].kind)
        if not found:
            return ok({"found": False, "type": reqs[0].kind})
        return ok({"found": True, "type": found["kind"], "value": found["display"], "posts": found["posts"],
                   "max_score": found["max_score"], "tracks": sorted(set((found["tracks"] or "").split(",")) - {""}),
                   "first_seen": found["first_seen"],
                   "note": "Найдены признаки использования реквизита в схемах; требуется проверка банком"})

    @app.get("/api/v1/health")
    def health():
        return ok({"status": "ok"})

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(Path(WEB_DIR) / "index.html")

    return app
