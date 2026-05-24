# Hermes Mattermost Enhancer Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-≥%200.14.0-blue)](https://github.com/nousresearch/hermes-agent)
[![Release](https://img.shields.io/github/v/release/colin-chang/hermes-plugin-mattermost-enhancer?label=release)](https://github.com/colin-chang/hermes-plugin-mattermost-enhancer/releases)

English Version | [中文版本](./README.zh-CN.md)

Makes your Hermes AI assistant smarter, safer, and easier to use inside Mattermost.

---

## 😵‍💫 What Is This?

**In one sentence:** If you use Hermes in Mattermost, this plugin makes everything work better.

Hermes is an AI assistant you chat with in Mattermost to get things done. But the vanilla Hermes has some rough edges — it runs dangerous commands without asking, Thread replies sometimes leak into the channel, switching AI models requires editing config files…

This plugin "retrofits" these capabilities onto Hermes so everything just feels right.

---

## ✨ What Can It Do?

### 🛡️ 1. Dangerous Command Approval (DM Card Confirmation)

**Scenario:** You ask Hermes to run a command like `rm -rf some-folder` or `DROP TABLE`. Once executed, there's no undo — if the AI misunderstood you, the consequences are real.

**Before:** Hermes runs it instantly. You only see the result in chat — too late to stop it 😱

**Now:** When Hermes is about to execute a dangerous command, it won't act immediately. It sends you a **private DM confirmation card** with 4 buttons:

| Button | Effect |
|--------|--------|
| **Allow Once** | Approve this time only; ask again next time |
| **Allow This Session** | Approve for the rest of this conversation |
| **Always Allow** | Never require approval for this command again |
| **Deny** | Refuse — don't run it |

![Approval card effect](images/approve.webp)

Click any button and it takes effect immediately — all within Mattermost, no window switching.

---

### 🧠 2. Switch AI Models (`/model` Command)

**Scenario:** You have multiple AI models available — some excel at coding, some at conversation, some are cheaper, some faster. You want to pick the right model for each task.

**Before:** You had to edit `~/.hermes/config.yaml` and restart the Gateway — tedious 💀

**Now:** Type `/model` in any Thread and a dropdown card appears:

![Model switching card effect](images/model.webp)

The dropdown lists all your available models. Pick one — this Thread immediately switches to the new model, **other Threads are unaffected**.

Thread A uses Model X for coding; Thread B uses Model Y for chatting. No interference.

---

### 🔄 3. Reset Conversation (`/new` Command)

**Scenario:** The conversation has gone off track and the AI keeps fixating on an earlier topic. You want a fresh start.

**Before:** No way out — either start a new Thread or endure the AI's "memory" 💀

**Now:** Type `/new` and a confirmation card appears:

![New session card effect](images/new.webp)

After confirming:
- ✅ The Thread's model override is cleared (back to default)
- ✅ Hermes' "memory" is wiped (like a brand-new conversation)
- ✅ Session state is reset

---

### ⌨️ 4. Typing Indicator

**Scenario:** You're waiting for Hermes to reply in a Thread and want to know it's thinking.

**Before:** The "typing..." indicator appeared at the **channel** level, not in the Thread you're watching. You thought it was stuck 😕

**Now:** The typing indicator correctly appears in your current Thread — you know it's processing your request ✅

![Typing indicator example](images/typing.webp)

---

### ❓ 5. AI Asks You Questions (Interactive Cards)

**Scenario:** Hermes hits a decision point during a complex task — "This file has two processing approaches: A is fast but rough, B is slow but precise. Which one?" Or an open-ended question like "What approach would you prefer?"

**Before:** Hermes drops a plain-text line "Please reply: 1. A 2. B" into the Thread, easily missed in the conversation flow. You don't see it → Hermes hangs waiting 💀

**Now:** When Hermes asks a question, it posts a **prominent interactive card** with clickable buttons for each option. A "✍️ Other" button lets you type a free-form answer:

![AI question interactive card](images/clarify.webp)

- Click an option button → takes effect immediately, card updates to confirmed ✅
- Click "✍️ Other" → card prompts "Type your answer below" — just type in the chat
- Open-ended questions (no choices) → shows the question text, just type your answer

Everything happens inside Mattermost — no window switching, no commands to memorize.

---

### 🏷️ 6. Reply Footer (Model & Context)

**Scenario:** You have multiple Threads open, each potentially using a different AI model. Mid-conversation you think: "Wait, which model is this Thread using?"

**Before:** No such feature. You had to type `/model` and check the dropdown to know 💀

**Now:** Every Hermes reply automatically includes a one-line footnote showing the current model and context usage:

![Model footer effect](images/footer.webp)

Gray monospace footnote — subtle, glanceable. **Especially useful with multiple Threads** — each Thread's footer shows its own model, no confusion.

> 💡 **How to Enable**
>
> This feature builds on Hermes' built-in `runtime_footer`. Add this to the `display` section of `~/.hermes/config.yaml`:
>
> ```yaml
> display:
>   runtime_footer:
>     enabled: true
>     fields:
>       - model
>       - context_pct
> ```
>
> Then restart the Gateway. Only `model` (model name) and `context_pct` (context usage %) are included — clean and concise.
>
> If you're using Hermes CLI (not Gateway), you can also toggle it with `/footer on`.

---

---

## 🐛 What Bugs Are Fixed?

Below are 7 bugs fixed by this project (plugin + companion script). Each includes the **real-world impact** so you can tell if you've encountered them.

| # | Bug Description | Real-World Impact | After Fix |
|---|----------------|-------------------|------------|
| **1** | Thread replies leak: Hermes replies in a Thread may appear in the main channel instead of the Thread | CRT mode — chat chaos, you can't find the AI's reply | Replies correctly stay in the current Thread |
| **2** | Missing file spam: Hermes posts long error messages when an image/file can't be found | Chat flooded with `File not found: /tmp/xxx.png`, disrupting conversation | Silently skipped — no noise |
| **3** | Typing indicator at wrong level: the "typing..." indicator appears at the channel while Hermes is thinking in a Thread | You wait in a Thread with no typing feedback | Typing correctly appears in the current Thread |
| **4** | DM approval missing user_id: Hermes can't determine which user to send the approval DM to | Approval cards never arrive; dangerous commands may execute without approval | user_id properly passed; cards delivered on time |
| **5** | Tool progress not routed to Thread: multi-step task progress ("Searching...", "Reading file...") only appears in the main channel | You wait in a Thread with zero visibility into progress — result just pops out at the end 💀 | Progress messages correctly appear in the current Thread; you see every step in real time |
| **6** | AI questions too subtle: Hermes asks a question (multiple choice or open-ended) as plain text, easily missed in the conversation flow | You miss the question → no response → AI times out → also triggers a session split, AI answers nonsense 💀 | Questions rendered as interactive cards with buttons — prominent and clickable |
| **7** | Session split (AI amnesia): When AI is waiting for your reply, your next message starts a new conversation — AI forgets everything | You're chatting fine in Thread A, then suddenly AI doesn't recognize you and gives random answers | Messages correctly delivered to the waiting AI; no new session created |

---

---

## 🧱 Plugin vs. Companion Script — How to Understand It?

You may have noticed this project contains both a **plugin** and a **companion shell script** (`scripts/hermes-mattermost-enhancer.sh`). Here's a plain-language explanation.

### How Hermes Works

Think of Hermes as an **intelligent robot** 👤:

```
You ──→ Mattermost ──→ Hermes Gateway (robot hub) ──→ AI Brain
                              │
                              ├── Plugin: adds new skills to the robot
                              └── Source code: the robot's "skeleton" — can't change
```

### What the Plugin Can (and Can't) Do

A plugin is like installing an app on your phone — it adds features and improves the experience, but can't modify the phone's operating system.

- ✅ **What the plugin can change:** How the robot "replies to you" (adapter methods) — all features listed above are plugin-based
- ❌ **What the plugin can't touch:** How the robot "gets woken up" (caller-side code) — this is deep in Hermes' source code

Bug **#4** (DM approval missing user_id), Bug **#5** (tool progress not routed to Thread), and Bug **#7** (session split) are exactly in that untouchable caller-side code.

### What the Companion Script Does

It fixes those three plugin-unreachable bugs by modifying Hermes' source files with minimal changes. Bug #7 (session split) has also been [submitted upstream](https://github.com/NousResearch/hermes-agent/pull/30669) — future Hermes releases may include the fix built-in.

![Patch script output](images/patch.webp)

### Which One Do I Need?

**Both.** Install the plugin first (for the features), then run the script (for the three low-level bug fixes).

> 💡 In the future, Hermes upstream may merge these fixes in, making the script unnecessary. Running `check` will then show "already applied" and you can ignore it.

---

---

## 🚀 Quick Start (4 Steps)

### Prerequisites

- ✅ Running [Hermes Agent](https://github.com/nousresearch/hermes-agent) (≥ 0.14.0)
- ✅ Mattermost server with Bot account configured
- ✅ Python 3.11+

---

### Step 1: Install the Plugin

```bash
hermes plugins install colin-chang/hermes-plugin-mattermost-enhancer --enable
```

### Step 2: Register Mattermost Slash Commands

In **Mattermost System Console → Integrations → Slash Commands**, add two:

| Command | Request URL | Purpose |
|---------|-------------|---------|
| `/model` | `http://<your-hermes-host>:18065/mm-command` | Switch AI model |
| `/new` | `http://<your-hermes-host>:18065/mm-command` | Reset session |

> 🔧 If Mattermost and Hermes are on the same machine (Docker deployment), use `http://host.docker.internal:18065/mm-command`

### Step 3: Configure Environment Variables

Open `~/.hermes/.env` and add:

```bash
# ═══ Required ═══
# Callback server bind address and port
MATTERMOST_CALLBACK_BIND=0.0.0.0
MATTERMOST_CALLBACK_PORT=18065

# Callback URL — Mattermost uses this to send button clicks / dropdown selections back to Hermes
# 🔧 Docker deployment (Mattermost in container): MUST use host.docker.internal
MATTERMOST_CALLBACK_URL=http://host.docker.internal:18065/mattermost/callback
# 💻 Local deployment (Mattermost + Hermes on same machine, no Docker):
#    Can leave blank — plugin auto-falls-back to http://127.0.0.1:18065/mattermost/callback

# ═══ Optional ═══
# HMAC signature verification (skips verification if left empty)
# MATTERMOST_CALLBACK_SECRET=your-secret
```

> ⚠️ If you're like most self-hosting users with Mattermost running in Docker, **`MATTERMOST_CALLBACK_URL` must be set**. Without it, the Docker container can't reach Hermes on the host machine.

### Step 4: Run Companion Script + Restart

**When do you need to run this?**
- ✅ **First install**: required
- ✅ **After Hermes upgrade**: upgrades may overwrite source fixes — run `check` to confirm status
- ✅ **When features act up**: approval cards not arriving, progress messages not in Thread → run `check` to diagnose
- ❌ **During normal use**: no need to re-run

```bash
cd ~/.hermes/plugins/hermes-plugin-mattermost-enhancer

# First, check current status (see if both fixes are applied)
./scripts/hermes-mattermost-enhancer.sh check
```

If `check` shows fixes not applied, run:

```bash
# Apply fixes (will automatically ask if you want to restart immediately after)
./scripts/hermes-mattermost-enhancer.sh apply
```

🎉 **Done!** Now go to Mattermost and try `/model` or run a dangerous command to see the approval card.

---

---

## 📖 Usage Guide

### Switching AI Models

1. Type `/model` in any Thread and send
2. A dropdown card appears listing all available models
3. Select the model you want from the dropdown
4. The current Thread switches immediately — your next question uses the new model

> 💡 Switching only affects the current Thread. Other Threads keep their original model. Want to switch back? Just `/model` again.

### Resetting a Conversation

1. Type `/new` and send
2. A confirmation card appears
3. Click confirm — everything resets

> 💡 `/new` doesn't delete chat history — it just makes the AI "forget". Previous messages remain in the Thread for viewing.

### Approving Dangerous Commands

This is automatic — no manual trigger needed.

When Hermes is about to run a dangerous command:

1. You receive an approval card in your **private DM**
2. Choose one of the buttons:
   - **Allow Once** — approve this one time
   - **Allow This Session** — valid for this conversation
   - **Always Allow** — permanently approve this command
   - **Deny** — refuse
3. The button disappears instantly; Hermes receives your decision and acts on it

### AI Asking You Questions

This is also automatic. When Hermes needs you to make a decision:

1. A prominent interactive card appears in the current Thread
2. Click the option button you want → takes effect immediately
3. Or click "✍️ Other" → type your answer directly in the chat box
4. For open-ended questions → no buttons shown, just type your answer

### Viewing the Current Model

This is also automatic — no manual trigger needed.

Once enabled, every Hermes reply ends with a footer showing the current model and context usage, formatted as `── deepseek-v4-pro 34% ──`. A gray monospace footnote that doesn't disrupt reading.

Want to turn it off? Set `display.runtime_footer.enabled` to `false` in `config.yaml` and restart.

---

---

## ❓ FAQ

**Q: Do I need to install both the plugin and the script?**

A: Yes. The plugin is the "feature pack"; the script is the "bug-fix pack". You need both. The script only needs to run once (`apply`), though you may need to re-run after upgrading Hermes.

**Q: What should I do after upgrading Hermes?**

A: Major Hermes upgrades may overwrite the source fixes. It's recommended to run `./scripts/hermes-mattermost-enhancer.sh check` again to verify status.

**Q: Will the script mess up my Hermes?**

A: No. It makes minimal changes. You can check status anytime with `check`. To revert, simply reinstall Hermes.

**Q: What if I skip the script?**

A: Three bugs remain unfixed:
- DM approval cards won't arrive (no user_id)
- Tool progress messages won't appear in Threads (they'll appear in the main channel)
- Session split: when AI is waiting for your reply, your next message may start a new conversation (AI forgets everything)

All other features still work normally.

---

## 📁 Project Structure

```
mattermost-enhancer/
├── plugin.yaml              # Plugin metadata
├── __init__.py              # Plugin entry point
├── adapter.py               # Core logic (31 methods)
├── cards.py                 # Interactive card templates
├── models.py                # Model list resolver
├── callback_server.py       # Callback server
├── scripts/
│   └── hermes-mattermost-enhancer.sh   # Companion shell script
├── references/
│   └── api-contracts.md     # Mattermost API contract docs
├── README.md                # This document
├── README.zh-CN.md          # Chinese documentation
└── LICENSE                  # MIT
```

---

> 💡 **Docker Self-Hosting Tips** — If you run Mattermost in Docker, these will save you some headaches:
>
> - **Messages not live-updating?** Set `AllowCorsFrom` to `http://127.0.0.1:8065` in `config.json` and restart the container. The browser WebSocket is being blocked by CORS.
> - **`/model` not responding?** `MATTERMOST_CALLBACK_URL` in `.env` must use `http://host.docker.internal:18065/mattermost/callback`. Inside a container, `127.0.0.1` points to the container itself, not the host.
> - **Images showing as broken?** Make `SiteURL` match the URL in your browser's address bar. Local = `127.0.0.1`, remote = your domain — don't mix them.
> - **Random disconnects?** Give the container at least 2GB of memory. Run `docker stats mm-app` to check current usage.

## 📄 License

MIT — see [LICENSE](LICENSE)
