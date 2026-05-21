# Hermes × Mattermost Enhancer Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-≥%200.14.0-blue)](https://github.com/nousresearch/hermes-agent)

Makes your Hermes AI assistant smarter, safer, and more pleasant to use inside Mattermost.

> 📖 [中文文档 (Chinese README)](README.zh-CN.md)

---

## What is this?

**One sentence:** If you chat with Hermes in Mattermost, this plugin makes the experience *way* better.

Out of the box, Hermes works in Mattermost — but some things are annoying:
- Dangerous commands run instantly, no "are you sure?" step
- Thread replies sometimes leak into the channel
- Switching AI models means editing config files and restarting

This plugin fixes all of that.

---

## ✨ Features

> 📸 Screenshots can be placed at each `[screenshot]` marker below.

### 🛡️ 1. DM Approval for Dangerous Commands

When Hermes is about to run a command that could do real damage (like `rm -rf` or dropping a database table), it won't just execute it. Instead, it sends you a **private DM card** with four buttons:

| Button | What it does |
|--------|-------------|
| **Allow Once** | Approve this one time. Next time, ask again. |
| **Allow This Session** | Approve for the rest of this conversation. |
| **Always Allow** | Never ask for this command again. |
| **Deny** | Cancel. Don't run it. |

> 📸 `[screenshot]` — DM approval card with 4 buttons

Click any button, and it takes effect immediately — no window switching required.

---

### 🧠 2. Model Switching (`/model`)

**Before:** Changing AI models meant editing `config.yaml` and restarting the Gateway.

**Now:** Type `/model` in any Thread. A dropdown card lists all your available models:

> 📸 `[screenshot]` — `/model` dropdown card with model list

Pick one. Only **this Thread** switches models. Other Threads keep theirs.

---

### 🔄 3. Session Reset (`/new`)

**Before:** When the AI got stuck on a topic, you had to start a new Thread.

**Now:** Type `/new` for a confirmation card:

> 📸 `[screenshot]` — `/new` confirmation card

Confirming clears the model override, agent cache, and session state — a fresh start in the same Thread.

---

### ⌨️ 4. Thread-aware Typing Indicator

**Before:** The "typing..." indicator appeared at the **channel** level, even when you were waiting in a Thread.

**Now:** The typing indicator correctly shows in the current Thread, so you know Hermes is actually working on your request.

> 📸 `[screenshot]` — Typing indicator inside a Thread

---

## 🐛 Bug Fixes

These are bugs fixed by this plugin (and its companion script). Each entry shows what went wrong and how it affected you.

| # | Bug | Real-World Impact | Fixed |
|---|-----|-------------------|-------|
| **1** | Thread replies leak to channel level | CRT mode: you can't find AI replies where you expect them | Replies correctly stay in the Thread |
| **2** | Missing-file errors spam the chat | `File not found: /tmp/img.png` fills your conversation | Silently skipped — no noise |
| **3** | Typing indicator at channel, not Thread | You wait in a Thread but see no "typing..." feedback | Typing indicator follows Thread context |
| **4** | DM approval had no user_id | Approval cards couldn't be delivered to you | user_id properly passed, cards arrive |
| **5** | Tool-chain progress leaks to channel | Multi-step tasks show progress ("Searching...", "Reading file...") only in the main channel, not your Thread | You wait in a Thread with zero visibility into what's happening — result just pops out at the end 💀 | Progress messages appear in the correct Thread, you see every step |

---

## Plugin vs. Companion Script — How It Works

### Hermes Architecture (Simplified)

Think of Hermes as a **robot** 🤖:

```
You → Mattermost → Hermes Gateway (the robot's brain) → AI model
                          │
                          ├── Plugin: adds new skills to the robot
                          └── Source code: the robot's wiring — plugins can't touch this
```

### What the Plugin Can (and Can't) Do

- ✅ **Plugin territory:** How Hermes replies to you (adapter methods). All features above are plugin-based.
- ❌ **Outside plugin reach:** How Hermes gets *called* in the first place (caller-side code). This is deep in `gateway/run.py`.

Bug #4 (DM user_id) and Bug #5 (tool progress routing) are in the caller-side code — the plugin simply can't reach them.

### What the Companion Script Does

It applies two tiny fixes to `~/.hermes/hermes-agent/gateway/run.py`:

1. Passes `user_id` when sending approval cards (so the plugin knows who to DM)
2. Routes tool-progress messages into Mattermost Threads (not just the channel)

> 📸 `[screenshot]` — `./scripts/hermes-mattermost-enhancer.sh check` output

### Which Do I Need?

**Both.** Install the plugin first, then run the script once.

> 💡 If Hermes merges these fixes upstream someday, the script becomes unnecessary — running `check` will just show "already applied."

---

## 🚀 Quick Start (5 Steps)

### Prerequisites

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) ≥ 0.14.0
- Mattermost server with a Bot account (`post:all` permission)
- Python ≥ 3.11

---

### Step 1: Install the Plugin

```bash
git clone https://github.com/colin-chang/hermes-plugin-mattermost-enhancer.git \
  ~/.hermes/plugins/mattermost-enhancer
```

### Step 2: Enable It

Add to `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - mattermost-enhancer     # ← add this line
```

> ⚠️ Note: the plugin name is `mattermost-enhancer`, not `hermes-plugin-mattermost-enhancer`

### Step 3: Register Slash Commands in Mattermost

In **System Console → Integrations → Slash Commands**, add two:

| Command | Request URL | Purpose |
|---------|-------------|---------|
| `/model` | `http://<your-hermes-host>:18065/mm-command` | Switch AI model |
| `/new` | `http://<your-hermes-host>:18065/mm-command` | Reset session |

> 🔧 If Mattermost runs in Docker on the same machine: use `http://host.docker.internal:18065/mm-command`

### Step 4: Set Environment Variables (Optional)

```bash
export MATTERMOST_CALLBACK_BIND="0.0.0.0"
export MATTERMOST_CALLBACK_PORT="18065"

# Optional: HMAC signature verification
export MATTERMOST_CALLBACK_SECRET="your-secret"

# Optional: restrict DM approvals to specific users
export MATTERMOST_ALLOWED_USERS="user_id_1,user_id_2"
```

### Step 5: Run Companion Script + Restart

```bash
cd ~/.hermes/plugins/mattermost-enhancer

# Check status first
./scripts/hermes-mattermost-enhancer.sh check

# Apply fixes
./scripts/hermes-mattermost-enhancer.sh apply

# Restart Hermes
hermes gateway restart
```

🎉 **Done!** Try `/model` in a Thread or run a dangerous command to test DM approval.

---

## 📖 Usage

### Switching Models

1. Type `/model` in any Thread
2. A dropdown card appears with your available models

   > 📸 `[screenshot]` — model selector dropdown in a Thread

3. Select a model from the dropdown
4. The Thread immediately switches — your next question uses the new model

   > 📸 `[screenshot]` — confirmation after model switch

> 💡 Only this Thread is affected. Other Threads keep their original model.

### Resetting a Session

1. Type `/new`
2. A confirmation card appears

   > 📸 `[screenshot]` — reset confirmation card

3. Confirm to clear model override, agent cache, and session state

### Approving Dangerous Commands

This is automatic — no action needed from you.

When Hermes wants to run a dangerous command:

1. A DM card arrives in your private messages

   > 📸 `[screenshot]` — approval card in DM

2. Choose one of the four buttons
3. The card disappears, and Hermes follows your decision

   > 📸 `[screenshot]` — card disappears after clicking "Allow Once"

---

## ❓ FAQ

**Q: Do I need both the plugin and the script?**

A: Yes. The plugin is the feature pack. The script fixes two bugs the plugin can't reach. Install both.

**Q: What happens when I upgrade Hermes?**

A: Upgrading may overwrite the two script fixes. Run `./scripts/hermes-mattermost-enhancer.sh check` after upgrading to see if you need to re-apply.

**Q: Will the script break anything?**

A: No. It changes exactly two lines. Run `check` anytime to see the current status. Re-installing Hermes reverts everything.

**Q: What if I skip the script?**

A: Two things won't work properly:
- DM approval cards may not reach you (no user_id)
- Tool progress messages appear at channel level instead of your Thread

Everything else works fine.

---

## 📁 Project Structure

```
mattermost-enhancer/
├── plugin.yaml              # Plugin metadata
├── __init__.py              # Entry point
├── adapter.py               # Core logic (31 methods)
├── cards.py                 # Interactive card templates
├── models.py                # Model list resolver
├── callback_server.py       # HTTP callback server
├── scripts/
│   └── hermes-mattermost-enhancer.sh   # Companion shell script
├── references/
│   └── api-contracts.md     # Mattermost API specs
├── README.md                # This file
├── README.zh-CN.md          # Chinese documentation
└── LICENSE                  # MIT
```

---

## 📄 License

MIT — see [LICENSE](LICENSE)
