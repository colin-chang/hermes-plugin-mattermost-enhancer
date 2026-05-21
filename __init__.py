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

    logger.info("Mattermost Approval Plugin registered (overrides built-in adapter)")
