"""
Mattermost Interactive Message 卡片渲染。

改进：模型选择器使用 select 下拉列表（一个 attachment，一个 action），
而非多行按钮。更整洁、更省空间。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Mattermost 限制
_MAX_ACTIONS_PER_ATTACHMENT = 5
_MAX_ATTACHMENTS = 5


def _make_button(
    action_id: str,
    name: str,
    context: Dict[str, Any],
    callback_url: str,
    style: str = "",
) -> Dict[str, Any]:
    """构建单个按钮的 integration 定义。"""
    button: Dict[str, Any] = {
        "id": action_id,
        "name": name,
        "type": "button",
        "integration": {
            "url": callback_url,
            "context": context,
        },
    }
    if style:
        button["style"] = style
    return button


def _make_select(
    action_id: str,
    name: str,
    options: List[Dict[str, str]],
    context: Dict[str, Any],
    callback_url: str,
) -> Dict[str, Any]:
    """构建 select 下拉列表的 integration 定义。

    options: [{"text": "显示名", "value": "实际值"}, ...]
    当用户选择某个选项时，MM 发送回调，context 中会包含 "selected_option" 字段。
    """
    return {
        "id": action_id,
        "name": name,
        "type": "select",
        "options": options,
        "integration": {
            "url": callback_url,
            "context": context,
        },
    }


def _make_attachment(
    pretext: str,
    text: str,
    actions: List[Dict[str, Any]],
    color: str = "",
    footer: str = "",
) -> Dict[str, Any]:
    """构建单个 attachment。"""
    att: Dict[str, Any] = {
        "text": text,
        "actions": actions,
    }
    if pretext:
        att["pretext"] = pretext
    if color:
        att["color"] = color
    if footer:
        att["footer"] = footer
    return att


# ═══════════════════════════════════════════════════════════════════════════
# 模型选择卡片 (/model) — 下拉列表模式
# ═══════════════════════════════════════════════════════════════════════════

def render_model_selector_card(
    *,
    callback_url: str,
    channel_id: str,
    user_id: str,
    current_model: str = "",
    available_models: Optional[List[str]] = None,
    provider_groups: Optional[List[Tuple[str, str, List[str]]]] = None,
) -> Dict[str, Any]:
    """渲染模型选择卡片（下拉列表模式）。

    使用 Mattermost 的 select 类型 action，所有模型在一个下拉列表中。
    当前使用的模型在选项中标记 ★ 前缀。
    按 provider 分组显示（optgroup 效果通过选项前缀模拟）。
    """
    # 构建选项列表
    options = []

    if provider_groups:
        for prov_name, prov_label, model_ids in provider_groups:
            short_prov = prov_name.split("/")[-1] if "/" in prov_name else prov_name

            for model_id in model_ids:
                # 显示格式：provider/model-name（如 zenmux/minimax-m2.7）
                display = model_id  # 保持完整的 provider/model 格式
                is_current = (model_id == current_model)
                prefix = "★ " if is_current else ""
                text = f"{prefix}{display}"
                options.append({
                    "text": text,
                    "value": model_id,
                })
    elif available_models:
        for model_id in available_models:
            is_current = (model_id == current_model)
            prefix = "★ " if is_current else ""
            text = f"{prefix}{model_id}"
            options.append({
                "text": text,
                "value": model_id,
            })

    if not options:
        return {"response_type": "ephemeral", "text": "没有可用的模型"}

    # 构建 select action
    # name 字段在 MM 中显示为 placeholder（下拉列表未展开时的文本）
    # 格式：当前模型名（如 "当前: zenmux/minimax-m2.7"）
    current_short = current_model.split("/", 1)[-1] if "/" in current_model else current_model
    select = _make_select(
        action_id="cmdmodelselect",
        name=f"当前: {current_model}",
        options=options,
        context={
            "action": "cmd_model_switch",
            "channel_id": channel_id,
            "user_id": user_id,
        },
        callback_url=callback_url,
    )

    current_display = current_model  # 显示完整格式（如 zenmux/minimax-m2.7）
    attachment = _make_attachment(
        pretext="🔄 切换模型",
        text=f"当前: **{current_display}**\n从下拉列表中选择目标模型：",
        actions=[select],
        color="#2196F3",
        footer="⚠️ 仅影响当前 Thread",
    )

    return {
        "response_type": "in_channel",
        "attachments": [attachment],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 新会话确认卡片 (/new)
# ═══════════════════════════════════════════════════════════════════════════

def render_new_session_confirm_card(
    *,
    callback_url: str,
    channel_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """渲染新会话确认卡片。"""
    actions = [
        _make_button(
            action_id="cmdnewconfirm",
            name="✅ 确认重置",
            context={
                "action": "cmd_new_confirm",
                "channel_id": channel_id,
                "user_id": user_id,
            },
            callback_url=callback_url,
            style="danger",
        ),
        _make_button(
            action_id="cmdnewcancel",
            name="❌ 取消",
            context={
                "action": "cmd_new_cancel",
            },
            callback_url=callback_url,
        ),
    ]

    attachment = _make_attachment(
        pretext="🆕 创建新会话",
        text="将重置当前 session 的对话上下文\n⚠️ 之前的对话历史将丢失",
        actions=actions,
        color="#F44336",
        footer="💡 Thread 模式下直接发新消息即可创建新会话",
    )

    return {
        "response_type": "in_channel",
        "attachments": [attachment],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 操作成功反馈卡片
# ═══════════════════════════════════════════════════════════════════════════

def render_switch_success_card(
    old_model: str,
    new_model: str,
) -> Dict[str, Any]:
    """模型切换成功确认卡片。"""
    old_display = old_model.split("/", 1)[-1] if "/" in old_model else old_model
    new_display = new_model.split("/", 1)[-1] if "/" in new_model else new_model
    attachment = _make_attachment(
        pretext="",
        text=f"✅ **{old_display or '(default)'}** → **{new_display}**\n当前 Thread 内生效",
        actions=[],
        color="#4CAF50",
    )
    return {
        "response_type": "in_channel",
        "attachments": [attachment],
    }


def render_reset_success_card() -> Dict[str, Any]:
    """会话重置成功确认卡片。"""
    attachment = _make_attachment(
        pretext="",
        text="✅ 会话已重置，新会话已创建，对话上下文已清空。",
        actions=[],
        color="#4CAF50",
    )
    return {
        "response_type": "in_channel",
        "attachments": [attachment],
    }
