#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# hermes-mattermost-enhancer.sh — Mattermost Enhancer 配套 Shell Patch
# ═══════════════════════════════════════════════════════════════════════════
#
# 此脚本为 hermes-plugin-mattermost-enhancer 插件的配套补丁。
# 修复 Hermes Agent 上游代码中影响 Mattermost 用户体验的 Gateway 缺陷。
#
# 为什么需要此脚本：
#   这些问题修改的是 gateway/run.py、adapter.py 等代码。
#   Hermes Platform Plugin 机制只能覆盖适配器方法，无法触及调用方。
#   详见插件 README。
#
# 已在插件 adapter 中实现的修复（不需要 shell patch）：
#   ✅ WebSocket 心跳 30s→15s — 覆写 _ws_connect_and_listen()
#   ✅ _api_put 缺少 timeout — 覆写 edit_message() 自实现 HTTP PUT
#
# 活跃 patch（当前 5 个）：
#   P1. 工具进度消息进 Thread（gateway/run.py）
#       上游 v0.14.0 修复不完整 — 要求 thread_id 但 Mattermost
#       Channel-root 消息 source.thread_id 为 None。
#   P2. Clarify Session 分裂修复（gateway/run.py）
#       Mattermost Thread 模型下 thread_sessions_per_user 配置
#       导致 _quick_key ≠ canonical session key，Clarify 响应发到
#       错误的 session。
#   P3. Clarify 并发守护（gateway/run.py）
#       同上场景，session key 不匹配导致 Clarify 阻塞时
#       并发创建重复 Session。
#   P4. Session 串台修复（gateway/run.py）
#       Gateway 重启后同 channel 多 Thread auto-resume 时
#       响应串到错误的 Thread。
#   P5. Channel-root 消息 metadata/status 路由修复（gateway/run.py）
#       P1 修复了 _progress_reply_to，但 _progress_thread_id 和
#       _status_thread_metadata 仍为 None——导致 Clarify 卡片和
#       Working... 状态消息在 channel-root 场景下失去 Thread 路由。
#
#   已消除：
#     ❌ 评论→正文合并              → 已迁至主脚本 hermes-patches.sh（平台通用修复）
#     ❌ 幽灵代码围栏               → 已迁至主脚本 hermes-patches.sh（平台通用修复）
#     ❌ stream fallback 丢失 reply_to → 已迁至主脚本 hermes-patches.sh（平台通用修复）
#
#   版本感知：
#     最后验证: 2026-06-08
#     Hermes 版本: v2026.6.5-181-gc98637723 (origin/main)
#     验证方式: 双重验证（check_pattern + old_string match）
#
#   已验证（v2026.6.5 / origin:main=c98637723）：
#     P1. run.py (工具进度 Thread)     — ❌ 未合入，old_string ✅ 仍匹配
#     P2. run.py (Clarify Session)    — ❌ 未合入，old_string ✅ 仍匹配
#     P3. run.py (Clarify 并发守护)    — ❌ 未合入，old_string ✅ 仍匹配
#     P4. run.py (Session 串台去重)    — ❌ 未合入，old_string ✅ 仍匹配
#     P5. run.py (Channel metadata 路由) — ❌ 未合入，old_string ✅ 仍匹配
#
# 使用方法：
#   ./scripts/hermes-mattermost-enhancer.sh check   # 检查状态
#   ./scripts/hermes-mattermost-enhancer.sh apply   # 应用补丁（完成后询问是否立即重启）
#   ./scripts/hermes-mattermost-enhancer.sh status  # 同 check
#
# 必要条件：
#   - Hermes Agent 源码位于 ~/.hermes/hermes-agent/
#   - Python 3
#
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

AGENT_DIR="${HOME}/.hermes/hermes-agent"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()      { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()    { echo -e "${RED}[FAIL]${NC}  $1"; }
optional(){ echo -e "${YELLOW}[OPT]${NC}    $1"; }
info()    { echo -e "${CYAN}[INFO]${NC}  $1"; }

# ── 辅助函数 ──────────────────────────────────────────────────────────────

_do_patch() {
    local file="${AGENT_DIR}/$1"
    local label="$2"
    local check="$3"

    if [[ ! -f "$file" ]]; then
        fail "File not found: $1, skipped（文件不存在，已跳过）"
        return 1
    fi
    if grep -q "$check" "$file" 2>/dev/null; then
        ok "$label — already applied, skipping（已经好了，跳过）"
        return 0
    fi

    local output
    output=$(python3 - "$file" 2>&1)
    local rc=$?
    if [[ $rc -eq 0 && "$output" == *"APPLIED"* ]]; then
        ok "$label — applied successfully（修复成功）"
    elif [[ $rc -eq 0 && "$output" == *"SKIP"* ]]; then
        ok "$label — skipped, code already matches（跳过，代码已符合预期）"
    else
        fail "$label — failed, check if Hermes is properly installed（修复失败，请检查 Hermes 是否正常安装）"
        [[ -n "$output" ]] && echo "  $output"
    fi
    return $rc
}

# ── P1: 工具进度消息进 Thread ───────────────────────────────────────────
#
# 上游 v0.14.0 修复了 Mattermost 进度消息的 Thread 路由，但不完整：
#   `source.platform in (FEISHU, MATTERMOST) and source.thread_id`
# 要求必须有 thread_id。但 auto-resume 后的第一条消息还没有 thread_id，
# 此时进度消息会跑回主频道。
#
# 修复：拆成 or 分支 — 只要 platform == MATTERMOST 就绑定 reply_to。

patch_progress_thread() {
    _do_patch "gateway/run.py" \
        "Fix: task progress leaking to channel（修复「任务进度跑到频道里」的问题）" \
        'or source.platform == Platform.MATTERMOST' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, 'r') as f:
    content = f.read()

old = """        _progress_reply_to = (
            event_message_id
            if source.platform in (Platform.FEISHU, Platform.MATTERMOST) and source.thread_id and event_message_id
            else None
        )"""

new = """        _progress_reply_to = (
            event_message_id
            if (
                (source.platform == Platform.FEISHU and source.thread_id)
                or source.platform == Platform.MATTERMOST
            ) and event_message_id
            else None
        )"""

if old in content:
    content = content.replace(old, new)
    with open(file_path, 'w') as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P2: Clarify Session 分裂修复 ────────────────────────────────────────
#
# Mattermost Thread 模型下，thread_sessions_per_user 配置会导致
# _quick_key ≠ canonical session key。Clarify 使用 _quick_key 查找
# pending clarify，找不到就以为是新消息，创建新的 agent session，
# 导致「AI 失忆」（之前的对话上下文丢失）。

patch_clarify_session() {
    _do_patch "gateway/run.py" \
        "Fix: clarify session split causing AI amnesia（修复「Clarify 打断导致 AI 失忆」的问题）" \
        '_canonical_entry = self.session_store.get_or_create_session' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, 'r') as f:
    content = f.read()

old = '''            _pending_clarify = _clarify_mod.get_pending_for_session(_quick_key)
        except Exception:
            _pending_clarify = None'''

new = '''            _pending_clarify = _clarify_mod.get_pending_for_session(_quick_key)
            # When _quick_key doesn't match (thread_sessions_per_user config
            # mismatch), fall back to the canonical session key.  Only in
            # Thread contexts — non-Thread paths always have _quick_key ==
            # canonical key, and calling get_or_create_session there breaks
            # Telegram topic mode lobby.
            if _pending_clarify is None and source.thread_id:
                try:
                    _canonical_entry = self.session_store.get_or_create_session(source)
                    _canonical_key = _canonical_entry.session_key
                    if _canonical_key != _quick_key:
                        _pending_clarify = _clarify_mod.get_pending_for_session(_canonical_key)
                except Exception:
                    pass
        except Exception:
            _pending_clarify = None'''

if old in content:
    content = content.replace(old, new)
    with open(file_path, 'w') as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P3: Clarify 并发守护 ────────────────────────────────────────────────
#
# P2 修复了「找到 pending clarify」的问题，但如果 Clarify 正在阻塞
# 等待用户回复时，新消息会因为找不到 agent（_quick_key 不匹配）
# 而触发新的 Session 创建，导致并发重复 Session。
#
# 修复：在 session 创建前多加一道 canonical key 的 Clarify 检查。

patch_clarify_guard() {
    _do_patch "gateway/run.py" \
        "Fix: clarify concurrency guard against duplicate sessions（修复「Clarify 并发创建重复会话」的问题）" \
        'Gateway intercepted clarify at session guard' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, 'r') as f:
    content = f.read()

old = """        session_key = session_entry.session_key
        self._cache_session_source(session_key, source)"""

new = """        session_key = session_entry.session_key
        # Belt-and-suspenders clarify check using the canonical session
        # key.  When _quick_key != session_key and no agent is found in
        # _running_agents under _quick_key, intercept the message before
        # a new Session spawns.
        if session_key != _quick_key:
            try:
                from tools import clarify_gateway as _clarify_mod2
                _pc = _clarify_mod2.get_pending_for_session(session_key)
                if _pc is not None:
                    _raw = (event.text or "").strip()
                    if _raw and not _raw.startswith("/"):
                        _clarify_mod2.resolve_gateway_clarify(_pc.clarify_id, _raw)
                        logger.info(
                            "Gateway intercepted clarify at session guard "
                            "(session=%s, clarify_id=%s)",
                            session_key, _pc.clarify_id,
                        )
                        return None  # consumed by clarify — no new turn
            except Exception:
                pass
        self._cache_session_source(session_key, source)"""

if old in content:
    content = content.replace(old, new, 1)
    with open(file_path, 'w') as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P4: Session 串台修复 — 同 channel 多 thread auto-resume 去重 ──────
#
# Gateway 重启时，同一 channel 下多个 Thread 的 session 会同时 auto-resume。
# 此时响应可能从 Thread A 的 session 串到 Thread B，用户看到不相关的内容。
#
# 修复：auto-resume 候选去重，每 (platform, chat_id) 只保留 updated_at 最新的。

patch_session_dedup() {
    _do_patch "gateway/run.py" \
        "Fix: auto-resume session leaking into wrong thread（修复「Gateway重启后多条Thread session串台」的问题）" \
        'Deduplicate.*keep only the most recent' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, "r") as f:
    content = f.read()

old = """        except Exception as exc:
            logger.warning("Failed to enumerate resume-pending sessions: %s", exc)
            return 0

        now = datetime.now()"""

new = """        except Exception as exc:
            logger.warning("Failed to enumerate resume-pending sessions: %s", exc)
            return 0

        # Deduplicate: keep only the most recent session per (platform, chat_id).
        # When multiple threads in the same channel are auto-resumed
        # simultaneously (e.g. after a gateway crash), responses from one
        # thread can leak into another — the user sees a message about
        # an unrelated topic appearing in their current thread.
        _per_chat: dict = {}
        for entry in candidates:
            key = (entry.origin.platform, entry.origin.chat_id)
            existing = _per_chat.get(key)
            if (
                existing is None
                or (
                    entry.updated_at
                    and existing.updated_at
                    and entry.updated_at > existing.updated_at
                )
            ):
                _per_chat[key] = entry
        candidates = list(_per_chat.values())

        now = datetime.now()"""

if old in content:
    content = content.replace(old, new)
    with open(file_path, "w") as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P5: Channel-root metadata/status Thread 路由 ────────────────────────
#
# P1 修复了 _progress_reply_to 对 Mattermost 去掉 source.thread_id 限制，
# 但 _progress_thread_id 和 _status_thread_metadata 仍为 None（因为
# source.thread_id 在 channel-root 消息上为 None）。这导致：
#   - Clarify 卡片 (send_clarify → metadata=None → root_id=None) 落入 Channel
#   - Working... 状态消息 (_send_or_update_status_coro → metadata=None) 落入 Channel
#
# 修复：
#   1. _progress_thread_id: Mattermost channel-root 消息使用 event_message_id
#   2. _status_thread_metadata: _thread_metadata 返回 None 时降级为手动构造

patch_progress_metadata() {
    _do_patch "gateway/run.py" \
        "Fix: clarify cards + status messages leak to channel（修复「Clarify + Working 状态落入频道」的问题）" \
        'source.platform == Platform.MATTERMOST and not source.thread_id' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, 'r') as f:
    content = f.read()

# ── Part A: _progress_thread_id ──
old_a = """        if source.platform == Platform.SLACK:
            _progress_thread_id = source.thread_id or event_message_id
        else:
            _progress_thread_id = source.thread_id"""

new_a = """        if source.platform == Platform.SLACK:
            _progress_thread_id = source.thread_id or event_message_id
        elif source.platform == Platform.MATTERMOST and not source.thread_id:
            # Hermes creates the Thread upon reply when the user sends
            # a channel-root message. Use the event message ID as the
            # thread root so that metadata-based routing (clarify cards,
            # status messages) lands in the correct Thread.
            _progress_thread_id = event_message_id
        else:
            _progress_thread_id = source.thread_id"""

if old_a in content:
    content = content.replace(old_a, new_a)
    part_a_ok = True
else:
    part_a_ok = False

# ── Part B: _status_thread_metadata ──
old_b = "            _status_thread_metadata = self._thread_metadata_for_source(source, event_message_id) if _progress_thread_id else None"

new_b = """            _status_thread_metadata = (
                (
                    self._thread_metadata_for_source(source, event_message_id)
                    or {"thread_id": _progress_thread_id}
                )
                if _progress_thread_id else None
            )"""

if old_b in content:
    content = content.replace(old_b, new_b)
    part_b_ok = True
else:
    part_b_ok = False

if part_a_ok or part_b_ok:
    with open(file_path, 'w') as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── 状态检查 ──────────────────────────────────────────────────────────────

check_status() {
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo "  🔍 Checking Mattermost patches..."
    echo "     （正在检查 Mattermost 补丁）"
    echo "═══════════════════════════════════════════════════"
    echo ""

    # ── Built-in capabilities (adapter override, no shell patch needed) ──
    info "WebSocket heartbeat 15s — adapter override（WebSocket 心跳 15 秒）"
    info "Edit message timeout 30s — adapter override（编辑消息 30 秒超时）"
    echo ""

    local ok_count=0 total=5

    # P1
    if grep -q 'or source.platform == Platform.MATTERMOST' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "Fix: task progress leaking to channel（修复「任务进度跑到频道里」的问题）"
        ok_count=$((ok_count + 1))
    else
        warn "Fix: task progress leaking to channel（修复「任务进度跑到频道里」的问题）"
    fi

    # P2
    if grep -q '_canonical_entry = self.session_store.get_or_create_session' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "Fix: clarify session split causing AI amnesia（修复「Clarify 打断导致 AI 失忆」的问题）"
        ok_count=$((ok_count + 1))
    else
        warn "Fix: clarify session split causing AI amnesia（修复「Clarify 打断导致 AI 失忆」的问题）"
    fi

    # P3
    if grep -q 'Gateway intercepted clarify at session guard' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "Fix: clarify concurrency guard against duplicate sessions（修复「Clarify 并发创建重复会话」的问题）"
        ok_count=$((ok_count + 1))
    else
        warn "Fix: clarify concurrency guard against duplicate sessions（修复「Clarify 并发创建重复会话」的问题）"
    fi

    # P4
    if grep -q 'Deduplicate.*keep only the most recent' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "Fix: auto-resume session leaking into wrong thread（修复「Gateway重启后 session 串台」的问题）"
        ok_count=$((ok_count + 1))
    else
        warn "Fix: auto-resume session leaking into wrong thread（修复「Gateway重启后 session 串台」的问题）"
    fi

    # P5
    if grep -q 'source.platform == Platform.MATTERMOST and not source.thread_id' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "Fix: clarify cards + status messages leak to channel（修复「Clarify + Working 状态落入频道」的问题）"
        ok_count=$((ok_count + 1))
    else
        warn "Fix: clarify cards + status messages leak to channel（修复「Clarify + Working 状态落入频道」的问题）"
    fi

    echo ""
    echo "───────────────────────────────────────────────────"
    echo "  Shell patches: ${ok_count}/${total} required"
    echo "  （Shell 补丁：${ok_count}/${total} 必需）"
    echo "───────────────────────────────────────────────────"
    echo ""

    if [[ $ok_count -eq $total ]]; then
        ok "All required patches applied ✨（所有必需补丁已生效）"
    elif [[ $ok_count -eq 0 ]]; then
        warn "No patches applied yet, run: $0 apply（还没有安装任何补丁，建议运行：$0 apply）"
    else
        warn "Some required patches still missing (${ok_count}/${total}), run: $0 apply（还有必需补丁没装完，建议运行：$0 apply）"
    fi
}

# ── 重启 Gateway ──────────────────────────────────────────────────────────

restart_gateway() {
    echo ""
    info "Restarting Hermes...（正在重启 Hermes）"
    if hermes gateway restart 2>&1; then
        ok "Restarted — patches are now active!（已重启 — 补丁生效了！）"
    else
        fail "Restart failed, manually run: hermes gateway restart（重启失败，请手动执行：hermes gateway restart）"
    fi
    echo ""
}

# ── 应用所有 ──────────────────────────────────────────────────────────────

apply_all() {
    info "Fixing issues with Hermes in Mattermost...（正在修复 Mattermost 相关问题...）"
    echo ""
    patch_progress_thread
    patch_clarify_session
    patch_clarify_guard
    patch_session_dedup
    patch_progress_metadata
    echo ""
    ok "Patches applied!（补丁完成！）"
    echo ""

    # 交互式重启询问
    echo "───────────────────────────────────────────────────"
    echo -n "Restart required for patches to take effect. Restart now? [Y/n]（需要重启才能生效，是否现在重启？） "
    read -r REPLY
    echo ""

    case "${REPLY:-y}" in
        [Yy]|"")
            restart_gateway
            ;;
        *)
            warn "Skipped. Patches are installed but require a restart.（已跳过 — 补丁已安装，重启后生效）"
            warn "Manually restart later: hermes gateway restart（稍后手动执行：hermes gateway restart）"
            echo ""
            ;;
    esac

    check_status
}

# ── 主命令分发 ────────────────────────────────────────────────────────────

CMD="${1:-check}"

case "$CMD" in
    apply)
        apply_all
        ;;
    check|status)
        check_status
        ;;
    *)
        echo "Usage: $0 {apply|check|status}（用法）"
        echo ""
        echo "  check   — Check if all patches are applied (default)（检查所有补丁是否生效，默认）"
        echo "  apply   — Apply patches, then ask whether to restart（安装所有补丁，完成后询问是否重启）"
        echo "  status  — Same as check（同 check）"
        ;;
esac
