"""
Mattermost Unified Plugin — DM 审批 + /model + /new Interactive Message 卡片交互。

通过 register_platform(name="mattermost") 覆盖内置 MattermostAdapter，
新增回调服务器、Slash 指令处理、卡片渲染。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx):
    """Plugin entry point — called by Hermes plugin system at startup."""
    from .adapter import MattermostApprovalAdapter
    from .callback_server import check_mattermost_requirements

    ctx.register_platform(
        name="mattermost",
        label="Mattermost (Approval)",
        adapter_factory=lambda cfg: MattermostApprovalAdapter(cfg),
        check_fn=check_mattermost_requirements,
        required_env=[
            "MATTERMOST_URL",
            "MATTERMOST_TOKEN",
        ],
        install_hint=(
            "MATTERMOST_URL=https://mm.example.com"
            " MATTERMOST_TOKEN=xxx MATTERMOST_CALLBACK_BIND=0.0.0.0"
        ),
    )

    # 注册 pre_gateway_dispatch hook — 实现 Channel → Thread 模型继承
    ctx.register_hook("pre_gateway_dispatch", _model_inheritance_hook)

    logger.info("Mattermost Approval Plugin registered (overrides built-in adapter)")


def _model_inheritance_hook(event, gateway, session_store, **kwargs):
    """Channel → Thread 模型继承。

    当用户在 Channel 中通过 /model 切换模型后，新建的 Thread 自动继承
    Channel 的模型设置，无需在每个 Thread 中重复切换。

    返回 {"action": "allow"} 始终放行消息，不改变消息处理流程。
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    source = event.source

    # 仅处理 Mattermost 的 Thread 消息
    if getattr(source.platform, "value", "") != "mattermost":
        return {"action": "allow"}
    if not source.thread_id:
        return {"action": "allow"}

    try:
        # 构造 session key（与 build_session_key 逻辑一致）
        chat_type = source.chat_type or "channel"
        platform = source.platform.value
        chat_id = source.chat_id

        thread_key = f"agent:main:{platform}:{chat_type}:{chat_id}:{source.thread_id}"
        parent_key = f"agent:main:{platform}:{chat_type}:{chat_id}"

        # Thread 已有 override → 不做任何事（用户已在 Thread 内独立切模型）
        if thread_key in gateway._session_model_overrides:
            return {"action": "allow"}

        # 查父 Channel 是否有 override
        parent_override = gateway._session_model_overrides.get(parent_key)
        if not parent_override:
            return {"action": "allow"}

        # 继承 Channel 的模型设置到 Thread
        gateway._session_model_overrides[thread_key] = dict(parent_override)

        _log.info(
            "Model inherited: thread=%s ← channel=%s model=%s",
            thread_key, parent_key,
            parent_override.get("model", "?"),
        )

    except Exception:
        _log.debug("Model inheritance check failed", exc_info=True)

    return {"action": "allow"}
