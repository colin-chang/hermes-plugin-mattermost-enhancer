# mattermost-enhancer

Hermes Platform Plugin — 将 Mattermost 所有自定义能力封装为插件，实现 **`mattermost.py` 源码零修改**。

## 功能覆盖

| 功能 | 触发方式 | 替代的原 Patch | 说明 |
|------|---------|--------------|------|
| **DM 审批** | 高危命令自动触发 | patch 7a-7d (~400行) | Allow Once / Session / Always / Deny 按钮卡片 |
| **Thread root_id 修复** | 自动 | patch 6a-6d | CRT 模式下 root_id 指向 Thread 根帖子 |
| **MEDIA 静默跳过** | 自动 | patch 10c | 文件不存在时静默跳过，不发噪声消息 |
| **send_typing Thread 路由** | 自动 | patch 11 | typing 指示器跟随 Thread 上下文 |
| **模型切换 /model** | Slash Command | 新功能 | 下拉列表选择模型，仅影响当前 Thread |
| **会话重置 /new** | Slash Command | 新功能 | 清除 override + agent 缓存，新建会话 |
| **Callback 服务器** | 自动 | patch 7c, 7d | HTTP 多路由：/mattermost/callback + /mm-command |

> 仍需要 shell patch 的：`run.py` 的 `send_exec_approval` 传入 `user_id`（patch 8）和 `_progress_reply_to` Mattermost 判断（patch 8b）—— 这两个修改的是调用方，插件无法触及。

## 安装

### 前置

- Hermes Agent ≥ 0.14.0
- Mattermost Bot Token（需 `post:all` 权限）
- Python ≥ 3.11

### 1. 启用插件

编辑 `~/.hermes/config.yaml`：

```yaml
plugins:
  enabled:
    - mattermost-enhancer
```

### 2. 配置 Mattermost Slash Commands

在 System Console → Integrations 添加：

| 指令 | 请求 URL |
|------|---------|
| `/model` | `http://<host>:18065/mm-command` |
| `/new` | `http://<host>:18065/mm-command` |

### 3. 环境变量

```bash
export MATTERMOST_CALLBACK_BIND="0.0.0.0"   # Docker 用 host.docker.internal
export MATTERMOST_CALLBACK_PORT="18065"
# 可选：回调 HMAC 签名
export MATTERMOST_CALLBACK_SECRET="your-secret"
# 可选：限制可用用户
export MATTERMOST_ALLOWED_USERS="user_id_1,user_id_2"
```

### 4. 重启

```bash
hermes gateway restart
```

## 插件结构

```
mattermost-enhancer/
├── plugin.yaml              # 插件元数据 (kind=platform)
├── __init__.py              # register_platform("mattermost")
├── adapter.py               # MattermostApprovalAdapter (31 个方法, ~1180 行)
│   ├── DM 审批              # send_exec_approval, _handle_callback, _verify_signature 等
│   ├── Callback 服务器      # _start/_stop_callback_server, connect, disconnect
│   ├── /model Slash 指令    # _handle_model_command, _switch_session_model 等 8 个方法
│   ├── /new Slash 指令      # _handle_new_command, _reset_session 等 4 个方法
│   ├── Thread root_id       # _resolve_root_id, send(), _send_local_file, _send_url_as_file
│   ├── send_typing          # Thread 路由修复
│   └── send_model_picker    # forward compat
├── cards.py                 # Interactive Message 卡片（select 下拉 + button）
├── models.py                # 模型列表管理（custom_providers 解析）
├── session.py               # Session 定位（备用）
├── callback_server.py       # 环境检查
└── references/
    └── api-contracts.md     # MM Slash Command & Interactive Message API 契约
```

## 技术要点

- **Session 区分**：直接从 MM Slash Command payload 的 `root_id` 字段区分 Channel/Thread，无需 API 反查
- **模型选择器**：Mattermost select 下拉列表（不限数量），name 字段作 placeholder 显示当前模型
- **Bot 身份**：卡片通过 Bot API `_api_post` 发帖，避免用户头像显示
- **模型感知**：`_pending_model_notes` 注入通知，LLM 正确报告当前模型
- **provider 格式**：session override 使用 `custom:name` 格式，匹配 Gateway 解析链
- **按钮防重复**：Deny/处理后返回空 `actions` 数组清空按钮
- **5 按钮限制**：select 下拉突破 5 actions/attachment 限制

## 迁移效果

```
mattermost.py: 1292 行 (4 patch 残留) → 852 行 (零修改)
hermes-patches.sh: 移除 patches 6, 7, 10c (~673 行 shell 代码)
```

## 许可

MIT
