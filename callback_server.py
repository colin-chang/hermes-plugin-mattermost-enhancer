"""
Mattermost 审批回调服务器 — HTTP 端点处理 Interactive Message 按钮回调 + Slash 指令。

环境检查函数：
  - check_mattermost_requirements(): 检查 MATTERMOST_URL + MATTERMOST_TOKEN + aiohttp

回调服务器由 adapter.py 的 _start_callback_server() 启动（原生 asyncio TCP），
路由：
  POST /mattermost/callback  → Interactive Message 按钮回调（审批 + cmd_*）
  POST /mm-command           → Slash 指令（/model + /new）
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 环境检查
# ═══════════════════════════════════════════════════════════════════════════

def check_mattermost_requirements() -> bool:
    """Return True if Mattermost can be used (by this plugin).

    与内置 check_mattermost_requirements() 语义一致：检查 URL + Token 存在，
    以及 aiohttp 可用。
    """
    token = os.getenv("MATTERMOST_TOKEN", "")
    url = os.getenv("MATTERMOST_URL", "")
    if not token:
        logger.debug("Mattermost (plugin): MATTERMOST_TOKEN not set")
        return False
    if not url:
        logger.debug("Mattermost (plugin): MATTERMOST_URL not set")
        return False
    try:
        import aiohttp  # noqa: F401
        return True
    except ImportError:
        logger.debug("Mattermost (plugin): aiohttp not installed")
        return False
