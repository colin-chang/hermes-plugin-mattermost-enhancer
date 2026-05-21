# hermes-plugin-mattermost-enhancer

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-≥%200.14.0-blue)](https://github.com/nousresearch/hermes-agent)

A Hermes Platform Plugin that extends the Mattermost adapter with interactive
message capabilities — DM approval cards, model switching, session reset, and
several bug fixes — all without modifying Hermes source code.

## Features

| Feature | Trigger | Description |
|---------|---------|-------------|
| **DM Approval** | Auto (dangerous commands) | Interactive button cards: Allow Once / Session / Always / Deny |
| **Thread root_id Fix** | Auto | CRT mode: root_id correctly points to thread root post |
| **MEDIA Silent Skip** | Auto | Missing files are silently skipped instead of posting noise |
| **send_typing Thread Routing** | Auto | Typing indicator follows the current Thread context |
| **Model Switch `/model`** | Slash Command | Dropdown model picker, scoped to current Thread only |
| **Session Reset `/new`** | Slash Command | Clear model override + agent cache + session state |
| **Callback Server** | Auto | HTTP server with `/mattermost/callback` + `/mm-command` routes |

### send_typing Thread Routing

The built-in `MattermostAdapter.send_typing()` only sends `channel_id`, causing
the typing indicator to appear at the channel level even when replying in a
Thread. This plugin overrides `send_typing()` to pass `parent_id` when a
`thread_id` is present in metadata, routing the indicator to the correct Thread.

### Companion Shell Script

Two fixes in `gateway/run.py` modify **caller-side code** that a Platform Plugin
cannot reach. A companion shell script is provided to apply these:

| Fix | File | Why Plugins Can't Fix It |
|-----|------|--------------------------|
| DM Approval `user_id` param | `run.py` | The caller of `send_exec_approval()` does not pass `user_id` |
| Progress messages in Thread | `run.py` | `_progress_reply_to` only checks `Platform.FEISHU` |

Apply the companion script after installing the plugin:

```bash
./scripts/hermes-mattermost-enhancer.sh check   # check status
./scripts/hermes-mattermost-enhancer.sh apply   # apply patches
```

> These two fixes can also be submitted as upstream PRs to Hermes Agent.

## Installation

### Prerequisites

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) ≥ 0.14.0
- Mattermost server with Bot account (`post:all` permission)
- Python ≥ 3.11

### 1. Install

```bash
git clone https://github.com/colin-chang/hermes-plugin-mattermost-enhancer.git \
  ~/.hermes/plugins/hermes-plugin-mattermost-enhancer
```

### 2. Enable

Add to `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - hermes-plugin-mattermost-enhancer
```

### 3. Configure Mattermost Slash Commands

In System Console → Integrations → Slash Commands:

| Command | Request URL |
|---------|-------------|
| `/model` | `http://<hermes-host>:18065/mm-command` |
| `/new` | `http://<hermes-host>:18065/mm-command` |

> For Docker setups on the same host, use `http://host.docker.internal:18065/mm-command`.

### 4. Environment Variables

```bash
export MATTERMOST_CALLBACK_BIND="0.0.0.0"
export MATTERMOST_CALLBACK_PORT="18065"
# Optional: HMAC signature verification
export MATTERMOST_CALLBACK_SECRET="your-secret"
# Optional: restrict to specific users
export MATTERMOST_ALLOWED_USERS="user_id_1,user_id_2"
```

### 5. Apply Companion Patches

```bash
cd ~/.hermes/plugins/hermes-plugin-mattermost-enhancer
./scripts/hermes-mattermost-enhancer.sh apply
```

### 6. Restart

```bash
hermes gateway restart
```

## Usage

### `/model` — Switch Model

Type `/model` in a Thread (or Channel). A dropdown card lists all available
models. Select one to switch the current session's model — other Threads are
unaffected.

### `/new` — Reset Session

Type `/new` to reset: clears model override, evicts agent cache, fresh context.

### DM Approval

When a dangerous command is executed, the plugin sends an interactive card to
your DM with Allow Once / Session / Always / Deny buttons.

## Structure

```
hermes-plugin-mattermost-enhancer/
├── plugin.yaml              # Plugin metadata
├── __init__.py              # register_platform("mattermost")
├── adapter.py               # MattermostApprovalAdapter (31 methods)
│   ├── DM Approval          # send_exec_approval, _handle_callback, etc.
│   ├── Callback Server      # _start/_stop_callback_server, connect, disconnect
│   ├── /model Handler       # _handle_model_command, _switch_session_model, etc.
│   ├── /new Handler         # _handle_new_command, _reset_session, etc.
│   ├── Thread root_id       # _resolve_root_id, send(), _send_local_file, _send_url_as_file
│   └── send_typing          # Thread-aware typing indicator
├── cards.py                 # Interactive Message cards
├── models.py                # Model list from custom_providers config
├── callback_server.py       # Environment checks
├── scripts/
│   └── hermes-mattermost-enhancer.sh   # Companion shell patches
└── references/
    └── api-contracts.md     # MM Slash Command & Interactive Message API spec
```

## Technical Details

- **Session Isolation**: Session key derived from MM Slash Command payload's
  `root_id` field — no API reverse-lookup needed
- **Model Picker**: Mattermost `select` dropdown (unlimited options), current
  model shown as placeholder
- **Bot Identity**: Cards posted via Bot API for correct avatar
- **Model Awareness**: `_pending_model_notes` injection notifies the LLM
- **Provider Format**: Session override uses `custom:<name>` format
- **Button Dedup**: Processed approvals return empty `actions` arrays

## License

MIT — see [LICENSE](LICENSE)
