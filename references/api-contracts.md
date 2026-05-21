# Mattermost Interactive Message & Slash Command API 契约

> 关联：Hermes Platform Plugin `mattermost-enhancer`
> 版本：1.0.0 | 最后更新：2026-05-22

## 1. Slash Command POST（`/model` / `/new`）

Mattermost System Console 配置的自定义 Slash 指令 → 插件 callback server。

### 1.1 请求格式

```
POST /mm-command
Content-Type: application/x-www-form-urlencoded

token=<system_concole_token>
team_id=<team_id>
team_domain=<team_domain>
channel_id=<channel_id>
channel_name=<channel_name>
user_id=<user_id>
user_name=<user_name>
command=/model               # 或 /new
text=                        # 指令后的可选文本
trigger_id=<trigger_id>
root_id=<root_post_id>       # ← 关键字段！Thread 中 = root post ID，Channel 顶层 = ""
```

**root_id 字段说明（MM 原生支持）：**

| 发送位置 | root_id 值 | session_key 格式 |
|---------|-----------|-----------------|
| Channel 顶层 | `""`（空字符串） | `agent:main:mattermost:group:<channel_id>` |
| Thread 内 | `"twcryzndejf15px8cuhy43sx4a"` | `agent:main:mattermost:group:<channel_id>:<root_id>` |

### 1.2 响应格式

**正常响应（返回空 ephemeral，Bot API 发帖）：**
```json
{}
```

**或**
```json
{"response_type": "ephemeral", "text": "🔄 模型选择器已发送"}
```

**权限拒绝：**
```json
{"response_type": "ephemeral", "text": "⛔ Unauthorized"}
```

**错误：**
```json
{"response_type": "ephemeral", "text": "❌ 发送失败，请稍后重试"}
```

### 1.3 设计原则

- Slash Command HTTP 响应以**用户身份**发送 → 卡片改用 **Bot API** `_api_post("posts", ...)` 发帖
- 避免 `in_channel` 响应 + Bot API 帖子双重显示
- Bot API 帖子以 Bot 头像显示，用户体验一致

---

## 2. Interactive Message 按钮回调

### 2.1 请求格式

```
POST /mattermost/callback
Content-Type: application/json
X-Mattermost-Signature: <hmac_sha256_hex>   # 如果配置了 MATTERMOST_CALLBACK_SECRET

{
  "context": {
    "action": "<action_name>",
    "session_key": "agent:main:mattermost:group:...",
    "<other_context_fields>..."
  },
  "user_id": "<user_id>",
  "post_id": "<post_id>",
  "channel_id": "<channel_id>",
  "trigger_id": "<trigger_id>"
}
```

### 2.2 响应格式

**更新帖子（替换内容，清空按钮）：**
```json
{
  "update": {
    "message": "✅ 审批通过",
    "props": {
      "attachments": [{"actions": []}]
    }
  }
}
```

**ephemeral 提示：**
```json
{"ephemeral_text": "Unauthorized"}
```

### 2.3 Action 命名约定

| action | action_id | 功能 | context 参数 |
|--------|-----------|------|-------------|
| `approve_once` | `approveonce` | 允许本次 | `session_key`, `command` |
| `approve_session` | `approvesession` | 本 session 全部允许 | `session_key`, `command` |
| `approve_always` | `approvealways` | 永久允许 | `session_key`, `command` |
| `deny` | `deny` | 拒绝本次 | `session_key`, `command` |
| `cmd_model_switch` | `cmdmodelselect` | 切换模型（select） | `selected_option`, `session_key`, `channel_id`, `user_id` |
| `cmd_new_confirm` | `cmdnewconfirm` | 确认创建新会话 | `session_key` |
| `cmd_new_cancel` | `cmdnewcancel` | 取消创建新会话 | - |

**约束：** action_id 必须**纯字母**，连字符/下划线会被 Mattermost 拒绝。

---

## 3. 卡片格式（Interactive Message Attachments）

### 3.1 Button 模式（DM 审批）

```json
{
  "attachments": [{
    "pretext": "⚠️ 危险命令需要审批",
    "text": "```\n<command>\n```\n**Reason:** dangerous command",
    "color": "#ff9900",
    "actions": [
      {
        "id": "approveonce",
        "name": "Allow Once",
        "type": "button",
        "style": "primary",
        "integration": {
          "url": "http://host:18065/mattermost/callback",
          "context": {
            "action": "approve_once",
            "session_key": "agent:main:mattermost:group:...",
            "command": "<dangerous_command>"
          }
        }
      }
    ]
  }]
}
```

### 3.2 Select 模式（模型选择器）

```json
{
  "attachments": [{
    "pretext": "🔄 切换模型",
    "text": "当前: **zenmux/minimax-m2.7**\n从下拉列表中选择目标模型：",
    "color": "#2196F3",
    "footer": "⚠️ 仅影响当前 Thread",
    "actions": [{
      "id": "cmdmodelselect",
      "name": "当前: zenmux/minimax-m2.7",
      "type": "select",
      "options": [
        {"text": "★ zenmux/minimax-m2.7", "value": "zenmux/minimax-m2.7"},
        {"text": "deepseek/deepseek-v4-pro", "value": "deepseek/deepseek-v4-pro"}
      ],
      "integration": {
        "url": "http://host:18065/mattermost/callback",
        "context": {
          "action": "cmd_model_switch",
          "session_key": "agent:main:mattermost:group:...",
          "channel_id": "...",
          "user_id": "..."
        }
      }
    }]
  }]
}
```

**关键：** Mattermost select 不支持默认选中。当前模型用 `name` 字段作为 placeholder（如 `"当前: zenmux/minimax-m2.7"`），当前选项加 `★` 前缀。

---

## 4. Mattermost 限制

| 限制 | 值 | 影响 |
|------|---|------|
| 每 attachment 最多 actions | 5 | button 模式需分组 |
| 每 message 最多 attachments | 5 | 最多 25 按钮 |
| action_id 格式 | 纯字母（无 `-` `_`） | 如 `cmdmodelswitch` |
| select 组件 | 不限选项数 | ✅ 推荐用于长模型列表 |
| Slash Command 响应身份 | 用户身份 | Bot API 代发卡片 |
| `in_channel` + ephemeral_text | 双重显示 | 返回空 `{}` |
| Bot API 响应 strips integration | API 返回无 `integration` | DB 中保留 → 按钮回调有效 |

---

## 5. 卡片更新机制

**MM Interactive Message 响应 `update` 字段替换消息内容：**

- `update.message` → 替换帖子正文
- `update.props` → 替换帖子 props（含 `attachments`）
- **按钮保留规则：** 如果 `props.attachments[].actions` 为空数组 `[]`，所有按钮被移除
- **不返回 `update.props` →** 原始按钮保留（可能导致 Deny 后重复点击）

**正确用法（Deny 后防重复点击）：**
```json
{
  "update": {
    "message": "❌ Denied",
    "props": {"attachments": [{"actions": []}]}
  }
}
```

---

## 6. 回调签名验证

HMAC-SHA256 对回调 body 签名，放在 `X-Mattermost-Signature` 头。

```
HMAC-SHA256(key=MATTERMOST_CALLBACK_SECRET, message=request body bytes) → hex digest
```

- 未配置 `MATTERMOST_CALLBACK_SECRET` → 跳过验证
- 无签名头或签名不匹配 → `401 Unauthorized`

---

## 7. 回调服务器路由

| 路由 | 方法 | Content-Type | 来源 | 处理 |
|------|------|-------------|------|------|
| `/mattermost/callback` | POST | `application/json` | Interactive Message 按钮 | `_route_callback()` → `_handle_callback()` |
| `/mm-command` | POST | `application/x-www-form-urlencoded` | Slash Command | `_route_slash_command()` → `_handle_model_command()` / `_handle_new_command()` |

**生命周期：** `connect()` → `asyncio.start_server()` / `disconnect()` → `_stop_callback_server()`

---

## 8. Bot API 发帖

```python
POST /api/v4/posts
Authorization: Bearer <MATTERMOST_TOKEN>
Content-Type: application/json

{
  "channel_id": "<dm_channel_id>",
  "message": "",
  "props": {"attachments": [{...}]}
}
```

**关键行为：**
- `message` + `props.attachments` 双重渲染 → `message` 留空避免
- `root_id` 参数指定 Thread → 卡片进 Thread
- API 响应 strips `integration` → DB 保留完整
- DM channel: `POST /api/v4/channels/direct` → `[bot_user_id, user_id]`
