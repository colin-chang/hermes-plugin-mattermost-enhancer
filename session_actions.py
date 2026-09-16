"""Session-scoped model switching and reset actions for Mattermost Enhancer.

Kept outside the adapter transport class so provider/session compatibility logic can
be tested without starting a Mattermost callback server.
"""
from __future__ import annotations

import logging
from typing import Any, Tuple

logger = logging.getLogger(__name__)


def current_model(adapter: Any, session_key: str) -> str:
    """Return the session override model, falling back to the configured default."""
    try:
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
        if runner:
            override = runner._session_model_overrides.get(session_key, {})
            if override:
                return str(override.get("model", ""))
    except Exception:
        logger.debug("Could not read in-memory model override", exc_info=True)

    try:
        from hermes_cli.config import load_config

        return str(load_config().get("model", {}).get("default", ""))
    except Exception:
        logger.debug("Could not read configured default model", exc_info=True)
        return ""


async def switch_session_model(
    adapter: Any,
    session_key: str,
    model_id: str,
    provider_name: str,
) -> Tuple[bool, str]:
    """Switch, persist, and evict a session-scoped model override.

    The persisted value intentionally contains no API key. Hermes resolves current
    credentials when it rehydrates the override after a Gateway restart.
    """
    try:
        from gateway.run import _gateway_runner_ref
        from hermes_cli.config import get_compatible_custom_providers, load_config
        from hermes_cli.model_switch import switch_model

        runner = _gateway_runner_ref()
        if not runner:
            return False, "GatewayRunner not available"

        from .models import resolve_provider_config

        provider_config = resolve_provider_config(provider_name)
        old_model = current_model(adapter, session_key) or "(default)"

        if provider_config:
            override = {
                "model": model_id,
                "provider": provider_config["provider"],
                "base_url": provider_config["base_url"],
                "api_key": provider_config["api_key"],
                "api_mode": provider_config["api_mode"],
            }
        else:
            logger.warning(
                "Provider '%s' not in custom_providers, falling back to switch_model for %s",
                provider_name,
                model_id,
            )
            config = load_config()
            model_config = config.get("model", {})
            custom_providers = get_compatible_custom_providers(config)
            previous = runner._session_model_overrides.get(session_key, {})
            result = switch_model(
                raw_input=model_id,
                current_provider=previous.get("provider", model_config.get("provider", "openrouter")),
                current_model=previous.get("model", model_config.get("default", "")),
                current_base_url=previous.get("base_url", model_config.get("base_url", "")),
                current_api_key=previous.get("api_key", ""),
                user_providers=config.get("providers"),
                custom_providers=custom_providers,
                explicit_provider=provider_name or None,
            )
            if not result.success:
                return False, result.error_message or "switch_model failed"
            override = {
                "model": result.new_model,
                "provider": result.target_provider,
                "base_url": result.base_url,
                "api_key": result.api_key,
                "api_mode": result.api_mode,
            }

        runner._session_model_overrides[session_key] = override
        try:
            await runner.async_session_store.set_model_override(session_key, override)
            session_db = getattr(runner, "_session_db", None)
            if session_db is not None:
                entry = await runner.async_session_store.lookup_by_session_key(session_key)
                if entry is not None:
                    await session_db.update_session_model(
                        entry.session_id,
                        model_id,
                        provider=override["provider"],
                    )
        except Exception:
            logger.warning(
                "Model switch persisted only in memory: session=%s model=%s",
                session_key,
                model_id,
                exc_info=True,
            )

        runner._evict_cached_agent(session_key)
        if not hasattr(runner, "_pending_model_notes"):
            runner._pending_model_notes = {}
        runner._pending_model_notes[session_key] = (
            f"[Note: model was just switched from {old_model} to {model_id} "
            f"via {override.get('provider', provider_name)}. "
            "Adjust your self-identification accordingly.]"
        )
        logger.info(
            "Model switched: session=%s -> %s provider=%s override_persisted=YES",
            session_key,
            model_id,
            override.get("provider", "?"),
        )
        return True, model_id
    except Exception as exc:
        logger.error("Model switch failed: %s", exc, exc_info=True)
        return False, str(exc)


async def reset_session(adapter: Any, session_key: str) -> Tuple[bool, str]:
    """Reset session state and all enhancer-owned runtime overrides."""
    try:
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
        if not runner:
            return False, "GatewayRunner not available"
        runner._session_model_overrides.pop(session_key, None)
        await runner.async_session_store.set_model_override(session_key, None)
        runner._evict_cached_agent(session_key)
        if hasattr(runner, "session_store"):
            runner.session_store.reset_session(session_key)
        if hasattr(runner, "_set_session_reasoning_override"):
            runner._set_session_reasoning_override(session_key, None)
        if hasattr(runner, "_pending_model_notes"):
            runner._pending_model_notes.pop(session_key, None)
        if hasattr(runner, "_clear_session_boundary_security_state"):
            runner._clear_session_boundary_security_state(session_key)
        logger.info("Session reset: session=%s", session_key)
        return True, "Session reset"
    except Exception as exc:
        logger.error("Session reset failed: %s", exc, exc_info=True)
        return False, str(exc)
