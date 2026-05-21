"""
Session 定位与操作。

职责：
  - create_session_key(): 根据 channel_id + root_id 创建 session key
  - locate_session(): 从 callback payload 定位 session_key
  - switch_session_model(): 切换指定 session 的模型（通过 GatewayRunner._session_model_overrides）
  - reset_session(): 重置指定 session 的对话上下文

模型切换机制：
  GatewayRunner 内部维护 _session_model_overrides dict，结构为：
    {session_key: {model, provider, api_key, base_url, api_mode}}
  切换模型 = 写入此 dict + evict 缓存的 agent。
  通过 _gateway_runner_ref 全局弱引用访问 GatewayRunner 实例。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def create_session_key(
    channel_id: str,
    root_id: Optional[str] = None,
    reply_mode: str = "thread",
) -> str:
    """根据 channel_id 和 root_id 创建 session key。

    CRT Thread 模式: agent:main:mattermost:group:<channel_id>:<root_id>
    扁平模式:        agent:main:mattermost:group:<channel_id>

    注意：session key 格式需与 gateway/run.py 的 _session_key_for_source() 对齐。
    """
    if reply_mode == "thread" and root_id:
        return f"agent:main:mattermost:group:{channel_id}:{root_id}"
    return f"agent:main:mattermost:group:{channel_id}"


def locate_session(
    channel_id: str,
    root_id: Optional[str] = None,
    reply_mode: str = "thread",
) -> str:
    """从 callback payload 定位 session_key。

    等同于 create_session_key()，语义别名。
    """
    return create_session_key(channel_id, root_id, reply_mode)


def _get_gateway_runner():
    """获取 GatewayRunner 实例（通过全局弱引用）。"""
    try:
        from gateway.run import _gateway_runner_ref
        runner = _gateway_runner_ref()
        if runner is not None:
            return runner
    except Exception as e:
        logger.debug("Failed to get gateway runner ref: %s", e)
    return None


async def switch_session_model(
    adapter,
    session_key: str,
    model_id: str,
) -> bool:
    """切换指定 session 的模型（仅影响当前 session）。

    实现策略：
      1. 通过 _gateway_runner_ref 获取 GatewayRunner 实例
      2. 解析 model_id → provider + api_key + base_url + api_mode
      3. 写入 _session_model_overrides[session_key]
      4. 调用 _evict_cached_agent(session_key) 使缓存的 agent 失效

    Args:
        adapter: MattermostApprovalAdapter 实例
        session_key: 目标 session key
        model_id: 目标模型 ID

    Returns:
        True 表示切换成功
    """
    try:
        from .models import validate_model_id
        if not validate_model_id(model_id):
            logger.warning("Invalid model_id for switch: %s", model_id)
            return False

        runner = _get_gateway_runner()
        if runner is None:
            logger.warning("Cannot switch model: GatewayRunner not available")
            return False

        # 解析模型对应的 provider 信息
        provider, api_key, base_url, api_mode = _resolve_provider_for_model(model_id)

        # 写入 session override
        runner._session_model_overrides[session_key] = {
            "model": model_id,
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "api_mode": api_mode,
        }

        # 清除缓存 agent，下次对话自动用新配置
        runner._evict_cached_agent(session_key)

        # 添加 model note，让 agent 感知切换
        if not hasattr(runner, "_pending_model_notes"):
            runner._pending_model_notes = {}

        current_model = _get_current_model_for_session(runner, session_key)
        runner._pending_model_notes[session_key] = (
            f"[Note: model was just switched from {current_model} to {model_id} "
            f"via {provider}. Adjust your self-identification accordingly.]"
        )

        logger.info(
            "Session model switched: %s → %s (session %s, provider %s)",
            current_model, model_id, session_key[:60], provider,
        )
        return True

    except Exception as e:
        logger.error("Failed to switch session model: %s", e, exc_info=True)
        return False


async def reset_session(
    adapter,
    session_key: str,
) -> bool:
    """重置指定 session 的对话上下文。

    实现策略：
      1. 通过 _gateway_runner_ref 获取 GatewayRunner 实例
      2. 调用 _evict_cached_agent + 清理 session 数据

    Args:
        adapter: MattermostApprovalAdapter 实例
        session_key: 目标 session key

    Returns:
        True 表示重置成功
    """
    try:
        runner = _get_gateway_runner()
        if runner is None:
            logger.warning("Cannot reset session: GatewayRunner not available")
            return False

        # 清除缓存 agent
        runner._evict_cached_agent(session_key)

        # 清除 session model override
        runner._session_model_overrides.pop(session_key, None)

        # 清除 pending model notes
        if hasattr(runner, "_pending_model_notes"):
            runner._pending_model_notes.pop(session_key, None)

        # 清除 session DB 中的对话历史
        try:
            from hermes_state import SessionDB
            from hermes_constants import get_hermes_home
            db_path = get_hermes_home() / "sessions" / "sessions.db"
            if db_path.exists():
                db = SessionDB(str(db_path))
                db.clear_session_messages(session_key)
        except Exception as e:
            logger.debug("Could not clear session messages from DB: %s", e)

        logger.info("Session reset: %s", session_key[:60])
        return True

    except Exception as e:
        logger.error("Failed to reset session: %s", e, exc_info=True)
        return False


def _resolve_provider_for_model(model_id: str) -> tuple:
    """解析模型 ID 对应的 provider/api_key/base_url/api_mode。

    从 config.yaml 的 custom_providers 中查找。
    """
    try:
        from hermes_cli.config import load_config
        import os

        config = load_config()
        custom_providers = config.get("custom_providers", [])

        for cp in custom_providers:
            models_map = cp.get("models", {})
            if isinstance(models_map, dict) and model_id in models_map:
                # 找到了！提取 provider 信息
                name = cp.get("name", "")
                base_url = cp.get("base_url", "")
                # api_key 可能是 ${ENV_VAR} 格式
                api_key_raw = cp.get("api_key", "")
                api_key = _resolve_env_ref(api_key_raw)

                # provider name 使用 "custom:<name>" 格式
                provider = f"custom:{name}" if name else "custom"
                api_mode = cp.get("api_mode", "chat_completions")

                return provider, api_key, base_url, api_mode

        # 未找到 → 使用默认 provider
        model_cfg = config.get("model", {})
        default_provider = model_cfg.get("provider", "")
        return default_provider, "", "", ""

    except Exception as e:
        logger.error("Failed to resolve provider for model %s: %s", model_id, e)
        return "", "", "", ""


def _resolve_env_ref(value: str) -> str:
    """解析 ${ENV_VAR} 格式的环境变量引用。"""
    import re
    match = re.match(r'^\$\{(\w+)\}$', value)
    if match:
        import os
        return os.getenv(match.group(1), "")
    return value


def _get_current_model_for_session(runner, session_key: str) -> str:
    """获取 session 当前的模型。"""
    override = runner._session_model_overrides.get(session_key)
    if override:
        return override.get("model", "unknown")
    # 从 config 获取默认模型
    try:
        from hermes_cli.config import load_config
        config = load_config()
        return config.get("model", {}).get("default", "unknown")
    except Exception:
        return "unknown"
