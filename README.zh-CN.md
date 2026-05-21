# mattermost-enhancer · 中文说明

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-≥%200.14.0-blue)](https://github.com/nousresearch/hermes-agent)

> English version: [README.md](README.md)

Hermes Platform Plugin — 统一插件，替代所有 Mattermost 相关的源码 patch，
实现 **`mattermost.py` 零修改**。

## 功能覆盖

| 功能 | 触发方式 | 替代的原 Patch | 说明 |
|------|---------|--------------|------|
| **DM 审批** | 高危命令自动触发 | patch 7a-7d (~400行) | Allow Once / Session / Always / Deny 交互卡片 |
| **Thread root_id 修复** | 自动 | patch 6a-6d | CRT 模式 root_id 指向 Thread 根帖子，防止 400 错误 |
| **MEDIA 静默跳过** | 自动 | patch 10c | 文件不存在时静默跳过，不发噪声消息到频道 |
| **send_typing Thread 路由** | 自动 | patch 11 | typing 指示器跟随当前 Thread 上下文 |
| **模型切换 /model** | Slash Command | 新功能 | 下拉列表选择模型，仅影响当前 Thread |
| **会话重置 /new** | Slash Command | 新功能 | 清除 override + agent 缓存 + session 状态 |
| **Callback 服务器** | 自动 | patch 7c, 7d | HTTP 多路由：/mattermost/callback + /mm-command |

## 仍需 Shell Patch 的功能（插件无法覆盖）

插件覆盖了**所有 `mattermost.py` 层面的修改**。但 `gateway/run.py` 中有两处修改
是**调用方代码**，插件无法触及，需要通过 [hermes-patches.sh](./scripts/) 单独应用：

| Patch | 文件 | 为什么插件无法修复 |
|-------|------|-------------------|
| **DM 审批 `user_id` 参数** | `run.py` | 调用 `send_exec_approval()` 的地方没有传 `user_id`。插件提供了方法实现，但改不了 `run.py` 怎么调用它。 |
| **工具进度消息不进 Thread** | `run.py` | `_progress_reply_to` 条件判断只写了 `Platform.FEISHU`，漏了 `Platform.MATTERMOST`。这是路由逻辑在调用方，适配器不可控。 |

> 这两个 patch 可以向 Hermes Agent 上游提 PR 永久修复，或在上游合入前通过
> `hermes-patches.sh` 脚本临时应用。

## 安装

### 前置条件

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) ≥ 0.14.0
- Mattermost 服务端 + Bot 账号（需 `post:all` 权限）
- Python ≥ 3.11

### 1. 安装插件

```bash
git clone https://github.com/<your-username>/mattermost-enhancer.git \
  ~/.hermes/plugins/mattermost-enhancer
```

### 2. 启用插件

编辑 `~/.hermes/config.yaml`：

```yaml
plugins:
  enabled:
    - mattermost-enhancer
```

### 3. 配置 Mattermost Slash Commands

在 Mattermost System Console → Integrations → Slash Commands 中添加：

| 指令 | 请求 URL |
|------|---------|
| `/model` | `http://<hermes-host>:18065/mm-command` |
| `/new` | `http://<hermes-host>:18065/mm-command` |

> Hermes 和 Mattermost 在同一台机器上通过 Docker 运行时，URL 用
> `http://host.docker.internal:18065/mm-command`

### 4. 环境变量

```bash
export MATTERMOST_CALLBACK_BIND="0.0.0.0"
export MATTERMOST_CALLBACK_PORT="18065"
# 可选：回调 HMAC 签名验证
export MATTERMOST_CALLBACK_SECRET="your-secret"
# 可选：限制可用用户
export MATTERMOST_ALLOWED_USERS="user_id_1,user_id_2"
```

### 5. 应用配套 Shell Patch

剩余的两个 `run.py` patch（见上文）通过 Hermes 配置中自带的
`hermes-patches.sh` 脚本应用：

```bash
~/.hermes/scripts/hermes-patches.sh apply
~/.hermes/scripts/hermes-patches.sh check   # 验证
```

### 6. 重启

```bash
hermes gateway restart
```

## 使用方法

### `/model` — 切换模型

在 Thread（或 Channel）中输入 `/model`，弹出下拉卡片列出所有可用模型。
选择一个即可切换当前 session 的模型，不影响其他 Thread。

### `/new` — 重置会话

输入 `/new` 可重置当前 session：清除模型 override、evict agent 缓存、
创建全新对话上下文。

### DM 审批

当 Agent 执行高危命令时，插件自动发送交互卡片到你的 DM：

```
⚠️ 危险命令需要审批
[Allow Once] [Allow Session] [Always Allow] [Deny]
```

## 技术要点

- **Session 隔离**：直接从 MM Slash Command payload 的 `root_id` 字段区分
  Channel/Thread，无需 API 反查
- **模型选择器**：Mattermost select 下拉（不受 5 actions/attachment 限制），
  name 字段显示当前模型
- **Bot 身份**：卡片通过 Bot API 发帖，正确显示 Bot 头像
- **模型感知**：`_pending_model_notes` 注入通知，LLM 正确报告当前模型
- **provider 格式**：session override 使用 `custom:<name>` 格式匹配 Gateway 解析链
- **按钮防重复**：处理后返回空 `actions` 数组清空按钮

## 许可

MIT — 详见 [LICENSE](LICENSE)
