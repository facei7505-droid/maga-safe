"""Пакет доказательств по кейсу: ZIP с артефактами, manifest.json (SHA-256, UTC-время) и report.html."""

from __future__ import annotations

import hashlib
import html
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from pruf import __version__
from pruf.graph.builder import CaseGraph, CaseSummary
from pruf.models import LEVEL_LABELS
from pruf.storage.blobs import BlobStore
from pruf.storage.db import Database

DISCLAIMER = ("Пакет содержит признаки, найденные автоматически, и не является выводом о виновности. "
              "Решение принимает уполномоченный аналитик.")


# Сколько байт файлов-пруфов кладём в один пакет (остальные только хешами в manifest.json)
MAX_EXPORT_ARTIFACT_BYTES = 200 * 1024 * 1024

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _report_html(case: CaseSummary, posts: list[dict[str, Any]], generated: str) -> str:
    esc = html.escape
    rows = []
    for p in posts:
        analysis = p.get("analysis") or {}
        ev = "".join(
            f"<li><b>{esc(e['label'])}</b> ({esc(e['source'])}, {e['weight']:+g})"
            + (f"<br><q>{esc(e['quote'])}</q>" if e.get("quote") else "") + "</li>"
            for e in analysis.get("evidence", [])
        )
        rows.append(
            f"<section><h3>Пост #{p['id']} · {esc(p.get('channel') or '—')} · {esc(p.get('posted_at') or '')}</h3>"
            f"<p>Риск: <b>{esc(LEVEL_LABELS.get(p['level'], p['level']))}</b> ({p['score']})</p>"
            f"<pre>{esc(p.get('text') or '')}</pre><ul>{ev}</ul></section>"
        )
    return (
        "<!doctype html><html lang='ru'><meta charset='utf-8'><title>Кейс " + esc(case.key) + "</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}"
        "pre{white-space:pre-wrap;background:#f4f4f4;padding:.5rem}q{color:#444}</style>"
        f"<h1>Кейс {esc(case.key)}</h1><p>{esc(DISCLAIMER)}</p>"
        f"<p>Сформирован: {esc(generated)} UTC · ПРУФ {esc(__version__)}</p>"
        f"<p>Риск: {esc(LEVEL_LABELS.get(case.level, case.level))} ({case.score}) · Треки: {esc(', '.join(case.tracks))}</p>"
        f"<p>Реквизиты: {esc(', '.join(case.requisites) or '—')}<br>Домены: {esc(', '.join(case.domains) or '—')}<br>"
        f"Каналы: {esc(', '.join(case.channels) or '—')}</p>" + "".join(rows) + "</html>"
    )


def build_evidence_package(db: Database, blobs: BlobStore, graph: CaseGraph, case: CaseSummary, actor: str) -> tuple[bytes, str]:
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    posts = [db.get_post(pid) for pid in case.post_ids]
    posts = [p for p in posts if p]
    for p in posts:
        p.pop("label", None)  # служебная метка синтетики в пакет не попадает
    files: dict[str, bytes] = {}
    artifacts_meta = []
    missing: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    budget = MAX_EXPORT_ARTIFACT_BYTES
    for p in posts:
        for art in db.artifacts_for_post(p["id"]):
            if art["kind"] not in ("image", "audio") or not art["ext"]:
                continue
            if budget <= 0:
                # Пакет собирается в памяти: сверх лимита файлы не кладём, но фиксируем их хеши
                skipped.append({"post_id": p["id"], "artifact_id": art["id"], "sha256": art["sha256"]})
                continue
            data = blobs.get(art["sha256"], art["ext"])
            if data is None:
                missing.append({"post_id": p["id"], "artifact_id": art["id"], "sha256": art["sha256"]})
                continue
            name = f"artifacts/post{p['id']}_a{art['id']}.{art['ext']}"
            files[name] = data
            budget -= len(data)
            artifacts_meta.append({"file": name, "post_id": p["id"], "artifact_id": art["id"], "sha256": art["sha256"],
                                   "pdq": art.get("pdq")})
    files["graph.json"] = json.dumps(graph.subgraph(case.post_ids), ensure_ascii=False, indent=1).encode()
    files["posts.json"] = json.dumps(posts, ensure_ascii=False, indent=1, default=str).encode()
    files["report.html"] = _report_html(case, posts, generated).encode()
    manifest = {
        "case": case.to_dict(), "generated_at_utc": generated, "generator": f"pruf {__version__}", "exported_by": actor,
        "disclaimer": DISCLAIMER, "artifacts": artifacts_meta, "missing_artifacts": missing,
        "skipped_artifacts": skipped,
        "files": {name: _sha(data) for name, data in sorted(files.items())},
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=1).encode()
    manifest_sha = _sha(manifest_bytes)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("manifest.sha256", f"{manifest_sha}  manifest.json\n")
    db.audit(actor, "export", f"{case.key}:{manifest_sha}")
    return buf.getvalue(), manifest_sha
