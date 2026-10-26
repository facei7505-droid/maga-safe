"""Демо при первом старте сервера: заливка идёт в фоне, а сайт сразу отвечает «Демо загружается».

Раньше заливку делал docker-entrypoint.sh до запуска сервера, и порт открывался только через несколько минут:
проснувшийся бесплатный Render всё это время показывал ошибку. Теперь сервер поднимается сразу.
"""

from __future__ import annotations

import importlib.util
import logging
from types import ModuleType

from pruf.config import ROOT
from pruf.pipeline import Pruf

log = logging.getLogger(__name__)

SEED_SCRIPT = ROOT / "scripts" / "seed_demo.py"
SCOUT_MAX_REQUESTS = 400

LOADING_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5"><title>ПРУФ — демо загружается</title>
<style>
:root { color-scheme: light dark; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; font: 16px/1.5 system-ui, sans-serif;
       background: #f6f7f9; color: #1d2330; padding: 16px; box-sizing: border-box; }
@media (prefers-color-scheme: dark) { body { background: #12151b; color: #e6e9ef; } }
main { max-width: 420px; text-align: center; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #2f6fed; margin: 0 3px;
       animation: pulse 1.2s infinite ease-in-out; }
.dot:nth-child(2) { animation-delay: .2s; } .dot:nth-child(3) { animation-delay: .4s; }
@keyframes pulse { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
p { opacity: .75; }
</style></head>
<body><main>
<h1>ПРУФ</h1>
<div aria-hidden="true"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
<p>Сервер проснулся и готовит демо-данные. Страница обновится сама, как только всё будет готово.</p>
</main></body></html>
"""


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pruf_seed_demo", SEED_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"нет {SEED_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_scout_demo(pruf: Pruf) -> None:
    """Офлайн-демо разведчика на фикстуре: вкладка «Разведка» не пустая. Claude не зовёт."""
    from pruf.scout.__main__ import DEMO_SEED
    from pruf.scout.scout import Scout, ScoutConfig
    from pruf.scout.sources import DEMO_FIXTURE, FixtureSource, Throttle, ThrottledSource

    source = ThrottledSource(FixtureSource(DEMO_FIXTURE), Throttle(0.0, SCOUT_MAX_REQUESTS))
    Scout(pruf, source, ScoutConfig(store=True, allow_llm=False, keywords=())).run([DEMO_SEED])


def seed(pruf: Pruf) -> None:
    """Демо-кампании, кейс C-211, списки и журнал разведчика — в ту же базу и индексы, что у сервера."""
    _seed_module().seed_all(pruf)
    try:
        run_scout_demo(pruf)
    except Exception:  # noqa: BLE001 — без разведчика сайт работает, вкладка будет пустой
        log.exception("демо разведчика не запустилось")
