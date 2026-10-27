"""Вспомогательные функции для тестов (не фикстуры)."""

from __future__ import annotations

from pathlib import Path

from pruf.config import Settings

TEST_HMAC_KEY = "test-hmac-key"
KASPI_PHONE = "+7 701 999 88 77"

LOTTERY_RU = "🎁 РОЗЫГРЫШ iPhone 15 Pro! Участие всего 2000 тг, переводите на Kaspi {phone}. Итоги в пятницу, осталось 5 мест!"
CASINO_RU = "Вчера поднял x500 на слотах 🔥 где играю — ссылка в профиле. Пополнение через каспи {phone}"
PYRAMID_RU = "Пассивный доход 5% в день! Пригласи друзей и получай бонус с каждого, вход от 5000 тг, каспи {phone}"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    """Явные настройки без зависимости от переменных окружения."""
    base = dict(
        data_dir=tmp_path / "data", model_path=tmp_path / "no-model" / "clf.joblib", analyst_token="",
        bank_tokens=(), bank_allow_analyst=False, dev_mode=True, hmac_key=TEST_HMAC_KEY, anthropic_api_key="", resolve_links=False,
        max_upload_bytes=8 * 1024 * 1024, rate_limit_per_minute=1000,
    )
    base.update(overrides)
    return Settings(**base)


def fastest(fn, repeats: int = 3) -> float:
    """Лучшее время из нескольких прогонов: защита от ReDoS без падений из-за нагрузки на CI."""
    import time

    best = float("inf")
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - started)
    return best
