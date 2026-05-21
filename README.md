# mattermost-enhancer

Mattermost 增强插件 for Hermes Agent — 将 DM 审批、模型切换、会话重置等功能以 Interactive Message 卡片交互方式集成到 Mattermost 工作流中。

## 功能

| 功能 | 触发方式 | 说明 |
|------|---------|------|
| **DM 审批** | 执行高危命令自动触发 | Allow Once / Allow Session / Always Allow / Deny，按钮卡片交互 |
| **模型切换** | `/model` Slash Command | 下拉列表选择任意模型，仅影响当前 Thread |
| **会话重置** | `/new` Slash Command | 清除模型 override 和 agent 缓存，开始新会话 |

## 架构

```
Mattermost 服务端
  ├── 自定义 Slash 指令
  │     /model → POST /mm-command
  │     /new   → POST /mm-command
  └── Interactive Message 回调
        → POST /mattermost/callback

Hermes Plugin: mattermost-enhancer (platform)
  ├── adapter.py        # MattermostApprovalAdapter，覆盖内置适配器
  ├── cards.py          # 模型选择器 / 新会话确认卡片
  ├── models.py         # 模型列表管理（从 config.yaml providers 获取）
  ├── session.py        # Session 定位与操作
  └── callback_server.py # HTTP 回调服务器
```

## 安装

### 前置条件

- Hermes Agent ≥ 0.14.0
- Mattermost 服务端（自部署或 Cloud）
- Mattermost Bot 账号（需 `post:all` 权限）

### 步骤

1. **复制插件**

```bash
cp -r mattermost-enhancer ~/.hermes/plugins/mattermost-enhancer
```

2. **启用插件**

编辑 `~/.hermes/config.yaml`：

```yaml
plugins:
  enabled:
    - mattermost-enhancer
```

3. **配置 Mattermost**

在 Mattermost System Console → Integrations → Slash Commands 中添加两条自定义指令：

| 指令 | 请求 URL | 请求方式 |
|------|---------|---------|
| `/model` | `http://<hermes-host>:18065/mm-command` | POST |
| `/new` | `http://<hermes-host>:18065/mm-command` | POST |

确保环境变量已配置：

```bash
export MATTERMOST_BOT_TOKEN="your-bot-token"
export MATTERMOST_CALLBACK_BIND="0.0.0.0"
export MATTERMOST_CALLBACK_PORT="18065"
```

4. **重启 Hermes Gateway**

```bash
hermes restart
```

## 交互演示

### /model — 模型切换

```
🔄 切换模型
当前: zenmux/minimax-m2.7
从下拉列表中选择目标模型：
[当前: zenmux/minimax-m2.7  ▾]
```

选择后卡片更新为：

```
✅ 模型已切换: minimax-m2.7 → deepseek-v4-pro
💡 重新选择请输入 /model
```

### /new — 新会话确认

```
🆕 创建新会话
当前会话将被重置，模型 override 清除。
[确认创建]  [取消]
```

### DM 审批

```
⚠️ 审批请求
命令: terminal rm -rf /data/cache/*
[Allow Once]  [Allow Session]  [Always Allow]  [Deny]
```

## 配置参考

```yaml
# ~/.hermes/config.yaml
platforms:
  mattermost:
    bot_token: "${MATTERMOST_BOT_TOKEN}"
    server_url: "http://127.0.0.1:8065"
    reply_mode: thread      # 或 channel
```

## 文件结构

```
mattermost-enhancer/
├── plugin.yaml           # 插件元数据
├── __init__.py           # 入口：register_platform()
├── adapter.py            # MattermostApprovalAdapter
├── cards.py              # Interactive Message 卡片渲染
├── models.py             # 模型列表管理
├── session.py            # Session 操作
├── callback_server.py    # HTTP 回调服务器
└── references/           # API 契约文档
```

## 技术细节

- **Session 区分**：Channel 顶层和 Thread 中的 `/model` `/new` 分别作用于不同 session，session_key 由 MM Slash Command payload 原生提供的 `root_id` 字段自动区分
- **模型选择器**：使用 Mattermost select 下拉列表（非按钮分组），格式 `provider/model`
- **Bot 身份**：卡片通过 Bot API (`_api_post`) 发帖，确保头像正确
- **模型感知**：切换后通过 `_pending_model_notes` 注入提示，让 LLM 正确报告当前使用的模型

## 许可

MIT License
