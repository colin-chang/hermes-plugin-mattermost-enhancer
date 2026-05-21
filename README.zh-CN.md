# Hermes × Mattermost 增强插件

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-≥%200.14.0-blue)](https://github.com/nousresearch/hermes-agent)

让你的 Hermes AI 助手在 Mattermost 里变得更聪明、更安全、更好用。

---

## 😵‍💫 这是什么？

**一句话：** 如果你在 Mattermost 里用 Hermes，这个插件能让它变得更好用。

Hermes 是一个 AI 助手，你可以在 Mattermost 里跟它对话，让它帮你干活。但原版 Hermes 在某些方面不太顺手——比如执行危险命令前不会问你、Thread 里回复有时候跳到频道里去了、想切换 AI 模型得去改配置文件……

这个插件就是给 Hermes "加装"这些能力，让你用起来更顺手。

---

## ✨ 它能做什么？

### 🛡️ 1. 危险操作审批（私信卡片确认）

**场景：** 你让 Hermes 执行一个命令，比如 `rm -rf 某个文件夹` 或者 `删除数据库记录`。这些操作一旦执行就不可逆，万一 AI 理解错了你的意思，后果很严重。

**原来：** Hermes 二话不说就执行了，你只能在聊天记录里看到结果，来不及阻止 😱

**现在：** 当 Hermes 要执行危险命令时，它不会直接动手。它会**私信你一张确认卡片**，上面有 4 个按钮：

| 按钮 | 效果 |
|------|------|
| **Allow Once** | 允许这一次，下次同样的命令还要重新审批 |
| **Allow This Session** | 允许这一次，整个对话结束前不再问 |
| **Always Allow** | 以后这个命令永远不需要审批 |
| **Deny** | 拒绝，不执行 |

> 📸 `[截图位]` — 私信中的审批卡片，展示 4 个按钮的界面

你点哪个按钮，按钮就会立刻消失并生效。整个过程全在 Mattermost 里完成，不用切窗口。

---

### 🧠 2. 切换 AI 模型（`/model` 指令）

**场景：** 你有好几种 AI 模型可选，有的擅长写代码、有的擅长聊天、有的便宜、有的快。你想根据具体任务切换模型。

**原来：** 得去改 `~/.hermes/config.yaml` 配置文件，改完还要重启 Gateway，非常繁琐 💀

**现在：** 在任何 Thread 里输入 `/model`，会弹出一张下拉菜单卡片：

> 📸 `[截图位]` — `/model` 指令弹出的模型选择下拉卡片

下拉列表里列出了所有你可用的模型。选一个，这个 Thread 就会立刻切换到新模型，**其他 Thread 不受影响**。

比如 Thread A 用模型 X 写代码，Thread B 用模型 Y 聊天，互不干扰。

---

### 🔄 3. 重置对话（`/new` 指令）

**场景：** 对话跑偏了，AI 一直在纠结前面说过的某个话题。你想"重开一局"。

**原来：** 没办法，要么新开一个 Thread，要么忍受 AI 的"记忆" 💀

**现在：** 输入 `/new`，会弹出确认卡片：

> 📸 `[截图位]` — `/new` 指令弹出的确认卡片

点击确认后：
- ✅ 当前 Thread 的模型切换被清除（恢复默认模型）
- ✅ Hermes 的"记忆"被清空（像新对话一样）
- ✅ 会话状态重置

---

### ⌨️ 4. 正在输入提示（Typing 指示器）

**场景：** 你在 Thread 里等 Hermes 回复，想知道它是不是在思考。

**原来：** "正在输入..."  的标志出现在频道级别，而不是你正在聊天的那个 Thread 里。你以为它卡住了 😕

**现在：** Typing 提示正确出现在当前 Thread 中，你知道它在处理你的请求 ✅

> 📸 `[截图位]` — Thread 里显示 "Hermes 正在输入..."  的 Typing 指示器

---

---

## 🐛 修复了什么 Bug？

下面是这个项目（插件 + 配套脚本）修掉的 5 个 Bug。每个 Bug 都附带了**造成的影响**，这样你能判断是否遇到过这些问题。

| # | Bug 描述 | 造成的影响 | 修复后 |
|---|---------|-----------|--------|
| **1** | Thread 回复跑偏：Hermes 在 Thread 里回复时，消息可能出现在频道主聊天流，而不是 Thread 里 | CRT 模式下聊天混乱，你找不到 AI 的回复在哪 | 回复正确出现在当前 Thread 中 |
| **2** | 文件不存在时刷屏：Hermes 要发送的图片/文件找不到了，会在聊天里贴一大段错误信息 | 聊天被 `File not found: /tmp/xxx.png` 刷屏，干扰正常对话 | 文件不存在时静默跳过，不打扰你 |
| **3** | Typing 标志位置错误：Hermes 在 Thread 里思考时，"正在输入..."  出现在频道级别 | 你在 Thread 里等回复，却看不到 Typing 标志 | Typing 正确出现在当前 Thread |
| **4** | DM 审批不知道发给谁：Hermes 要发审批私信，但不知道发给哪个用户（user_id 没传过来） | 审批卡片无法送达，危险操作可能被直接执行 | user_id 正确传递，审批卡片按时送到 |
| **5** | 工具链进度不进 Thread：Hermes 执行多步任务（如连续调用多个工具）时，中间的进度提示（"正在搜索..."、"正在读文件..."）只出现在频道主聊天流 | 你在 Thread 里等结果，过程中完全看不到进展，最后才突然弹出结果 💀 | 进度消息正确出现在当前 Thread，你能实时看到每一步 |

---

---

## 🧱 插件 vs 配套脚本，怎么理解？

你可能注意到了，这个项目里除了插件（Plugin），还有一个 **配套 Shell 脚本**（`scripts/hermes-mattermost-enhancer.sh`）。这里用大白话解释一下。

### Hermes 的工作原理

可以把 Hermes 理解成一个**智能机器人** 👤：

```
你 ──→ Mattermost ──→ Hermes Gateway（机器人中枢）──→ AI 大脑
                              │
                              ├── 插件（Plugin）: 给机器人装新技能
                              └── 源码（Source）: 机器人的"骨架"，改不了
```

### 插件能做什么？不能做什么？

插件就像给手机装 App——能增加功能、优化体验，但不能改手机的底层系统。

- ✅ **插件能改的**：机器人"怎么回复你"（适配器方法）——本章前面列的所有功能都是插件实现的
- ❌ **插件改不了的**：机器人"怎么被叫起来的"（调用方代码）——这部分在 Hermes 的底层源码里

上面 Bug 表格里的 **Bug #4**（DM 审批缺少 user_id）和 **Bug #5**（工具进度消息不进 Thread），就是插件够不到的地方。

### 配套脚本是干什么的？

就是修这两个插件够不到的 Bug。它直接修改了 Hermes 的源码文件（`gateway/run.py`），加了两行代码。

> 📸 `[截图位]` — 运行 `./scripts/hermes-mattermost-enhancer.sh check` 的输出结果

### 我该装哪个？

**两个都要装。** 先装插件（实现主要功能），再跑脚本（修两个底层 Bug）。

> 💡 将来 Hermes 官方可能会把这两个 Bug 修复合并进去，到时候就不需要脚本了。到时候运行 `check` 会提示"已应用"，你就不用管它了。

---

---

## 🚀 快速上手（5 步）

### 前提条件

- ✅ 已经在用 [Hermes Agent](https://github.com/nousresearch/hermes-agent)（版本 ≥ 0.14.0）
- ✅ 有一个 Mattermost 服务器，Bot 账号已配好
- ✅ Python 3.11+

---

### 第 1 步：下载插件

```bash
git clone https://github.com/colin-chang/hermes-plugin-mattermost-enhancer.git \
  ~/.hermes/plugins/mattermost-enhancer
```

### 第 2 步：启用插件

打开 `~/.hermes/config.yaml`，在 `plugins.enabled` 下面加上一行：

```yaml
plugins:
  enabled:
    - mattermost-enhancer     # ← 加这行
```

> ⚠️ 注意：是 `mattermost-enhancer`，不是 `hermes-plugin-mattermost-enhancer`

### 第 3 步：注册 Mattermost Slash 指令

在 Mattermost **系统控制台 → 集成 → Slash 指令** 中添加两条：

| 指令 | 请求 URL | 说明 |
|------|---------|------|
| `/model` | `http://<你的Hermes主机>:18065/mm-command` | 切换 AI 模型 |
| `/new` | `http://<你的Hermes主机>:18065/mm-command` | 重置会话 |

> 🔧 如果 Mattermost 和 Hermes 在同一台机器上（Docker 部署），用 `http://host.docker.internal:18065/mm-command`

### 第 4 步：配置环境变量（可选）

```bash
# 审批私信回调服务器绑定地址和端口（默认值通常够用）
export MATTERMOST_CALLBACK_BIND="0.0.0.0"
export MATTERMOST_CALLBACK_PORT="18065"

# 可选：HMAC 签名验证（增强安全）
export MATTERMOST_CALLBACK_SECRET="你的密钥"

# 可选：限制哪些用户可以用审批功能
export MATTERMOST_ALLOWED_USERS="user_id_1,user_id_2"
```

### 第 5 步：运行配套脚本 + 重启

```bash
cd ~/.hermes/plugins/mattermost-enhancer

# 先检查当前状态
./scripts/hermes-mattermost-enhancer.sh check

# 应用修复
./scripts/hermes-mattermost-enhancer.sh apply

# 重启 Hermes Gateway
hermes gateway restart
```

🎉 **完成！** 现在去 Mattermost 里试试 `/model` 或者执行一条危险命令看看审批卡片吧。

---

---

## 📖 使用指南

### 切换 AI 模型

1. 在任何 Thread 里输入 `/model` 并发送
2. 会弹出一张下拉菜单，显示所有可用模型

   > 📸 `[截图位]` — Thread 中的 `/model` 下拉菜单卡片

3. 从下拉菜单中选择你要的模型
4. 当前 Thread 立刻切换，下一个问题就用新模型回答

   > 📸 `[截图位]` — 选择模型后的确认提示

> 💡 切换只影响当前 Thread。其他 Thread 还是原来的模型。想切回去？再 `/model` 选一次。

### 重置对话

1. 输入 `/new` 并发送
2. 弹出确认卡片

   > 📸 `[截图位]` — `/new` 确认卡片

3. 点击确认，一切重置

> 💡 `/new` 不会删除聊天记录，只是让 AI "失忆"。之前的聊天还在 Thread 里可以看。

### 审批危险操作

这是自动的，不需要你手动触发。

当 Hermes 要执行危险命令时：

1. 你会在 **私信** 里收到一张审批卡片

   > 📸 `[截图位]` — 私信中的审批卡片，展示 4 个按钮

2. 选择其中一个按钮：
   - **Allow Once** — 只批准这一次
   - **Allow This Session** — 这次对话有效
   - **Always Allow** — 永远批准这条命令
   - **Deny** — 拒绝

3. 按钮立刻消失，Hermes 收到你的决定并执行

   > 📸 `[截图位]` — 点击 "Allow Once" 后卡片消失的效果

---

---

## ❓ 常见问题

**Q: 插件和脚本要一起装吗？**

A: 对。插件是"功能包"，脚本是"Bug 修复包"。两个都要。脚本只需要跑一次（`apply`），以后 Hermes 升级时可能需要再跑一次。

**Q: 升级 Hermes 后怎么办？**

A: Hermes 大版本升级后，源码可能被覆盖。建议再跑一次 `./scripts/hermes-mattermost-enhancer.sh check` 看看状态。

**Q: 脚本会不会搞坏我的 Hermes？**

A: 不会。它只改了两行代码，你可以用 `check` 随时查看状态。如果想还原，重新安装 Hermes 即可。

**Q: 我不想装脚本，有什么影响？**

A: 两个 Bug 得不到修复：
- DM 审批卡片收不到（因为没有你的 user_id）
- 工具进度消息不会出现在 Thread 里（会跳到频道主聊天流）

其他功能都正常工作。

---

## 📁 项目结构

```
mattermost-enhancer/
├── plugin.yaml              # 插件元数据
├── __init__.py              # 插件入口
├── adapter.py               # 核心逻辑（31 个方法）
├── cards.py                 # 交互卡片模板
├── models.py                # 模型列表
├── callback_server.py       # 回调服务器
├── scripts/
│   └── hermes-mattermost-enhancer.sh   # 配套 Shell 脚本
├── references/
│   └── api-contracts.md     # Mattermost API 契约文档
├── README.md                # 英文文档
├── README.zh-CN.md          # 本文档
└── LICENSE                  # MIT
```

---

## 📄 许可

MIT — 详见 [LICENSE](LICENSE)
