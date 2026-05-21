# hermes-plugin-mattermost-enhancer · 中文说明

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-≥%200.14.0-blue)](https://github.com/nousresearch/hermes-agent)

> English version: [README.md](README.md)

Hermes Platform Plugin — 扩展 Mattermost 适配器，提供 DM 审批交互卡片、
模型切换、会话重置等功能，无需修改 Hermes 源码。

## 功能

| 功能 | 触发方式 | 说明 |
|------|---------|------|
| **DM 审批** | 高危命令自动触发 | Allow Once / Session / Always / Deny 交互卡片 |
| **Thread root_id 修复** | 自动 | CRT 模式 root_id 正确指向 Thread 根帖子 |
| **MEDIA 静默跳过** | 自动 | 文件不存在时静默跳过，不发噪声消息 |
| **send_typing Thread 路由** | 自动 | typing 指示器跟随当前 Thread 上下文 |
| **模型切换 /model** | Slash Command | 下拉列表选择模型，仅影响当前 Thread |
| **会话重置 /new** | Slash Command | 清除 override + agent 缓存 + session 状态 |
| **Callback 服务器** | 自动 | HTTP 多路由：/mattermost/callback + /mm-command |

### send_typing Thread 路由

内置 `MattermostAdapter.send_typing()` 只传 `channel_id`，导致 typing 指示器
即使在 Thread 内回复也显示在频道层。本插件覆写 `send_typing()`，当 metadata
含 `thread_id` 时传入 `parent_id`，将指示器路由到正确的 Thread。

### 配套 Shell 脚本

`gateway/run.py` 中有两个修改是**调用方代码**，Platform Plugin 机制无法触及。
插件仓库提供了配套脚本：

| 修复 | 文件 | 说明 |
|------|------|------|
| DM 审批 `user_id` 参数 | `run.py` | `send_exec_approval()` 调用方没有传 `user_id` |
| 工具进度进 Thread | `run.py` | `_progress_reply_to` 只检查了 `Platform.FEISHU` |

安装插件后执行：

```bash
./scripts/hermes-mattermost-enhancer.sh check   # 检查
./scripts/hermes-mattermost-enhancer.sh apply   # 应用
```

> 这两个修复也可以向 Hermes Agent 上游提 PR 永久解决。

## 安装

### 前置条件

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) ≥ 0.14.0
- Mattermost 服务端 + Bot 账号（`post:all` 权限）
- Python ≥ 3.11

### 1. 安装

```bash
git clone https://github.com/colin-chang/hermes-plugin-mattermost-enhancer.git \
  ~/.hermes/plugins/hermes-plugin-mattermost-enhancer
```

### 2. 启用

编辑 `~/.hermes/config.yaml`：

```yaml
plugins:
  enabled:
    - hermes-plugin-mattermost-enhancer
```

### 3. 配置 Slash Commands

在 Mattermost System Console → Integrations → Slash Commands 添加：

| 指令 | 请求 URL |
|------|---------|
| `/model` | `http://<hermes-host>:18065/mm-command` |
| `/new` | `http://<hermes-host>:18065/mm-command` |

> Docker 同机部署用 `http://host.docker.internal:18065/mm-command`

### 4. 环境变量

```bash
export MATTERMOST_CALLBACK_BIND="0.0.0.0"
export MATTERMOST_CALLBACK_PORT="18065"
# 可选
export MATTERMOST_CALLBACK_SECRET="your-secret"
export MATTERMOST_ALLOWED_USERS="user_id_1,user_id_2"
```

### 5. 应用配套补丁

```bash
cd ~/.hermes/plugins/hermes-plugin-mattermost-enhancer
./scripts/hermes-mattermost-enhancer.sh apply
```

### 6. 重启

```bash
hermes gateway restart
```

## 使用方法

### `/model` — 切换模型

在 Thread 或 Channel 中输入 `/model`，下拉卡片列出所有可用模型，
选择一个即可切换当前 session 的模型，不影响其他 Thread。

### `/new` — 重置会话

输入 `/new` 重置当前 session：清除模型 override、evict agent 缓存、
创建全新对话上下文。

### DM 审批

执行高危命令时自动发送交互卡片到你的 DM，提供 Allow Once / Session / Always / Deny 按钮。

## 目录结构

```
hermes-plugin-mattermost-enhancer/
├── plugin.yaml              # 插件元数据
├── __init__.py              # register_platform("mattermost")
├── adapter.py               # MattermostApprovalAdapter (31 个方法)
│   ├── DM 审批              # send_exec_approval, _handle_callback 等
│   ├── Callback 服务器      # _start/_stop_callback_server, connect, disconnect
│   ├── /model 处理          # _handle_model_command, _switch_session_model 等
│   ├── /new 处理            # _handle_new_command, _reset_session 等
│   ├── Thread root_id       # _resolve_root_id, send(), _send_local_file 等
│   └── send_typing          # Thread 路由修复
├── cards.py                 # Interactive Message 卡片
├── models.py                # 模型列表管理
├── callback_server.py       # 环境检查
├── scripts/
│   └── hermes-mattermost-enhancer.sh   # 配套 shell patch
└── references/
    └── api-contracts.md     # MM API 契约
```

## 技术要点

- **Session 隔离**：直接从 MM Slash Command payload 的 `root_id` 字段区分
  Channel/Thread，无需 API 反查
- **模型选择器**：Mattermost select 下拉（不受 5 actions 限制），
  name 字段显示当前模型
- **Bot 身份**：卡片通过 Bot API 发帖，正确显示 Bot 头像
- **模型感知**：`_pending_model_notes` 注入通知 LLM
- **provider 格式**：session override 使用 `custom:<name>` 格式
- **按钮防重复**：处理后返回空 `actions` 数组清空按钮

## 许可

MIT — 详见 [LICENSE](LICENSE)
