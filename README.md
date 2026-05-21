# mattermost-enhancer

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-≥%200.14.0-blue)](https://github.com/nousresearch/hermes-agent)

Hermes Platform Plugin — a unified plugin that replaces all Mattermost-specific
source code patches, achieving **zero modification to `mattermost.py`**.

## Features

| Feature | Trigger | Replaces | Description |
|---------|---------|----------|-------------|
| **DM Approval** | Auto (dangerous commands) | patch 7a-7d (~400 lines) | Interactive button cards: Allow Once / Session / Always / Deny |
| **Thread root_id Fix** | Auto | patch 6a-6d | CRT mode: root_id points to thread root post (prevents 400 Invalid RootId) |
| **MEDIA Silent Skip** | Auto | patch 10c | Silently skip missing files instead of posting noise to channel |
| **send_typing Thread Routing** | Auto | patch 11 | Typing indicator follows current Thread context |
| **Model Switch `/model`** | Slash Command | New | Dropdown model picker, scoped to current Thread only |
| **Session Reset `/new`** | Slash Command | New | Clear override + agent cache + session state |
| **Callback Server** | Auto | patch 7c, 7d | HTTP multi-route: `/mattermost/callback` + `/mm-command` |

### Remaining Shell Patches (run.py — caller-side, plugin cannot reach)

The plugin covers **all `mattermost.py` modifications**. Two patches in `gateway/run.py`
still require the [hermes-patches.sh](./scripts/) shell script because they modify
**caller code** that exists outside the adapter class:

| Patch | File | Why Plugins Can't Fix It |
|-------|------|--------------------------|
| **DM Approval `user_id`** | `run.py` | `send_exec_approval()` caller does not pass `user_id`. The plugin provides the method, but cannot change how `run.py` invokes it. |
| **Progress in Thread** | `run.py` | `_progress_reply_to` condition checks only `Platform.FEISHU`. Adding `Platform.MATTERMOST` requires modifying the caller's routing logic. |

These two patches can be submitted as upstream PRs to Hermes Agent, or applied
via the companion shell script until merged upstream.

## Installation

### Prerequisites

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) ≥ 0.14.0
- Mattermost server (self-hosted or Cloud) with Bot account (`post:all` permission)
- Python ≥ 3.11

### 1. Install the Plugin

```bash
git clone https://github.com/<your-username>/mattermost-enhancer.git \
  ~/.hermes/plugins/mattermost-enhancer
```

### 2. Enable in Hermes

Edit `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - mattermost-enhancer
```

### 3. Configure Mattermost Slash Commands

In Mattermost System Console → Integrations → Slash Commands, add:

| Command | Request URL |
|---------|-------------|
| `/model` | `http://<hermes-host>:18065/mm-command` |
| `/new` | `http://<hermes-host>:18065/mm-command` |

> If Hermes and Mattermost run on the same host with Docker, use
> `http://host.docker.internal:18065/mm-command` as the URL.

### 4. Environment Variables

```bash
export MATTERMOST_CALLBACK_BIND="0.0.0.0"
export MATTERMOST_CALLBACK_PORT="18065"
# Optional: HMAC signature verification for callbacks
export MATTERMOST_CALLBACK_SECRET="your-secret"
# Optional: restrict to specific user IDs
export MATTERMOST_ALLOWED_USERS="user_id_1,user_id_2"
```

### 5. Apply Companion Shell Patches

The two remaining `run.py` patches (see above) can be applied via the
`hermes-patches.sh` script that ships with your Hermes configuration:

```bash
~/.hermes/scripts/hermes-patches.sh apply
~/.hermes/scripts/hermes-patches.sh check   # verify
```

### 6. Restart

```bash
hermes gateway restart
```

## Usage

### `/model` — Switch Model

Open a Thread (or Channel), type `/model`. A dropdown card appears listing all
available models from your `config.yaml`. Select one to switch the current
session's model — other Threads are unaffected.

```
🔄 Switch Model
Current: zenmux/minimax-m2.7
Choose from the dropdown:
[Current: zenmux/minimax-m2.7  ▾]
```

After selection:

```
✅ Model switched: minimax-m2.7 → deepseek-v4-pro
💡 Re-select with /model
```

### `/new` — Reset Session

Type `/new` to reset the current session: clears model override, evicts agent
cache, and creates a fresh conversation context.

```
🆕 New Session
This will clear the conversation history.
[✅ Confirm]  [❌ Cancel]
```

### DM Approval

When a dangerous command is executed, the plugin sends a DM card:

```
⚠️ Dangerous Command Requires Approval
` ` `
rm -rf /data/cache/*
` ` `
**Reason:** destructive filesystem operation

[Allow Once] [Allow Session] [Always Allow] [Deny]
```

## Plugin Structure

```
mattermost-enhancer/
├── plugin.yaml              # Plugin metadata (kind=platform)
├── __init__.py              # Entry point: register_platform("mattermost")
├── adapter.py               # MattermostApprovalAdapter (31 methods, ~1180 lines)
│   ├── DM Approval          # send_exec_approval, _handle_callback, _verify_signature
│   ├── Callback Server      # _start/_stop_callback_server, connect, disconnect
│   ├── /model Handler       # 8 methods: _handle_model_command, _switch_session_model, etc.
│   ├── /new Handler         # 4 methods: _handle_new_command, _reset_session, etc.
│   ├── Thread root_id       # _resolve_root_id, send(), _send_local_file, _send_url_as_file
│   ├── send_typing          # Thread-aware typing indicator
│   └── send_model_picker    # Forward compat hook
├── cards.py                 # Interactive Message cards (select dropdown + button)
├── models.py                # Model list from custom_providers config
├── session.py               # Session key construction
├── callback_server.py       # Environment checks
└── references/
    └── api-contracts.md     # MM Slash Command & Interactive Message API spec
```

## Technical Details

- **Session Isolation**: Session key derived directly from MM Slash Command
  payload's `root_id` field — no API reverse-lookup needed
- **Model Picker**: Mattermost `select` dropdown (unlimited options) with current
  model shown as placeholder
- **Bot Identity**: Cards posted via Bot API (`_api_post`) for correct avatar
- **Model Awareness**: `_pending_model_notes` injection notifies the LLM of model
  changes so it correctly self-identifies
- **Provider Format**: Session override uses `custom:<name>` format to match
  Gateway's provider resolution chain
- **Button Dedup**: Denied/processed approvals return empty `actions` arrays to
  prevent repeated clicks
- **5-Action Limit**: Select dropdown bypasses Mattermost's 5 actions/attachment cap

## Migration Impact

```
mattermost.py: 1292 lines (4 patches) → 852 lines (zero modifications)
hermes-patches.sh: patches 6, 7, 10c removed (~673 lines of shell code)
```

## License

MIT — see [LICENSE](LICENSE)
