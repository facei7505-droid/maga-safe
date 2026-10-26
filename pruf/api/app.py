"""HTTP API ПРУФ: приём и анализ, очередь кейсов, карточка, таймлайн пруфа, экспорт, лента для банков.

Ответы в едином конверте: {"success": bool, "data": ..., "error": str | null, "meta": {...}}.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
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
from pydantic import BaseModel, Field, field_validator

from pruf.analytics import overview
from pruf.api.security import RateLimiter, require_analyst, require_bank, require_extension, sniff_upload
from pruf.bot.telegram import BotLogic, HttpTelegramApi
from pruf.config import ROOT, Settings, load_settings
from pruf.export import build_evidence_package
from pruf.graph.builder import CaseGraph, artifact_timeline
from pruf.inspect import REPORT_PLATFORMS, Inspector
from pruf.lists import apply_case_decision, case_money_keys, export_ref, list_info, mask, to_csv
from pruf.normalize.audio import transcribe, whisper_available
from pruf.normalize.ocr import ocr_available
from pruf.normalize.requisites import extract_requisites
from pruf.pipeline import Pruf, Submission, Upload
from pruf.registry.forensics import ela_heatmap_png
from pruf.registry.hashing import open_image
from pruf.storage.db import CASE_STATUSES

log = logging.getLogger(__name__)
MAX_FILES = 6
MAX_TEXT = 20_000
MIN_WEBHOOK_SECRET = 32
WEBHOOK_MAX_BODY = 1024 * 1024  # update Telegram меньше 1 МБ, файлы приходят ссылками
BOT_WORKERS = 2
BOT_MAX_PENDING = 50
WEB_DIR = ROOT / "web"


JSON_MAX_BODY = 256 * 1024
CSV_MAX_ROWS = 20_000

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
    return {"ocr": p.settings.ocr_enabled and ocr_available(), "ocr_off": not p.settings.ocr_enabled, "whisper": whisper_available(), "ml": p.detector.has_classifier,
            "llm": p.detector.llm_state(), "link_resolution": p.settings.resolve_links}


class InspectIn(BaseModel):
    """Только извлечённое из поста: реквизиты, ссылки, хэш текста, номера признаков. Без текста."""
    requisites: list[str] = Field(default_factory=list, max_length=10)
    links: list[str] = Field(default_factory=list, max_length=20)
    text_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    cues: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("requisites", "cues")
    @classmethod
    def _short(cls, items: list[str]) -> list[str]:
        if any(len(i) > 64 for i in items):
            raise ValueError("слишком длинное значение")
        return items

    @field_validator("links")
    @classmethod
    def _url(cls, items: list[str]) -> list[str]:
        if any(len(i) > 2048 for i in items):
            raise ValueError("слишком длинная ссылка")
        return items


REPORTS_PER_MINUTE_PER_IP = 5


class ReportIn(InspectIn):
    """Жалоба «Сообщить в ПРУФ»: то же извлечённое, что для проверки, плюс площадка и случайный id установки."""
    text_hash: str = Field(pattern="^[0-9a-f]{64}$")
    platform: str = Field(default="other", max_length=16)
    install_id: str = Field(min_length=8, max_length=64, pattern="^[A-Za-z0-9-]+$")

    @field_validator("platform")
    @classmethod
    def _platform(cls, value: str) -> str:
        return value if value in REPORT_PLATFORMS else "other"


class CaseUpdate(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=2000)


def create_app(settings: Settings | None = None, pruf: Pruf | None = None) -> FastAPI:
    settings = settings or load_settings()
    limiter = RateLimiter(settings.rate_limit_per_minute)
    report_limiter = RateLimiter(REPORTS_PER_MINUTE_PER_IP)  # токен расширения общий: жалобы ограничиваем по IP
    state: dict[str, Any] = {}
    bot_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if int(os.environ.get("WEB_CONCURRENCY", "1")) > 1:
            # Индексы ПРУФ и граф живут в памяти процесса: несколько воркеров не увидят приём друг друга.
            raise RuntimeError("ПРУФ MVP работает в одном процессе: уберите --workers / WEB_CONCURRENCY")
        state["pruf"] = pruf or Pruf(settings)
        state["graph"] = CaseGraph(state["pruf"].db)
        state["inspector"] = Inspector(state["pruf"].db, state["pruf"].settings.effective_hmac_key())
        if settings.telegram_token:
            if len(settings.telegram_secret) < MIN_WEBHOOK_SECRET or not settings.telegram_secret.replace("-", "").replace("_", "").isalnum():
                log.warning("вебхук бота выключен: задайте PRUF_TELEGRAM_SECRET из %d+ символов [A-Za-z0-9_-]", MIN_WEBHOOK_SECRET)
            else:
                logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx пишет URL с токеном бота на INFO
                state["bot"] = BotLogic(state["pruf"], HttpTelegramApi(settings.telegram_token), settings.max_upload_bytes)
                # Обработка вне запроса: OCR и Whisper не занимают пул потоков API, Telegram сразу получает 200.
                state["bot_pool"] = ThreadPoolExecutor(max_workers=BOT_WORKERS, thread_name_prefix="tg")
                state["bot_pending"] = 0
                state["bot_seen"] = deque(maxlen=2000)
        if settings.dev_mode:
            log.warning("PRUF_DEV_MODE=1: токены не обязательны, не используйте в проде")
        yield
        if "bot_pool" in state:
            state["bot_pool"].shutdown(wait=True)
        state["pruf"].db.close()

    app = FastAPI(title="ПРУФ API", version="0.1.0", lifespan=lifespan)
    max_body = MAX_FILES * settings.max_upload_bytes + 256 * 1024

    @app.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length")
        # Тело читается и разбирается до проверки токена, поэтому большие тела принимаем только там,
        # где они нужны (приём файлов); JSON-маршрутам хватает 256 КБ.
        limit = {"/api/v1/analyze": max_body, "/api/v1/telegram/webhook": WEBHOOK_MAX_BODY}.get(request.url.path, JSON_MAX_BODY)
        if length is not None and (not length.isdigit() or int(length) > limit):
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
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    def analyst(request: Request) -> str:
        return require_analyst(request, settings, limiter)

    def bank(request: Request) -> str:
        return require_bank(request, settings, limiter)

    def extension(request: Request) -> str:
        return require_extension(request, settings, limiter)

    def inspector() -> Inspector:
        ins: Inspector = state["inspector"]
        ins.refresh(state["pruf"].version)
        return ins

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
        store: str | None = Form(default=None, max_length=5),  # строка: у Form(bool) отсутствие поля = False
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
            if (store or "true").lower() not in ("0", "false", "off", "no"):
                result = core().ingest(Submission(text=text, uploads=tuple(uploads), transcript=transcript,
                                                  channel=channel, posted_at=posted_at, source="dashboard"))
            else:  # проверка без сохранения: файл не попадает в реестр
                audio = next((u for u in uploads if u.kind == "audio"), None)
                if audio and not transcript:
                    transcript = transcribe(audio.data, "." + audio.ext)
                result = core().check(text, images=tuple(u.data for u in uploads if u.kind == "image"),
                                      transcript=transcript)
                if audio and not transcript:
                    # Без этого голосовое молча выпадало, а ответ выглядел как «низкий риск»
                    analysis = result["analysis"]
                    analysis["degraded"] = [*analysis.get("degraded", []), {
                        "component": "whisper", "reason": "Голосовое не расшифровано: проверены только текст и изображения"}]
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
                   "families": g.families(case.post_ids), "network": g.case_network(key),
                   "money_requisites": len(case_money_keys(p.db, case.post_ids))})

    @app.get("/api/v1/networks")
    def list_networks(limit: int = Query(20, ge=1, le=100), actor: str = Depends(analyst)):
        """Сети каналов с общими реквизитами и ключевой реквизит каждой: что заблокировать в первую очередь."""
        items = graph().networks()
        return ok(items[:limit], total=len(items), limit=limit)

    @app.patch("/api/v1/cases/{key}")
    def update_case(key: str, body: CaseUpdate, actor: str = Depends(analyst)):
        if body.status not in CASE_STATUSES:
            raise HTTPException(status_code=400, detail="Статус: " + ", ".join(CASE_STATUSES))
        case = graph().case(key)
        if not case:
            raise HTTPException(status_code=404, detail="Кейс не найден")
        core().db.set_case_status(key, body.status, body.note, actor)
        core().db.audit(actor, "case_status", f"{key}:{body.status}")
        listed = apply_case_decision(core().db, key, case.post_ids, body.status, actor, (c.key for c in graph().cases()))
        return ok({"key": key, "status": body.status, "requisites_listed": listed})

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

    @app.get("/api/v1/overview")
    def overview_view(actor: str = Depends(analyst)):
        g = graph()
        return ok(overview(core().db, [c.key for c in g.cases()], g.case_for_post))

    # ---------- банки ----------
    def feed_rows(since: str | None, min_level: str, limit: int, offset: int, list_name: str | None) -> list[dict[str, Any]]:
        rows = core().db.requisite_feed(since, min_level, limit, offset, list_name)
        g = graph()
        feed = []
        for r in rows:
            post_ids = core().db.posts_with_requisite(r["key"])
            cases = sorted({c for c in (g.case_for_post(pid) for pid in post_ids) if c})
            feed.append({"id": r["id"], "key": r["key"], "type": r["kind"], "value": r["display"], "max_score": r["max_score"],
                         "posts": r["posts"], "tracks": sorted(set((r["tracks"] or "").split(",")) - {""}), "cases": cases,
                         "first_seen": r["first_seen"], "last_seen": r["last_seen"],
                         **list_info(r["list"], r["decided"], r["grey_since"]),
                         "note": "Найдены признаки использования реквизита в схемах; не является основанием для блокировки без проверки"})
        return feed

    @app.get("/api/v1/bank/requisites")
    def bank_feed(since: str | None = Query(default=None, max_length=40),
                  min_level: str = Query(default="medium", pattern="^(medium|high)$"),
                  list_name: str | None = Query(default=None, alias="list", pattern="^(grey|black|cleared)$"),
                  limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0),
                  actor: str = Depends(bank)):
        feed = [{k: v for k, v in row.items() if k != "key"} for row in feed_rows(since, min_level, limit, offset, list_name)]
        core().db.audit(actor, "bank_feed", f"{len(feed)} rows")
        return ok(feed, limit=limit, offset=offset)

    @app.get("/api/v1/bank/requisites.csv")
    def bank_feed_csv(since: str | None = Query(default=None, max_length=40),
                      min_level: str = Query(default="medium", pattern="^(medium|high)$"),
                      list_name: str | None = Query(default=None, alias="list", pattern="^(grey|black|cleared)$"),
                      actor: str = Depends(bank)):
        """Выгрузка для обмена (Антифрод-центр, банки): HMAC-ссылка и маска вместо номера, статус, срок, основание."""
        key = core().settings.effective_hmac_key()
        found = feed_rows(since, min_level, CSV_MAX_ROWS + 1, 0, list_name)
        rows = [{**r, "ref": export_ref(r["key"], key), "value_masked": mask(r["type"], r["value"]),
                 "cases": " ".join(r["cases"]), "reason": r["list_reason"]} for r in found[:CSV_MAX_ROWS]]
        core().db.audit(actor, "bank_feed_csv", f"{len(rows)} rows")
        # Обрезанную выгрузку видно по заголовку: тогда выгружать частями через since
        return Response(to_csv(rows), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="pruf_requisites.csv"', "Cache-Control": "no-store",
                                 "X-PRUF-Truncated": "1" if len(found) > CSV_MAX_ROWS else "0"})

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
                   "first_seen": found["first_seen"], **list_info(found["list"], found["decided"], found["grey_since"]),
                   "note": "Найдены признаки использования реквизита в схемах; требуется проверка банком"})

    # ---------- расширение ПРУФ Sentinel ----------
    @app.post("/api/v1/inspect")
    def inspect_post(body: InspectIn, actor: str = Depends(extension)):
        """Риск поста по извлечённым признакам; текст поста сюда не приходит и ничего не сохраняется."""
        return ok(inspector().inspect(body.requisites, body.links, body.text_hash, body.cues))

    @app.post("/api/v1/reports")
    def report_post(body: ReportIn, request: Request, actor: str = Depends(extension)):
        """Жалоба пользователя. Кто жалуется, хранится только как HMAC от токена и id установки."""
        report_limiter.check(f"report:{request.client.host if request.client else 'unknown'}")
        # Месячная эпоха: жалобы одного человека не склеиваются в профиль дольше месяца
        epoch = time.strftime("%Y-%m", time.gmtime())
        reporter = hmac.new(core().settings.effective_hmac_key(), f"{actor}|{body.install_id}|{epoch}".encode(), "sha256").hexdigest()[:24]
        try:
            accepted = inspector().report(reporter, body.platform, body.requisites, body.links, body.text_hash, body.cues)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        core().db.audit(actor, "user_report", body.platform)
        return ok({"accepted": accepted})

    @app.get("/api/v1/reports")
    def reports_list(limit: int = Query(default=100, ge=1, le=500), actor: str = Depends(analyst)):
        """Реквизиты из жалоб: сначала те, на которые жаловалось больше разных людей."""
        db = core().db
        rows = [{"type": r["kind"], "value": r["display"], "reporters": r["reporters"], "reports": r["reports"],
                 "platforms": sorted(set((r["platforms"] or "").split(",")) - {""}), "last_report": r["last_report"],
                 "in_registry": bool(r["in_registry"])} for r in db.reported_requisites(limit)]
        return ok(rows, total=db.report_count())

    @app.get("/api/v1/blacklist/domains")
    def blacklist(actor: str = Depends(extension)):
        domains = inspector().blacklist()
        return ok(domains, total=len(domains), version=core().version)

    # ---------- разведчик ----------
    @app.get("/api/v1/scout")
    def scout_view(actor: str = Depends(analyst)):
        """Каналы и связи, найденные разведчиком (python -m pruf.scout)."""
        db = core().db
        return ok({"channels": db.scout_channels(), "edges": db.scout_edges()})

    # ---------- Telegram webhook ----------
    @app.post("/api/v1/telegram/webhook")
    async def telegram_webhook(request: Request):
        bot = state.get("bot")
        got = request.headers.get("x-telegram-bot-api-secret-token", "")
        # Секрет проверяется до чтения тела; без бота или с чужим секретом ответ одинаковый.
        if bot is None or not hmac.compare_digest(got.encode(), settings.telegram_secret.encode()):
            limiter.check(f"tgfail:{request.client.host if request.client else 'unknown'}")
            raise HTTPException(status_code=404, detail="Не найдено")
        length = request.headers.get("content-length", "")
        if not length.isdigit() or int(length) > WEBHOOK_MAX_BODY:
            raise HTTPException(status_code=413, detail="Слишком большой update")
        try:
            update = json.loads(await request.body())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный JSON") from exc
        if not isinstance(update, dict):
            raise HTTPException(status_code=400, detail="Некорректный update")
        uid = update.get("update_id")
        with bot_lock:
            if isinstance(uid, int) and uid in state["bot_seen"]:
                return ok({"queued": False, "reason": "duplicate"})  # Telegram повторил доставку
            if state["bot_pending"] >= BOT_MAX_PENDING:
                # 503, а не 200: Telegram повторит доставку позже, сообщение пользователя не потеряется
                log.warning("очередь бота переполнена, update %s отложен", uid)
                raise HTTPException(status_code=503, detail="Бот занят, повторите позже")
            if isinstance(uid, int):
                state["bot_seen"].append(uid)
            state["bot_pending"] += 1
        state["bot_pool"].submit(run_bot, bot, update)
        return ok({"queued": True})

    def run_bot(bot: BotLogic, update: dict[str, Any]) -> None:
        try:
            bot.handle(update)
        except Exception:
            log.exception("ошибка обработки update")
        finally:
            with bot_lock:
                state["bot_pending"] -= 1

    @app.get("/api/v1/health")
    def health():
        return ok({"status": "ok"})

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(Path(WEB_DIR) / "index.html")

    return app
