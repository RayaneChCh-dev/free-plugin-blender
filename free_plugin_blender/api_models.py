"""Live model lists of the API-key chat providers, cached on disk (bpy)."""

from __future__ import annotations

import json

from . import prefs, tasks
from .providers import openai_compat

PROVIDER_OF = {"OPENAI": "openai"}  # chat_provider → openai_compat.PROVIDERS key
_cache: dict[str, list[str]] = {}


def _path():
    return prefs.user_dir() / "api_models.json"


def _load():
    if not _cache:
        try:
            _cache.update(json.loads(_path().read_text()))
        except (OSError, ValueError):
            pass


def preset(provider=None):
    return openai_compat.PROVIDERS[PROVIDER_OF[provider or prefs.get().chat_provider]]


def models(provider=None) -> list[str]:
    _load()
    return _cache.get(provider or prefs.get().chat_provider, [])


def current(provider=None) -> str:
    provider = provider or prefs.get().chat_provider
    chosen = prefs.get().openai_model.strip() if provider == "OPENAI" else ""
    return chosen or openai_compat.default_model(models(provider))


def refreshing() -> bool:
    return any(t.state == "running" and t.label.startswith("Models:") for t in tasks.TASKS)


def refresh(provider=None):
    """Read the provider's model list in the background (it shows in Generations)."""
    provider = provider or prefs.get().chat_provider
    if provider not in PROVIDER_OF or refreshing():
        return
    key, info = prefs.api_key(provider), preset(provider)

    def work(task):
        return openai_compat.list_models(info["base_url"], key, PROVIDER_OF[provider])

    def done(task, ids):
        _load()
        _cache[provider] = ids
        try:
            _path().write_text(json.dumps(_cache))
        except OSError:
            pass
        return f"{len(ids)} models"

    tasks.run(f"Models: {info['label']}", work, done)


def refresh_if_needed():
    provider = prefs.get().chat_provider
    if provider in PROVIDER_OF and prefs.api_key(provider) and not models(provider):
        refresh(provider)
