"""Behaviour tests for persistent session model switching."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_session_actions(runner):
    gateway = types.ModuleType("gateway")
    gateway_run = types.ModuleType("gateway.run")
    gateway_run._gateway_runner_ref = lambda: runner
    sys.modules["gateway"] = gateway
    sys.modules["gateway.run"] = gateway_run

    config = types.ModuleType("hermes_cli.config")
    config.load_config = lambda: {"model": {"default": "gpt-5.6-terra", "provider": "chubby"}}
    config.get_compatible_custom_providers = lambda _cfg: []
    model_switch = types.ModuleType("hermes_cli.model_switch")
    model_switch.switch_model = lambda **_kwargs: None
    sys.modules["hermes_cli"] = types.ModuleType("hermes_cli")
    sys.modules["hermes_cli.config"] = config
    sys.modules["hermes_cli.model_switch"] = model_switch

    package = types.ModuleType("enhancer_test")
    package.__path__ = [str(ROOT)]
    sys.modules["enhancer_test"] = package
    models = types.ModuleType("enhancer_test.models")
    models.resolve_provider_config = lambda _name: {
        "provider": "custom:chubby",
        "base_url": "http://example.invalid",
        "api_key": "secret-not-persisted",
        "api_mode": "codex_responses",
    }
    sys.modules["enhancer_test.models"] = models

    spec = importlib.util.spec_from_file_location("enhancer_test.session_actions", ROOT / "session_actions.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Store:
    def __init__(self):
        self.persisted = []

    async def set_model_override(self, key, override):
        safe = None if override is None else {
            name: value
            for name, value in override.items()
            if name in {"model", "provider", "base_url"} and value not in (None, "")
        }
        self.persisted.append((key, safe))

    async def lookup_by_session_key(self, _key):
        return types.SimpleNamespace(session_id="session-1")


class _SessionDB:
    def __init__(self):
        self.updated = []

    async def update_session_model(self, session_id, model, *, provider):
        self.updated.append((session_id, model, provider))


class _Runner:
    def __init__(self):
        self._session_model_overrides = {}
        self.async_session_store = _Store()
        self._session_db = _SessionDB()
        self.evicted = []

    def _evict_cached_agent(self, key):
        self.evicted.append(key)


class _Adapter:
    pass


def test_model_switch_persists_non_secret_override_before_evicting_agent():
    runner = _Runner()
    actions = _load_session_actions(runner)

    ok, model = asyncio.run(actions.switch_session_model(_Adapter(), "session-key", "gpt-5.6-sol", "chubby"))

    assert (ok, model) == (True, "gpt-5.6-sol")
    assert runner.async_session_store.persisted
    key, persisted = runner.async_session_store.persisted[-1]
    assert key == "session-key"
    assert persisted["model"] == "gpt-5.6-sol"
    assert persisted["provider"] == "custom:chubby"
    assert "api_key" not in persisted
    assert runner._session_db.updated == [("session-1", "gpt-5.6-sol", "custom:chubby")]
    assert runner.evicted == ["session-key"]
