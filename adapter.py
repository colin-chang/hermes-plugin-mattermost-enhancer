"""
MattermostApprovalAdapter — 继承内置 MattermostAdapter，扩展 DM 审批 + /model 卡片 + /new 确认。

架构说明：
  Mattermost 拦截所有 / 开头消息，必须注册 Slash Command 才能接收。
  Slash Command payload 不含 root_id，需要通过 Mattermost API 反查 thread 上下文。

修复的问题：
  1. 重复消息 → Slash Command 返回空 ephemeral，Bot API 发帖（唯一可见消息）
  2. 模型切换无效 → 直接从 custom_providers 构建 session override（绕过 switch_model 路由）
  3. 显示用户头像 → 使用 _api_post("posts", ...) 以 Bot 身份发帖
  4. 模型排列混乱 → 按 provider 分组渲染，按钮名去掉 provider 前缀
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from gateway.platforms.base import SendResult
from gateway.platforms.mattermost import MattermostAdapter, MAX_POST_LENGTH
from tools.approval import resolve_gateway_approval

from .cards import (
    render_model_selector_card,
    render_new_session_confirm_card,
    render_switch_success_card,
    render_reset_success_card,
    render_clarify_card,
    render_clarify_choice_confirmed_card,
    render_clarify_other_prompt_card,
)

logger = logging.getLogger(__name__)


class MattermostApprovalAdapter(MattermostAdapter):
    """Mattermost 适配器 — DM 审批 + /model 卡片 + /new 确认。"""

    def __init__(self, config):
        import os as _os

        super().__init__(config)
        self._model_picker_callbacks: Dict[str, Callable] = {}

        # ── Callback server 配置 ──
        self._callback_server = None
        self._callback_port: int = int(
            _os.getenv("MATTERMOST_CALLBACK_PORT", "18065")
        )
        self._callback_bind: str = _os.getenv(
            "MATTERMOST_CALLBACK_BIND", "127.0.0.1"
        )
        self._callback_url: str = _os.getenv(
            "MATTERMOST_CALLBACK_URL", ""
        )
        self._callback_secret: str = _os.getenv(
            "MATTERMOST_CALLBACK_SECRET", ""
        )
        # DM channel 缓存: user_id → dm_channel_id
        self._dm_cache: Dict[str, str] = {}
        # Footer 追踪: chat_id → (post_id, content)
        # runtime footer 不独立发帖，而是编辑上一条消息追加到末尾
        self._tracked_posts: Dict[str, Tuple[str, str]] = {}

    # ══════════════════════════════════════════════════════════════════════
    # 公共辅助方法
    # ══════════════════════════════════════════════════════════════════════

    def _get_allowed_users(self) -> set:
        """获取 MATTERMOST_ALLOWED_USERS 配置."""
        import os as _os
        allowed_str = _os.getenv("MATTERMOST_ALLOWED_USERS", "").strip()
        if not allowed_str:
            return set()
        return {u.strip() for u in allowed_str.split(",") if u.strip()}

    @staticmethod
    def _is_footer_line(content: str) -> bool:
        """检测 runtime footer 行 — 单行、含 · 分隔符、纯文本."""
        if "\n" in content or len(content) > 120:
            return False
        if " · " not in content:
            return False
        return True

    async def _get_or_create_dm(self, user_id: str) -> str:
        """获取或创建与指定用户的 DM channel（幂等，带缓存）."""
        if user_id in self._dm_cache:
            return self._dm_cache[user_id]

        payload = [self._bot_user_id, user_id]
        data = await self._api_post("channels/direct", payload)

        dm_id = data.get("id", "")
        if dm_id:
            self._dm_cache[user_id] = dm_id

        return dm_id

    async def _get_user_id_from_channel(self, channel_id: str) -> Optional[str]:
        """从 channel members 中提取非 bot 的 user_id。

        替代 patch 8：当 run.py 未传 user_id 时，通过 channel members API
        反查 DM channel 中的对方用户 ID。额外一次 GET 请求，仅在审批触发时调用。
        """
        try:
            data = await self._api_get(f"channels/{channel_id}/members")
            if isinstance(data, list):
                for member in data:
                    uid = member.get("user_id", "")
                    if uid and uid != self._bot_user_id:
                        return uid
        except Exception:
            logger.warning(
                "Mattermost: _get_user_id_from_channel failed for %s",
                channel_id, exc_info=True,
            )
        return None

    # ══════════════════════════════════════════════════════════════════════
    # 回调服务器（多路由）
    # ══════════════════════════════════════════════════════════════════════

    async def _start_callback_server(self) -> None:
        """启动 HTTP callback server。
        路由：
          POST /mattermost/callback → 按钮回调（审批 + 模型切换 + 会话重置）
          POST /mm-command          → Slash 指令（/model + /new）
        """
        import asyncio as _asyncio
        adapter_self = self

        async def _handler(reader: _asyncio.StreamReader, writer: _asyncio.StreamWriter):
            try:
                request_data = await _asyncio.wait_for(reader.read(65536), timeout=10.0)
                if not request_data:
                    writer.close()
                    return

                request_text = request_data.decode("utf-8", errors="replace")
                headers, _, body = request_text.partition("\r\n\r\n")
                request_line = headers.split("\r\n")[0]
                parts = request_line.split(" ", 2)
                if len(parts) < 2:
                    writer.close()
                    return
                method, path = parts[0], parts[1]

                if method != "POST":
                    writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
                    await writer.drain()
                    writer.close()
                    return

                if path == "/mattermost/callback":
                    result = await adapter_self._route_callback(headers, body)
                elif path == "/mm-command":
                    result = await adapter_self._route_slash_command(body)
                else:
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                    await writer.drain()
                    writer.close()
                    return

                response_body = json.dumps(result).encode("utf-8")
                response = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n\r\n"
                ).encode("utf-8") + response_body
                writer.write(response)
                await writer.drain()
                writer.close()
            except Exception:
                logger.exception("Unhandled error in callback server handler")
                try:
                    err_body = json.dumps({"ephemeral_text": "⚠️ Internal error"}).encode("utf-8")
                    err_resp = (
                        f"HTTP/1.1 200 OK\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(err_body)}\r\n\r\n"
                    ).encode("utf-8") + err_body
                    writer.write(err_resp)
                    await writer.drain()
                except Exception:
                    pass
                writer.close()

        server = await _asyncio.start_server(
            _handler, host=adapter_self._callback_bind, port=adapter_self._callback_port,
        )
        adapter_self._callback_server = server
        logger.info(
            "MattermostApproval callback server on %s:%s (routes: /mattermost/callback, /mm-command)",
            adapter_self._callback_bind, adapter_self._callback_port,
        )

    # ══════════════════════════════════════════════════════════════════════
    # 路由: Interactive Message 回调
    # ══════════════════════════════════════════════════════════════════════

    async def _route_callback(self, headers: str, body: str) -> Dict[str, Any]:
        """处理 POST /mattermost/callback。"""
        signature = ""
        for line in headers.split("\r\n"):
            if line.lower().startswith("x-mattermost-signature:"):
                signature = line.split(":", 1)[1].strip()
                break

        if self._callback_secret:
            if not signature or not self._verify_signature(body.encode("utf-8"), signature):
                return {"ephemeral_text": "Unauthorized"}

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return {"ephemeral_text": "Invalid JSON"}

        return await self._handle_callback(payload)

    # ══════════════════════════════════════════════════════════════════════
    # 路由: Slash 指令
    # ══════════════════════════════════════════════════════════════════════

    async def _route_slash_command(self, body: str) -> Dict[str, Any]:
        """处理 POST /mm-command（/model + /new）。

        关键设计：
          Slash Command 的 HTTP response 以用户身份显示 ephemeral（MM 设计限制）。
          为避免用户头像发送 Bot 消息的困惑，HTTP response 返回空 ephemeral，
          所有可见内容通过 Bot API 发帖。
        """
        from urllib.parse import unquote_plus
        params: Dict[str, str] = {}
        for pair in body.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = unquote_plus(v)

        command = params.get("command", "").lstrip("/")
        channel_id = params.get("channel_id", "")
        user_id = params.get("user_id", "")
        # MM Slash Command payload 包含 root_id 字段！
        # - 在 Thread 中发送时，root_id = thread 的 root post ID
        # - 在 Channel 顶层发送时，root_id = 空字符串
        root_id = params.get("root_id", "") or None

        logger.info("Slash command: /%s user=%s channel=%s root_id=%s",
                    command, user_id[:8], channel_id[:8], root_id or "(channel-level)")

        # 校验权限
        allowed_users = self._get_allowed_users()
        if allowed_users and user_id not in allowed_users:
            return {"response_type": "ephemeral", "text": "⛔ Unauthorized"}

        if command == "model":
            return await self._handle_model_command(channel_id, user_id, root_id)
        elif command == "new":
            return await self._handle_new_command(channel_id, user_id, root_id)

        return {"response_type": "ephemeral", "text": f"Unknown command: /{command}"}

    # ══════════════════════════════════════════════════════════════════════
    # Slash 指令处理
    # ══════════════════════════════════════════════════════════════════════

    # NOTE: _find_user_thread_root_id 已移除 — MM Slash Command payload
    # 原生包含 root_id 字段，无需 API 反查。

    async def _post_card_in_thread(
        self, channel_id: str, root_id: Optional[str], card: Dict[str, Any],
    ) -> Optional[str]:
        """通过 Bot API 在 thread 中发送 Interactive Message 卡片。返回 post_id。

        关键：message 留空，所有可见内容只在 props.attachments 中。
        如果 message 和 props.attachments 都有内容，MM 会重复显示。
        """
        attachments = card.get("attachments", [])

        payload: Dict[str, Any] = {
            "channel_id": channel_id,
            "message": "",  # 留空，避免与 props 重复显示
            "props": {"attachments": attachments},
        }

        if root_id:
            payload["root_id"] = root_id

        try:
            data = await self._api_post("posts", payload)
            if data and "id" in data:
                return data["id"]
            logger.error("Failed to post card: %s", data)
            return None
        except Exception as e:
            logger.error("Error posting card: %s", e)
            return None

    async def _update_bot_post(
        self, post_id: str, message: str, props: Dict[str, Any],
    ) -> bool:
        """通过 Bot API 更新帖子内容。"""
        try:
            payload = {
                "message": message,
                "props": props,
            }
            data = await self._api_post(f"posts/{post_id}", payload, method="PUT")
            return bool(data and "id" in data)
        except Exception as e:
            logger.error("Error updating post %s: %s", post_id, e)
            return False

    async def _handle_model_command(
        self, channel_id: str, user_id: str, root_id: Optional[str],
    ) -> Dict[str, Any]:
        """处理 /model Slash Command。

        root_id 来自 MM Slash Command payload：
          - Thread 中发送 → root_id = thread root post ID
          - Channel 顶层发送 → root_id = None
        """
        # 1. 获取可用模型（按 provider 分组）
        from .models import get_models_by_provider
        provider_groups = get_models_by_provider()

        # 2. 当前模型
        current_model = self._get_current_model_for_session(channel_id, root_id)

        # 4. 渲染卡片（分组模式）
        callback_url = self._callback_url or (
            f"http://{self._callback_bind}:{self._callback_port}/mattermost/callback"
        )
        card = render_model_selector_card(
            callback_url=callback_url,
            channel_id=channel_id,
            user_id=user_id,
            current_model=current_model,
            provider_groups=provider_groups,
        )

        # 5. 注入 session_key + provider 到按钮 context
        session_key = self._build_session_key(channel_id, root_id)
        self._inject_model_context(card, session_key)

        # 6. Bot API 发帖到 thread（Bot 头像，非用户头像）
        post_id = await self._post_card_in_thread(channel_id, root_id, card)

        if post_id:
            logger.info("Model picker posted: session=%s post=%s groups=%d",
                        session_key, post_id, len(provider_groups))
            # 返回空 ephemeral — 所有可见内容在 Bot 帖子中
            return {}

        return {"response_type": "ephemeral", "text": "❌ 发送模型选择器失败，请稍后重试"}

    async def _handle_new_command(
        self, channel_id: str, user_id: str, root_id: Optional[str],
    ) -> Dict[str, Any]:
        """处理 /new Slash Command。

        root_id 来自 MM Slash Command payload：
          - Thread 中发送 → root_id = thread root post ID
          - Channel 顶层发送 → root_id = None
        """
        callback_url = self._callback_url or (
            f"http://{self._callback_bind}:{self._callback_port}/mattermost/callback"
        )
        card = render_new_session_confirm_card(
            callback_url=callback_url,
            channel_id=channel_id,
            user_id=user_id,
        )

        session_key = self._build_session_key(channel_id, root_id)
        self._inject_session_key(card, session_key)

        post_id = await self._post_card_in_thread(channel_id, root_id, card)

        if post_id:
            logger.info("New session confirm posted: session=%s post=%s", session_key, post_id)
            # 保存 post_id 供后续回调更新
            self._new_confirm_posts = getattr(self, "_new_confirm_posts", {})
            self._new_confirm_posts[session_key] = post_id
            # 返回空 ephemeral
            return {}

        return {"response_type": "ephemeral", "text": "❌ 发送确认卡片失败，请稍后重试"}

    # ══════════════════════════════════════════════════════════════════════
    # Session 上下文辅助
    # ══════════════════════════════════════════════════════════════════════

    def _build_session_key(self, channel_id: str, root_id: Optional[str]) -> str:
        """构建 session_key，对齐 Gateway 的 build_session_key 格式。
        格式: agent:main:mattermost:group:<channel_id>[:<root_id>]
        """
        key = f"agent:main:mattermost:group:{channel_id}"
        if root_id:
            key += f":{root_id}"
        return key

    def _get_current_model_for_session(
        self, channel_id: str, root_id: Optional[str],
    ) -> str:
        """获取当前 session 使用的模型名。"""
        session_key = self._build_session_key(channel_id, root_id)

        # 先查 session override
        try:
            from gateway.run import _gateway_runner_ref
            runner = _gateway_runner_ref()
            if runner:
                override = runner._session_model_overrides.get(session_key, {})
                if override:
                    return override.get("model", "")
        except Exception:
            pass

        # 回退到 config 默认
        try:
            from hermes_cli.config import load_config
            cfg = load_config()
            model_cfg = cfg.get("model", {})
            if isinstance(model_cfg, dict):
                return model_cfg.get("default", "")
        except Exception:
            pass

        return ""

    def _inject_model_context(
        self, card: Dict[str, Any], session_key: str,
    ) -> None:
        """在模型选择卡片 context 中注入 session_key + provider_name。

        支持 select 和 button 两种 action 类型：
        - select: context 是共享的，selected_option 由 MM 在回调时添加
        - button: 每个 button 的 context 独立，包含 model_id 和 provider_name
        """
        from .models import _resolve_provider_for_model

        for att in card.get("attachments", []):
            for action in att.get("actions", []):
                ctx = action.get("integration", {}).get("context", {})

                # select 类型：context 是共享的，不需要 model_id/provider_name
                # 这些在回调时通过 selected_option 获取
                if action.get("type") == "select":
                    ctx["session_key"] = session_key
                    continue

                # button 类型：每个按钮的 context 包含 model_id
                model_id = ctx.get("model_id", "")
                ctx["session_key"] = session_key
                if model_id:
                    ctx["provider_name"] = _resolve_provider_for_model(model_id)

    def _inject_session_key(self, card: Dict[str, Any], session_key: str) -> None:
        """在卡片按钮 context 中注入 session_key。"""
        for att in card.get("attachments", []):
            for action in att.get("actions", []):
                ctx = action.get("integration", {}).get("context", {})
                ctx["session_key"] = session_key

    # ══════════════════════════════════════════════════════════════════════
    # 回调处理（Interactive Message 按钮）
    # ══════════════════════════════════════════════════════════════════════

    async def _handle_callback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理按钮回调 — 审批 + 模型切换 + 会话重置 + Clarify。"""
        context = payload.get("context", {})
        action = context.get("action", "")

        # ── Clarify 选择 ──
        if action == "cmd_clarify_choice":
            return await self._handle_clarify_choice_callback(payload)

        # ── Clarify「其他」─→
        if action == "cmd_clarify_other":
            return await self._handle_clarify_other_callback(payload)

        # ── 模型切换 ──
        if action == "cmd_model_switch":
            return await self._handle_model_switch_callback(payload)

        # ── 会话重置确认 ──
        if action == "cmd_new_confirm":
            return await self._handle_new_confirm_callback(payload)

        # ── 会话重置取消 ──
        if action == "cmd_new_cancel":
            return {"update": {"message": "❌ 已取消重置", "props": {}}}

        # ── DM 审批 ──
        session_key = context.get("session_key", "")
        if not action or not session_key:
            return {"ephemeral_text": "Invalid callback data"}

        user_id = payload.get("user_id", "")
        allowed_users = self._get_allowed_users()
        if allowed_users and user_id not in allowed_users:
            return {"ephemeral_text": "Unauthorized"}

        choice_map = {
            "approve_once": "once",
            "approve_session": "session",
            "approve_always": "always",
            "deny": "deny",
        }
        choice = choice_map.get(action)
        if not choice:
            return {"ephemeral_text": f"Unknown action: {action}"}

        # ── 并发点击防护：每个审批按 session_key 串行化 ──
        # asyncio 回调服务器可以并发处理多个请求。用户快速双击时，
        # 两个请求同时进入此方法，需用 Lock 串行化避免竞态。
        # 并发请求直接返回"处理中"更新并清空按钮，防止用户继续点击。
        import asyncio as _asyncio

        if not hasattr(self, "_approval_locks"):
            self._approval_locks: Dict[str, _asyncio.Lock] = {}

        lock = self._approval_locks.get(session_key)
        if not lock:
            lock = _asyncio.Lock()
            self._approval_locks[session_key] = lock

        if lock.locked():
            # 并发请求 — 另一个回调正在处理同一审批，快速返回
            logger.info(
                "Approval callback: concurrent click detected for session %s, "
                "returning processing update",
                session_key[:40],
            )
            return {
                "update": {
                    "message": "⏳ 正在处理您的审批请求，请稍候...",
                    "props": {
                        "attachments": [{
                            "actions": [],  # 清空按钮，防止继续点击
                        }],
                    },
                },
            }

        async with lock:
            count = resolve_gateway_approval(session_key, choice)
            if count == 0:
                # 审批已被处理（重复点击）— 仍然返回 update 清空卡片按钮
                # 防止用户继续点击看到 "No pending approval found" 错误
                return {
                    "update": {
                        "message": "⚠️ 此审批已处理",
                        "props": {
                            "attachments": [{
                                "actions": [],  # 清空按钮
                            }],
                        },
                    },
                }

            label_map = {
                "once": "✅ Approved — Allow Once",
                "session": "✅ Approved — Allow Session",
                "always": "✅ Approved — Always Allow",
                "deny": "❌ Denied",
            }
            cmd = context.get("command", "")
            cmd_display = f"\n```\n{cmd}\n```" if cmd else ""
            _update_msg = f"{label_map.get(choice, choice)}{cmd_display}"

            logger.info("Approval callback: %s → %s (session %s), %d resolved",
                         action, choice, session_key[:40], count)

            # update 响应替换卡片内容，同时清空 actions 防止重复点击
            # MM 的 update 只替换 message+props，按钮仍在 — 必须在 props 中返回空 actions
            return {
                "update": {
                    "message": _update_msg,
                    "props": {
                        "attachments": [{
                            "actions": [],  # 清空按钮，防止 Deny 后重复点击
                        }],
                    },
                },
            }

    # ── Clarify 回调处理 ──

    async def _handle_clarify_choice_callback(
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理 Clarify 选项按钮回调。

        用户点击某个选项 → resolve_gateway_clarify → 更新卡片为确认状态。
        """
        from tools.clarify_gateway import resolve_gateway_clarify

        context = payload.get("context", {})
        clarify_id = context.get("clarify_id", "")
        choice_value = context.get("choice_value", "")

        if not clarify_id:
            logger.warning("Clarify choice callback: missing clarify_id")
            return {"ephemeral_text": "⚠️ Invalid clarify callback"}

        resolved = resolve_gateway_clarify(clarify_id, choice_value)
        if not resolved:
            logger.warning(
                "Clarify choice callback: resolve failed (already resolved?) clarify_id=%s",
                clarify_id,
            )
            return {"update": {"message": "⚠️ 此问题已过期", "props": {}}}

        logger.info(
            "Clarify choice callback: resolved clarify_id=%s choice=%r",
            clarify_id, choice_value,
        )

        # 更新原始卡片为确认状态
        card = render_clarify_choice_confirmed_card(choice_value)
        return {
            "update": {
                "message": "",
                "props": card,
            },
        }

    async def _handle_clarify_other_callback(
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理 Clarify「其他」按钮回调。

        标记 clarify 进入文本捕获模式 → 用户下一条消息被 Gateway 拦截为回答。
        """
        from tools.clarify_gateway import mark_awaiting_text

        context = payload.get("context", {})
        clarify_id = context.get("clarify_id", "")

        if not clarify_id:
            logger.warning("Clarify other callback: missing clarify_id")
            return {"ephemeral_text": "⚠️ Invalid clarify callback"}

        ok = mark_awaiting_text(clarify_id)
        if not ok:
            logger.warning(
                "Clarify other callback: mark_awaiting_text failed clarify_id=%s",
                clarify_id,
            )

        logger.info("Clarify other callback: awaiting text clarify_id=%s", clarify_id)

        # 更新原始卡片为「请输入」提示
        card = render_clarify_other_prompt_card()
        return {
            "update": {
                "message": "",
                "props": card,
            },
        }

    # ── 模型切换回调 ──

    async def _handle_model_switch_callback(
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理模型选择回调（支持下拉列表 select + 按钮 button）。

        Select 下拉列表：context 中包含 selected_option 字段（值为 option.value）
        Button 按钮：context 中包含 model_id 字段
        """
        context = payload.get("context", {})

        # 兼容 select 和 button 两种模式
        model_id = context.get("selected_option", "") or context.get("model_id", "")
        session_key = context.get("session_key", "")
        provider_name = context.get("provider_name", "")
        user_id = payload.get("user_id", "")

        logger.info(
            "Model switch callback: model=%s session=%s provider=%s",
            model_id, session_key, provider_name,
        )

        allowed_users = self._get_allowed_users()
        if allowed_users and user_id not in allowed_users:
            return {"ephemeral_text": "Unauthorized"}

        if not model_id or not session_key:
            return {"ephemeral_text": "Missing model_id or session context"}

        # 如果 provider_name 为空（select 模式可能没有注入），从 model_id 解析
        if not provider_name:
            from .models import _resolve_provider_for_model
            provider_name = _resolve_provider_for_model(model_id)

        # 获取旧模型名（用于显示切换路径）
        old_model = self._get_current_model_from_key(session_key)

        success, message = await self._switch_session_model(
            session_key, model_id, provider_name,
        )

        if success:
            old_display = old_model.split("/", 1)[-1] if "/" in old_model else old_model
            new_display = model_id.split("/", 1)[-1] if "/" in model_id else model_id
            return {
                "update": {
                    "message": f"✅ 模型已切换: {old_display or '(default)'} → {new_display}\n💡 重新选择请输入 `/model`",
                    "props": {},
                },
            }
        else:
            return {"ephemeral_text": f"切换失败: {message}"}

    # ── 会话重置回调 ──

    async def _handle_new_confirm_callback(
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理会话重置确认按钮回调。"""
        context = payload.get("context", {})
        session_key = context.get("session_key", "")
        user_id = payload.get("user_id", "")

        allowed_users = self._get_allowed_users()
        if allowed_users and user_id not in allowed_users:
            return {"ephemeral_text": "Unauthorized"}

        if not session_key:
            return {"ephemeral_text": "Missing session context"}

        success, message = await self._reset_session(session_key)

        if success:
            # 只在 message 中放内容，props 清空避免重复
            return {
                "update": {
                    "message": "✅ 会话已重置，新会话已创建，对话上下文已清空。",
                    "props": {},
                },
            }
        else:
            return {"ephemeral_text": f"重置失败: {message}"}

    # ── DM 审批发送 ──

    async def send_exec_approval(
        self,
        chat_id: str,
        command: str,
        session_key: str,
        description: str = "dangerous command",
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> SendResult:
        """发送按钮式审批提示到用户 DM.

        Bot API 创建的帖子 integration 字段虽被 API 响应剥离，
        但数据库中完整保留，MM 服务端处理按钮点击时从 DB 读取，
        因此 Bot API + DM 方式可正常触发回调。
        """
        if not user_id:
            # 替代 patch 8：从 chat_id 反查 DM channel members 推导 user_id
            user_id = await self._get_user_id_from_channel(chat_id)
        if not user_id:
            return SendResult(
                success=False,
                error="Cannot send DM approval without user_id",
            )

        try:
            # 1. 获取/创建 DM channel
            dm_channel_id = await self._get_or_create_dm(user_id)
            if not dm_channel_id:
                return SendResult(
                    success=False,
                    error="Failed to create DM channel",
                )

            # 2. 构建 callback URL
            callback_url = self._callback_url or (
                f"http://{self._callback_bind}:{self._callback_port}"
                f"/mattermost/callback"
            )

            cmd_preview = (
                command[:3800] + "..." if len(command) > 3800 else command
            )

            # 3. 构建 Interactive Message
            attachment = {
                "fallback": f"⚠️ 危险命令需要审批: {command[:100]}",
                "color": "#ff9900",
                "text": (
                    f"```\n{cmd_preview}\n```\n"
                    f"**Reason:** {description}\n\n"
                    f"请点击下方按钮审批或拒绝此操作。"
                ),
                "actions": [
                    {
                        "id": "approveonce",
                        "name": "Allow Once",
                        "type": "button",
                        "style": "primary",
                        "integration": {
                            "url": callback_url,
                            "context": {
                                "action": "approve_once",
                                "session_key": session_key,
                                "command": command,
                            },
                        },
                    },
                    {
                        "id": "approvesession",
                        "name": "Allow Session",
                        "type": "button",
                        "integration": {
                            "url": callback_url,
                            "context": {
                                "action": "approve_session",
                                "session_key": session_key,
                                "command": command,
                            },
                        },
                    },
                    {
                        "id": "approvealways",
                        "name": "Always Allow",
                        "type": "button",
                        "integration": {
                            "url": callback_url,
                            "context": {
                                "action": "approve_always",
                                "session_key": session_key,
                                "command": command,
                            },
                        },
                    },
                    {
                        "id": "deny",
                        "name": "Deny",
                        "type": "button",
                        "style": "danger",
                        "integration": {
                            "url": callback_url,
                            "context": {
                                "action": "deny",
                                "session_key": session_key,
                            },
                        },
                    },
                ],
            }

            # 4. 通过 Bot API 发送到 DM（props.attachments）
            payload = {
                "channel_id": dm_channel_id,
                "message": "⚠️ 危险命令需要审批",
                "props": {"attachments": [attachment]},
            }

            data = await self._api_post("posts", payload)
            if not data or "id" not in data:
                return SendResult(
                    success=False, error="Failed to send DM approval post"
                )

            # 5. 在原频道/Thread 发送简短提示（带上 metadata 确保路由到正确 Thread）
            await self.send(
                chat_id,
                "⏳ 已向您发送私信，请在 DM 中审批危险命令。",
                metadata=metadata,
            )

            return SendResult(success=True, message_id=data.get("id"))

        except Exception as e:
            logger.error(
                "[Mattermost] send_exec_approval failed: %s",
                e,
                exc_info=True,
            )
            return SendResult(success=False, error=str(e))

    # ══════════════════════════════════════════════════════════════════════
    # 核心操作：模型切换 + 会话重置
    # ══════════════════════════════════════════════════════════════════════

    def _get_current_model_from_key(self, session_key: str) -> str:
        """从 session override 或 config 获取当前模型名。"""
        try:
            from gateway.run import _gateway_runner_ref
            runner = _gateway_runner_ref()
            if runner:
                override = runner._session_model_overrides.get(session_key, {})
                if override:
                    return override.get("model", "")
        except Exception:
            pass

        try:
            from hermes_cli.config import load_config
            cfg = load_config()
            return cfg.get("model", {}).get("default", "")
        except Exception:
            return ""

    async def _switch_session_model(
        self, session_key: str, model_id: str, provider_name: str,
    ) -> Tuple[bool, str]:
        """执行模型切换 — 直接从 custom_providers 配置构建 session override。

        绕过 switch_model() 的复杂路由逻辑，直接读取 provider 配置。
        这确保 api_key 正确解析、响应速度快、provider 正确匹配。
        """
        try:
            from gateway.run import _gateway_runner_ref
            runner = _gateway_runner_ref()
            if not runner:
                return False, "GatewayRunner not available"

            # 从 custom_providers 配置直接解析 provider 连接信息
            from .models import resolve_provider_config
            prov_cfg = resolve_provider_config(provider_name)

            # 先记录旧模型（必须在写入 override 之前）
            old_model = self._get_current_model_from_key(session_key) or "(default)"

            if prov_cfg:
                # 直接构建 override — 无需调用 switch_model
                runner._session_model_overrides[session_key] = {
                    "model": model_id,
                    "provider": prov_cfg["provider"],
                    "base_url": prov_cfg["base_url"],
                    "api_key": prov_cfg["api_key"],
                    "api_mode": prov_cfg["api_mode"],
                }
            else:
                # provider 不在 custom_providers 中 — 回退到 switch_model
                logger.warning(
                    "Provider '%s' not in custom_providers, falling back to switch_model for %s",
                    provider_name, model_id,
                )
                from hermes_cli.config import load_config
                cfg = load_config()
                model_cfg = cfg.get("model", {})
                user_provs = cfg.get("providers")
                try:
                    from hermes_cli.config import get_compatible_custom_providers
                    custom_provs = get_compatible_custom_providers(cfg)
                except Exception:
                    custom_provs = cfg.get("custom_providers")

                override = runner._session_model_overrides.get(session_key, {})
                current_provider = override.get("provider", model_cfg.get("provider", "openrouter"))
                current_model = override.get("model", model_cfg.get("default", ""))
                current_base_url = override.get("base_url", model_cfg.get("base_url", ""))
                current_api_key = override.get("api_key", "")

                from hermes_cli.model_switch import switch_model
                result = switch_model(
                    raw_input=model_id,
                    current_provider=current_provider,
                    current_model=current_model,
                    current_base_url=current_base_url,
                    current_api_key=current_api_key,
                    user_providers=user_provs,
                    custom_providers=custom_provs,
                    explicit_provider=provider_name or None,
                )

                if not result.success:
                    return False, result.error_message or "switch_model failed"

                runner._session_model_overrides[session_key] = {
                    "model": result.new_model,
                    "provider": result.target_provider,
                    "base_url": result.base_url,
                    "api_key": result.api_key,
                    "api_mode": result.api_mode,
                }

            # 清除缓存的 agent
            runner._evict_cached_agent(session_key)

            # 注入 model note — 让 LLM 知道自己被切换了
            # 这样 LLM 回答"当前模型"时会正确报告新模型
            if not hasattr(runner, "_pending_model_notes"):
                runner._pending_model_notes = {}
            _verify = runner._session_model_overrides.get(session_key, {})
            _new_provider = _verify.get("provider", provider_name)
            runner._pending_model_notes[session_key] = (
                f"[Note: model was just switched from {old_model} to {model_id} "
                f"via {_new_provider}. "
                f"Adjust your self-identification accordingly.]"
            )

            # 验证 override 是否真的写入了
            verify = runner._session_model_overrides.get(session_key)
            if verify:
                logger.info(
                    "Model switched: session=%s → %s provider=%s api_key_len=%d override_verified=YES",
                    session_key, model_id,
                    verify.get("provider", "?"),
                    len(verify.get("api_key", "")),
                )
            else:
                logger.error(
                    "Model switch FAILED to persist: session=%s model=%s override_keys=%s",
                    session_key, model_id,
                    list(runner._session_model_overrides.keys())[:5],
                )
            return True, model_id

        except Exception as e:
            logger.error("Model switch failed: %s", e, exc_info=True)
            return False, str(e)

    async def _reset_session(self, session_key: str) -> Tuple[bool, str]:
        """执行会话重置，通过 GatewayRunner。"""
        try:
            from gateway.run import _gateway_runner_ref
            runner = _gateway_runner_ref()
            if not runner:
                return False, "GatewayRunner not available"

            # 清除 session override
            runner._session_model_overrides.pop(session_key, None)

            # 清除缓存 agent
            runner._evict_cached_agent(session_key)

            # 重置 session store
            if hasattr(runner, "session_store"):
                runner.session_store.reset_session(session_key)

            # 清除 reasoning override
            if hasattr(runner, "_set_session_reasoning_override"):
                runner._set_session_reasoning_override(session_key, None)

            # 清除 pending model notes
            if hasattr(runner, "_pending_model_notes"):
                runner._pending_model_notes.pop(session_key, None)

            # 清除 session boundary security state
            if hasattr(runner, "_clear_session_boundary_security_state"):
                runner._clear_session_boundary_security_state(session_key)

            logger.info("Session reset: session=%s", session_key)
            return True, "Session reset"

        except Exception as e:
            logger.error("Session reset failed: %s", e, exc_info=True)
            return False, str(e)

    # ══════════════════════════════════════════════════════════════════════
    # Gateway 标准钩子（forward compat，当前因 Mattermost 拦截 / 不会触发）
    # ══════════════════════════════════════════════════════════════════════

    async def send_model_picker(
        self,
        chat_id: str,
        providers: list,
        current_model: str,
        current_provider: str,
        session_key: str,
        on_model_selected: Callable[[str, str, str], Coroutine[Any, Any, str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Gateway 标准 hook — 当前 Mattermost 拦截 / 消息，此方法不会被调用。
        保留用于未来兼容（如 Mattermost 改进 Slash Command 支持时）。
        """
        return SendResult(success=False, error="Use Slash Command /model instead")

    # ══════════════════════════════════════════════════════════════════════
    # 回调服务器辅助方法
    # ══════════════════════════════════════════════════════════════════════

    async def _stop_callback_server(self) -> None:
        """停止 callback server."""
        if self._callback_server:
            self._callback_server.close()
            await self._callback_server.wait_closed()
            self._callback_server = None
            logger.info("Mattermost callback server stopped")

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """HMAC-SHA256 校验 Mattermost 回调签名."""
        import hmac as _hmac
        import hashlib as _hashlib

        if not self._callback_secret:
            return True

        expected = _hmac.new(
            self._callback_secret.encode("utf-8"),
            body,
            _hashlib.sha256,
        ).hexdigest()

        return _hmac.compare_digest(expected, signature)

    # ══════════════════════════════════════════════════════════════════════
    # 父类方法覆写（修复内置适配器的 Bug）
    # ══════════════════════════════════════════════════════════════════════

    async def send_typing(self, chat_id: str, metadata: Optional[Dict[str, Any]] = None):
        """覆写父类：将 typing 指示器发送到正确的 Thread 内。

        内置 MattermostAdapter.send_typing() 只传 channel_id，
        在 reply_mode=thread 时 typing 指示器错误地显示在频道而非 Thread 内。
        Mattermost API 支持 parent_id 参数指定 Thread。
        """
        body: Dict[str, Any] = {"channel_id": chat_id}
        if metadata and metadata.get("thread_id"):
            body["parent_id"] = metadata["thread_id"]
        await self._api_post(f"users/{self._bot_user_id}/typing", body)

    # ══════════════════════════════════════════════════════════════════════
    # 生命周期覆写（启动/停止回调服务器）
    # ══════════════════════════════════════════════════════════════════════

    async def connect(self) -> bool:
        """Connect to Mattermost — 覆写父类，追加回调服务器启动."""
        import asyncio

        # 先调用内置 connect（认证 + WebSocket）
        result = await super().connect()
        if not result:
            return False

        # 启动审批 + Slash 指令回调服务器
        await self._start_callback_server()
        return True

    async def disconnect(self) -> None:
        """Disconnect from Mattermost — 覆写父类，追加回调服务器停止."""
        # 先停止回调服务器
        await self._stop_callback_server()

        # 再调用内置 disconnect
        await super().disconnect()

    # ══════════════════════════════════════════════════════════════════════
    # Thread root_id 解析（替代 patch 6）
    # ══════════════════════════════════════════════════════════════════════

    async def _resolve_root_id(self, post_id: str) -> Optional[str]:
        """Resolve a post_id to the thread root_id for Mattermost.

        Mattermost requires root_id to be the *root* post of a thread.
        If the post is a reply (has its own root_id), we must use that
        root_id instead. Using a reply's own ID as root_id causes
        "Invalid RootId parameter" errors.

        Returns None when resolution fails (API error, network issue) —
        callers MUST skip root_id in that case to avoid 400 errors.
        """
        if not post_id:
            return None
        try:
            data = await self._api_get(f"posts/{post_id}")
        except Exception:
            logger.warning(
                "Mattermost: _resolve_root_id — API call failed for post=%s, "
                "skipping thread routing",
                post_id, exc_info=True,
            )
            return None

        if data is None:
            logger.warning(
                "Mattermost: _resolve_root_id — API returned None for post=%s, "
                "skipping thread routing",
                post_id,
            )
            return None

        root_id = data.get("root_id")
        # root_id can be "" (empty string = this post IS the root).
        # Only use data["root_id"] when it's a non-empty string pointing
        # to a different post.
        if isinstance(root_id, str) and root_id:
            logger.info(
                "Mattermost: _resolve_root_id — input=%s root_id=%s (reply → use root)",
                post_id, root_id,
            )
            return root_id

        # root_id is "" or missing → this post IS the thread root.
        logger.info(
            "Mattermost: _resolve_root_id — input=%s is_root=True (root_id=%r)",
            post_id, root_id,
        )
        return post_id

    async def _get_thread_root_id(self, reply_to: Optional[str]) -> Optional[str]:
        """Resolve reply_to → thread root_id when in thread mode."""
        if reply_to and self._reply_mode == "thread":
            return await self._resolve_root_id(reply_to)
        return None

    # ══════════════════════════════════════════════════════════════════════
    # send() 覆写 — 添加 _resolve_root_id（替代 patch 6a）
    # ══════════════════════════════════════════════════════════════════════

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """覆写父类 send()：将 root_id 解析为 thread 根帖子 ID."""
        if not content:
            return SendResult(success=True)

        # ── Footer 拦截：编辑上一条消息而非独立发帖 ──
        if self._is_footer_line(content):
            tracked = self._tracked_posts.get(chat_id)
            if tracked:
                post_id, _prev_content = tracked
                # 实时拉取当前帖子内容（流式模式下 send() 收到的 content 不完整）
                current = await self._api_get(f"posts/{post_id}")
                current_text = current.get("message", "") if isinstance(current, dict) else ""
                if not current_text:
                    logger.warning(
                        "Mattermost: footer edit skipped — failed to fetch post=%s content",
                        post_id,
                    )
                    # 降级：回退为正常发送
                else:
                    footer_text = content.replace(" · ", " ")
                    footer_md = f"`── {footer_text} ──`"
                    edited = f"{current_text}\n\n{footer_md}"
                    result = await self._api_put(f"posts/{post_id}", {
                        "id": post_id,
                        "message": edited,
                    })
                    if result and result.get("id"):
                        self._tracked_posts[chat_id] = (post_id, edited)
                        return SendResult(success=True, message_id=post_id)
                    logger.warning(
                        "Mattermost: footer edit failed for post=%s, "
                        "fallback to normal send",
                        post_id,
                    )
            # 无追踪帖子或编辑/拉取失败 → 正常发送（降级）

        formatted = self.format_message(content)
        chunks = self.truncate_message(formatted, MAX_POST_LENGTH)

        last_id = None
        for chunk in chunks:
            payload: Dict[str, Any] = {
                "channel_id": chat_id,
                "message": chunk,
            }
            if reply_to and self._reply_mode == "thread":
                root_id = await self._resolve_root_id(reply_to)
                if root_id:
                    payload["root_id"] = root_id
                    logger.info(
                        "Mattermost: send() threading — reply_to=%s resolved_root=%s "
                        "reply_mode=%s chat_id=%s",
                        reply_to, root_id, self._reply_mode, chat_id,
                    )
                elif metadata and metadata.get("thread_id"):
                    # _resolve_root_id 失败时降级使用 metadata.thread_id，
                    # 避免消息落到频道级（而非正确的 Thread）。
                    payload["root_id"] = str(metadata["thread_id"])
                    logger.warning(
                        "Mattermost: send() — _resolve_root_id returned None for "
                        "reply_to=%s, falling back to metadata.thread_id=%s",
                        reply_to, metadata["thread_id"],
                    )
                else:
                    logger.warning(
                        "Mattermost: send() — _resolve_root_id returned None for "
                        "reply_to=%s, no metadata fallback — sending without thread routing",
                        reply_to,
                    )
            elif self._reply_mode == "thread" and metadata and metadata.get("thread_id"):
                # 替代 patch 8b：reply_to 未提供时降级使用 metadata.thread_id。
                # 工具进度消息等场景下 _progress_reply_to 为 None，但
                # _progress_metadata 中已携带 thread_id（= source.thread_id），
                # 在 Mattermost 中即为 root post ID，无需额外解析。
                payload["root_id"] = str(metadata["thread_id"])
                logger.info(
                    "Mattermost: send() threading from metadata fallback — "
                    "thread_id=%s chat_id=%s",
                    payload["root_id"], chat_id,
                )
            elif reply_to and self._reply_mode != "thread":
                logger.info(
                    "Mattermost: send() reply_to present but reply_mode=%s (not 'thread') — "
                    "skipping root_id — reply_to=%s chat_id=%s",
                    self._reply_mode, reply_to, chat_id,
                )

            data = await self._api_post("posts", payload)
            if not data or "id" not in data:
                return SendResult(success=False, error="Failed to create post")
            last_id = data["id"]

        # 追踪非 footer 帖子（用于后续 footer 编辑合并到上一条消息）
        if last_id and not self._is_footer_line(content):
            self._tracked_posts[chat_id] = (last_id, content)

        return SendResult(success=True, message_id=last_id)

    # ══════════════════════════════════════════════════════════════════════
    # send_clarify() 覆写 — 渲染交互卡片替代纯文本（替代 base.send_clarify）
    # ══════════════════════════════════════════════════════════════════════

    async def send_clarify(
        self,
        chat_id: str,
        question: str,
        choices: Optional[list],
        clarify_id: str,
        session_key: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """覆写 base.send_clarify()：用 MM interactive card 渲染选项按钮。

        - 有 choices → 每个选项渲染为一个按钮 + 「其他」按钮
        - 无 choices → 纯文本提问，Gateway text-intercept 自动捕获回复
        """
        callback_url = self._callback_url or (
            f"http://{self._callback_bind}:{self._callback_port}/mattermost/callback"
        )
        logger.info(
            "Mattermost: send_clarify — callback_url=%r _callback_url=%r card_choices=%d",
            callback_url, self._callback_url,
            len(choices) if choices else 0,
        )

        # 从 metadata 中提取 channel_id（兼容不同调用方）
        channel_id_for_card = chat_id

        card = render_clarify_card(
            question=question,
            choices=list(choices) if choices else None,
            clarify_id=clarify_id,
            session_key=session_key,
            callback_url=callback_url,
            channel_id=channel_id_for_card,
            user_id="",  # user_id 不需要在 clarify 卡片中
        )

        # 通过 Bot API 发送交互卡片到 thread
        root_id = None
        if metadata and metadata.get("thread_id"):
            root_id = await self._get_thread_root_id(metadata["thread_id"])

        post_id = await self._post_card_in_thread(chat_id, root_id, card)

        if post_id:
            # 保存 post_id → clarify_id 映射，供回调时更新卡片
            if not hasattr(self, "_clarify_posts"):
                self._clarify_posts: Dict[str, str] = {}
            self._clarify_posts[clarify_id] = post_id

            logger.info(
                "Mattermost: send_clarify — question=%r clarify_id=%s post_id=%s",
                question[:60], clarify_id, post_id,
            )
            return SendResult(success=True, message_id=post_id)

        # 降级：Bot API 失败时回退到纯文本
        logger.warning("Mattermost: send_clarify card post failed, falling back to text")
        return await super().send_clarify(
            chat_id=chat_id,
            question=question,
            choices=choices,
            clarify_id=clarify_id,
            session_key=session_key,
            metadata=metadata,
        )

    # ══════════════════════════════════════════════════════════════════════
    # _send_local_file() 覆写 — MEDIA 静默跳过 + _resolve_root_id（替代 patch 6c + 10c）
    # ══════════════════════════════════════════════════════════════════════

    async def _send_local_file(
        self,
        chat_id: str,
        file_path: str,
        caption: Optional[str],
        reply_to: Optional[str],
        file_name: Optional[str] = None,
    ) -> SendResult:
        """覆写父类 _send_local_file：文件不存在时静默跳过 + Thread root_id 解析."""
        import mimetypes
        from pathlib import Path as _Path

        p = _Path(file_path)
        if not p.exists():
            # 替代 patch 10c：静默跳过，不发噪声消息到频道
            logger.warning(
                "Mattermost: local file not found, skipping: %s", file_path
            )
            return SendResult(success=True, message_id=None)

        fname = file_name or p.name
        ct = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        file_data = p.read_bytes()

        file_id = await self._upload_file(chat_id, file_data, fname, ct)
        if not file_id:
            return SendResult(success=False, error="File upload failed")

        payload: Dict[str, Any] = {
            "channel_id": chat_id,
            "message": caption or "",
            "file_ids": [file_id],
        }
        root_id = await self._get_thread_root_id(reply_to)
        if root_id:
            payload["root_id"] = root_id

        data = await self._api_post("posts", payload)
        if not data or "id" not in data:
            return SendResult(success=False, error="Failed to post with file")
        return SendResult(success=True, message_id=data["id"])

    # ══════════════════════════════════════════════════════════════════════
    # _send_url_as_file() 覆写 — 添加 _resolve_root_id（替代 patch 6b）
    # ══════════════════════════════════════════════════════════════════════

    async def _send_url_as_file(
        self,
        chat_id: str,
        url: str,
        caption: Optional[str],
        reply_to: Optional[str],
        kind: str = "file",
    ) -> SendResult:
        """覆写父类 _send_url_as_file：添加 Thread root_id 解析."""
        from tools.url_safety import is_safe_url
        if not is_safe_url(url):
            logger.warning("Mattermost: blocked unsafe URL (SSRF protection)")
            return await self.send(chat_id, f"{caption or ''}\n{url}".strip(), reply_to)

        import aiohttp

        file_data = None
        ct = "application/octet-stream"
        fname = url.rsplit("/", 1)[-1].split("?")[0] or f"{kind}.png"

        for attempt in range(3):
            try:
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status >= 500 or resp.status == 429:
                        if attempt < 2:
                            logger.debug("Mattermost download retry %d/2 for %s (status %d)",
                                         attempt + 1, url[:80], resp.status)
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                    if resp.status >= 400:
                        return await self.send(chat_id, f"{caption or ''}\n{url}".strip(), reply_to)
                    file_data = await resp.read()
                    ct = resp.content_type or "application/octet-stream"
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                logger.warning("Mattermost: failed to download %s after %d attempts: %s", url, attempt + 1, exc)
                return await self.send(chat_id, f"{caption or ''}\n{url}".strip(), reply_to)

        if file_data is None:
            logger.warning("Mattermost: download returned no data for %s", url)
            return await self.send(chat_id, f"{caption or ''}\n{url}".strip(), reply_to)

        file_id = await self._upload_file(chat_id, file_data, fname, ct)
        if not file_id:
            return await self.send(chat_id, f"{caption or ''}\n{url}".strip(), reply_to)

        payload: Dict[str, Any] = {
            "channel_id": chat_id,
            "message": caption or "",
            "file_ids": [file_id],
        }
        root_id = await self._get_thread_root_id(reply_to)
        if root_id:
            payload["root_id"] = root_id

        data = await self._api_post("posts", payload)
        if not data or "id" not in data:
            return SendResult(success=False, error="Failed to post with file")
        return SendResult(success=True, message_id=data["id"])
