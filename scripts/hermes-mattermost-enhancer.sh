#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# hermes-mattermost-enhancer.sh — Mattermost Enhancer 配套 Shell Patch
# ═══════════════════════════════════════════════════════════════════════════
#
# 此脚本为 hermes-plugin-mattermost-enhancer 插件的配套补丁。
# 修复 Hermes Agent 上游代码中影响 Mattermost 用户体验的 Gateway 缺陷——
# 插件架构（Platform Plugin override）只能覆盖适配器方法，无法触及调用方代码。
#
# 为什么需要此脚本：
#   这些问题修改的是 gateway/run.py、stream_consumer.py、base.py 等
#   调用方代码，Hermes Platform Plugin 机制只能覆盖适配器方法，无法触及调用方。
#   详见插件 README。
#
# Patch 列表：
#   P1. DM 审批传入 user_id（run.py）
#   P2. 工具进度消息进 Thread（run.py）— 上游 v0.14.0 修复不完整
#   P3. Clarify Session 分裂修复（run.py）
#   P4. Clarify 并发守护（run.py）
#   P5. 评论→正文合并，防止消息碎片化（stream_consumer.py）
#   P6. WebSocket 心跳优化 30s→15s（adapter.py）
#   P7. stream fallback 丢失 reply_to（stream_consumer.py）
#   P8. _api_put 缺少 timeout（adapter.py）
#   P9. 幽灵代码围栏修复（base.py）
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
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}    $1"; }
warn() { echo -e "${RED}[FAIL]${NC}  $1"; }
info() { echo -e "${CYAN}[INFO]${NC}  $1"; }

# ── 辅助函数 ──────────────────────────────────────────────────────────────

_do_patch() {
    local file="${AGENT_DIR}/$1"
    local label="$2"
    local check="$3"

    if [[ ! -f "$file" ]]; then
        warn "File not found: $1, skipped（文件不存在，已跳过）"
        return 1
    fi
    if grep -q "$check" "$file" 2>/dev/null; then
        ok "$label — already applied ✅, skipping（已经好了，跳过）"
        return 0
    fi

    python3 - "$file"
    local rc=$?
    if [[ $rc -eq 0 ]]; then
        ok "$label — applied successfully ✅（修复成功）"
    else
        warn "$label — failed ❌, check if Hermes is properly installed（修复失败，请检查 Hermes 是否正常安装）"
    fi
    return $rc
}

# ── P1: DM 审批传入 user_id ─────────────────────────────────────────────

patch_user_id() {
    _do_patch "gateway/run.py" \
        "Fix: approval card not being delivered（修复「审批卡片收不到」的问题）" \
        'user_id=source.user_id' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, 'r') as f:
    content = f.read()

old = '''                            _status_adapter.send_exec_approval(
                                chat_id=_status_chat_id,
                                command=cmd,
                                session_key=_approval_session_key,
                                description=desc,
                                metadata=_status_thread_metadata,
                            ),'''

new = '''                            _status_adapter.send_exec_approval(
                                chat_id=_status_chat_id,
                                command=cmd,
                                session_key=_approval_session_key,
                                description=desc,
                                metadata=_status_thread_metadata,
                                user_id=source.user_id if hasattr(source, 'user_id') else None,
                            ),'''

if old in content and "user_id=source.user_id" not in content:
    content = content.replace(old, new)
    with open(file_path, 'w') as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P2: 工具进度消息进 Thread ───────────────────────────────────────────

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

# ── P3: Clarify Session 分裂修复 ────────────────────────────────────────

patch_clarify_session() {
    _do_patch "gateway/run.py" \
        "Fix: clarify session split causing AI amnesia（修复「Clarify 等待时新消息打断导致 AI 失忆」的问题）" \
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

# ── P4: Clarify 并发守护 ────────────────────────────────────────────────

patch_clarify_guard() {
    _do_patch "gateway/run.py" \
        "Fix: clarify concurrency guard against duplicate sessions（修复「Clarify 阻塞时并发创建重复会话」的问题）" \
        'Gateway intercepted clarify at session guard' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, 'r') as f:
    content = f.read()

old = "        session_key = session_entry.session_key\n        self._cache_session_source(session_key, source)"

new = "        session_key = session_entry.session_key\n"
new += "        # Belt-and-suspenders clarify check using the canonical session\n"
new += "        # key.  When _quick_key != session_key and no agent is found in\n"
new += "        # _running_agents under _quick_key, intercept the message before\n"
new += "        # a new Session spawns.\n"
new += "        if session_key != _quick_key:\n"
new += "            try:\n"
new += '                from tools import clarify_gateway as _clarify_mod2\n'
new += "                _pc = _clarify_mod2.get_pending_for_session(session_key)\n"
new += "                if _pc is not None:\n"
new += '                    _raw = (event.text or "").strip()\n'
new += '                    if _raw and not _raw.startswith("/"):\n'
new += "                        _clarify_mod2.resolve_gateway_clarify(_pc.clarify_id, _raw)\n"
new += "                        logger.info(\n"
new += '                            "Gateway intercepted clarify at session guard "\n'
new += '                            "(session=%s, clarify_id=%s)",\n'
new += "                            session_key, _pc.clarify_id,\n"
new += "                        )\n"
new += "                        return None  # consumed by clarify — no new turn\n"
new += "            except Exception:\n"
new += "                pass\n"
new += "        self._cache_session_source(session_key, source)"

if old in content:
    content = content.replace(old, new, 1)
    with open(file_path, 'w') as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P5: 评论→正文合并（防止消息碎片化） ─────────────────────────────────

patch_commentary_merge() {
    _do_patch "gateway/stream_consumer.py" \
        "Fix: response fragmented into multiple messages（修复「回复碎成很多条消息」的问题）" \
        'Accumulate commentary' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, "r") as f:
    content = f.read()

old = """                if commentary_text is not None:
                    self._reset_segment_state()
                    await self._send_commentary(commentary_text)
                    self._last_edit_time = time.monotonic()
                    self._reset_segment_state()"""

new = """                if commentary_text is not None:
                    # Accumulate commentary into the stream buffer instead of
                    # sending as a separate message.  Prevents response fragmentation
                    # across multiple messages on platforms like Mattermost.
                    if self._accumulated:
                        self._accumulated += "\\n\\n"
                    self._accumulated += commentary_text"""

if old in content:
    content = content.replace(old, new)
    with open(file_path, "w") as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P6: WebSocket 心跳优化 30s→15s ──────────────────────────────────────

patch_ws_heartbeat() {
    _do_patch "plugins/platforms/mattermost/adapter.py" \
        "Fix: WebSocket disconnects every ~50s close 258（修复「WebSocket每50秒断开重连」的问题）" \
        'heartbeat=15.0' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, "r") as f:
    content = f.read()

old = "self._ws = await self._session.ws_connect(ws_url, heartbeat=30.0)"
new = "self._ws = await self._session.ws_connect(ws_url, heartbeat=15.0)"

if old in content:
    content = content.replace(old, new)
    with open(file_path, "w") as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P7: stream fallback 丢失 reply_to ───────────────────────────────────

patch_stream_fallback_reply_to() {
    _do_patch "gateway/stream_consumer.py" \
        "Fix: thread replies lost on fallback send（修复「Thread回复在stream fallback时丢失」的问题）" \
        'reply_to=self._initial_reply_to_id' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, "r") as f:
    content = f.read()

old = """                result = await self.adapter.send(
                    chat_id=self.chat_id,
                    content=chunk,
                    metadata=self.metadata,
                )"""

new = """                result = await self.adapter.send(
                    chat_id=self.chat_id,
                    content=chunk,
                    reply_to=self._initial_reply_to_id,
                    metadata=self.metadata,
                )"""

if old in content:
    content = content.replace(old, new)
    with open(file_path, "w") as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P8: Mattermost _api_put 缺少 timeout ───────────────────────────────

patch_api_put_timeout() {
    _do_patch "plugins/platforms/mattermost/adapter.py" \
        "Fix: message edit hangs silently（修复「消息编辑超时无错误信息」的问题）" \
        'timeout=aiohttp.ClientTimeout(total=30)' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, "r") as f:
    content = f.read()

old = """            async with self._session.put(
                url, headers=self._headers(), json=payload
            ) as resp:"""

new = """            async with self._session.put(
                url, headers=self._headers(), json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:"""

if old in content:
    content = content.replace(old, new)
    with open(file_path, "w") as f:
        f.write(content)
    print("APPLIED")
else:
    print("SKIP")
PYEOF
}

# ── P9: 幽灵代码围栏修复 ────────────────────────────────────────────────

patch_ghost_fence() {
    _do_patch "gateway/platforms/base.py" \
        "Fix: ghost empty code blocks in long responses（修复「长代码块出现幽灵空代码围栏」的问题）" \
        'reopening the fence would create' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, "r") as f:
    content = f.read()

old = """        while remaining:
            # If we're continuing a code block from the previous chunk,
            # prepend a new opening fence with the same language tag.
            prefix = f\"```{carry_lang}\\n\" if carry_lang is not None else \"\""""

new = """        while remaining:
            # When the previous chunk's closing fence is immediately followed
            # by the original content's own closing `` ``` `` (because the
            # split cut right before it), reopening the fence would create a
            # ghost empty block::
            #
            #     ```python
            #     ```
            #
            # Detect this and consume the original closing fence without
            # reopening, so the code block ends cleanly at the chunk boundary.
            if carry_lang is not None:
                stripped_line = remaining.lstrip().split("\\n", 1)[0].rstrip()
                if stripped_line.startswith("```") and not stripped_line[3:].strip():
                    # The first meaningful line is a bare `` ``` `` — the
                    # original closing fence.  Consume it and clear the
                    # carry so we don't reopen.
                    idx = remaining.index("```")
                    remaining = remaining[idx + 3:]
                    if remaining.startswith("\\n"):
                        remaining = remaining[1:]
                    remaining = remaining.lstrip()
                    carry_lang = None
                    continue

            # If we're continuing a code block from the previous chunk,
            # prepend a new opening fence with the same language tag.
            prefix = f\"```{carry_lang}\\n\" if carry_lang is not None else \"\""""

if old in content:
    content = content.replace(old, new)
    with open(file_path, "w") as f:
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
    echo "  🔍 Checking if your Hermes fully supports Mattermost..."
    echo "     （正在检查你的 Hermes 是否完整支持 Mattermost）"
    echo "═══════════════════════════════════════════════════"
    echo ""

    local ok_count=0 total=9

    # ── P1 ──
    echo "  ── Check ①: Can approval cards reach your DMs? ──"
    echo "     （审批卡片能不能发到你的私信）"
    echo ""
    if grep -q 'user_id=source.user_id' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "Approval cards work ✅ (Hermes knows who to DM)（审批卡片能正常发送 — Hermes 知道发给谁）"
        ok_count=$((ok_count + 1))
    else
        warn "Approval cards may not arrive ⚠️ (Hermes doesn't know who to DM)（审批卡片可能收不到 — Hermes 不知道该私信谁）"
    fi

    # ── P2 ──
    echo ""
    echo "  ── Check ②: Do tool progress messages stay inside the Thread? ──"
    echo "     （工具调用进度消息是否在 Thread 内显示）"
    echo ""
    if grep -q 'or source.platform == Platform.MATTERMOST' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "Progress in Thread ✅ (tool calls stay in thread, not in channel)（进度在 Thread 中 — 工具调用不会跑到频道里）"
        ok_count=$((ok_count + 1))
    else
        warn "Progress may leak to channel ⚠️ (tool calls appear outside thread)（进度可能泄露到频道 — 工具调用跑到 Thread 外面了）"
    fi

    # ── P3 ──
    echo ""
    echo "  ── Check ③: Will the AI forget what you were talking about? ──"
    echo "     （AI 会不会突然忘记刚才在聊什么——Clarify 等待时失忆）"
    echo ""
    if grep -q '_canonical_entry = self.session_store.get_or_create_session' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "No more AI amnesia ✅ (clarify replies stay in the same session)（不会失忆了 — Clarify 回复保持在同一会话中）"
        ok_count=$((ok_count + 1))
    else
        warn "AI may forget context ⚠️ (new session created while waiting for clarify reply)（AI 可能失忆 — 等待 Clarify 回复时可能创建新会话）"
    fi

    # ── P4 ──
    echo ""
    echo "  ── Check ④: Is there a failsafe against duplicate sessions? ──"
    echo "     （有没有兜底防护防止并发创建重复会话）"
    echo ""
    if grep -q 'Gateway intercepted clarify at session guard' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "Failsafe active ✅ (last-moment guard prevents duplicate sessions)（兜底防护已激活 — 最后一刻拦截重复会话）"
        ok_count=$((ok_count + 1))
    else
        warn "No failsafe ⚠️ (rare race condition could still split sessions)（缺少兜底防护 — 极端情况下仍可能分裂会话）"
    fi

    # ── P5 ──
    echo ""
    echo "  ── Check ⑤: Are responses fragmented into multiple messages? ──"
    echo "     （回复会不会碎成很多条消息）"
    echo ""
    if grep -q 'Accumulate commentary' "${AGENT_DIR}/gateway/stream_consumer.py" 2>/dev/null; then
        ok "No fragmentation ✅ (commentary merged into stream)（不会碎片化 — 评论合并到正文流中）"
        ok_count=$((ok_count + 1))
    else
        warn "Responses may fragment ⚠️ (commentary sent as separate messages)（回复可能碎片化 — 评论作为独立消息发送）"
    fi

    # ── P6 ──
    echo ""
    echo "  ── Check ⑥: Is the WebSocket connection stable? ──"
    echo "     （WebSocket 连接是否稳定）"
    echo ""
    if grep -q 'heartbeat=15.0' "${AGENT_DIR}/plugins/platforms/mattermost/adapter.py" 2>/dev/null; then
        ok "WebSocket stable ✅ (heartbeat=15s, no more 258 disconnects)（连接稳定 — 心跳15秒，不再断连）"
        ok_count=$((ok_count + 1))
    else
        warn "WebSocket may disconnect ⚠️ (heartbeat=30s, closes every ~50s with code 258)（可能断连 — 心跳30秒，每50秒断一次）"
    fi

    # ── P7 ──
    echo ""
    echo "  ── Check ⑦: Do fallback sends preserve Thread routing? ──"
    echo "     （fallback 发送是否保持 Thread 路由）"
    echo ""
    if grep -q 'reply_to=self._initial_reply_to_id' "${AGENT_DIR}/gateway/stream_consumer.py" 2>/dev/null; then
        ok "Thread routing OK ✅ (fallback sends include reply_to)（Thread 路由正常 — fallback 发送包含 reply_to）"
        ok_count=$((ok_count + 1))
    else
        warn "Thread routing broken ⚠️ (fallback sends missing reply_to, replies leak to channel)（Thread 路由丢失 — fallback 发送缺少 reply_to，回复跑到频道根级别）"
    fi

    # ── P8 ──
    echo ""
    echo "  ── Check ⑧: Does message edit have proper timeout? ──"
    echo "     （消息编辑是否有超时设置）"
    echo ""
    if grep -q 'timeout=aiohttp.ClientTimeout(total=30)' "${AGENT_DIR}/plugins/platforms/mattermost/adapter.py" 2>/dev/null; then
        ok "Edit timeout OK ✅ (30s timeout on _api_put)（编辑超时正常 — _api_put 有 30 秒超时）"
        ok_count=$((ok_count + 1))
    else
        warn "Edit may hang ⚠️ (_api_put has no timeout, silent failure on network issues)（编辑可能卡住 — _api_put 无超时，网络问题导致静默失败）"
    fi

    # ── P9 ──
    echo ""
    echo "  ── Check ⑨: Any ghost empty code blocks? ──"
    echo "     （长代码块有没有幽灵空代码围栏）"
    echo ""
    if grep -q 'reopening the fence would create' "${AGENT_DIR}/gateway/platforms/base.py" 2>/dev/null; then
        ok "No ghost fences ✅ (truncate_message handles chunk boundaries correctly)（没有幽灵围栏 — 长代码块分片边界处理正确）"
        ok_count=$((ok_count + 1))
    else
        warn "Ghost fences possible ⚠️ (empty code blocks appear in long code responses)（可能有幽灵围栏 — 长代码回复中出现空代码块）"
    fi

    echo ""
    echo "───────────────────────────────────────────────────"
    echo "  Result: ${ok_count}/${total} passed（检查结果：${ok_count}/${total} 项通过）"
    echo "───────────────────────────────────────────────────"
    echo ""

    if [[ $ok_count -eq $total ]]; then
        ok "All good, every fix is working ✨（一切正常，所有修复都已生效）"
    elif [[ $ok_count -eq 0 ]]; then
        warn "No fixes applied yet, run: $0 apply（还没有安装任何修复，建议运行：$0 apply）"
    else
        warn "Some fixes still missing (${ok_count}/${total}), run: $0 apply（还有修复没装完 ${ok_count}/${total}，建议运行：$0 apply）"
    fi
}

# ── 重启 Gateway ──────────────────────────────────────────────────────────

restart_gateway() {
    echo ""
    info "Restarting Hermes...（正在重启 Hermes）"
    if hermes gateway restart 2>&1; then
        ok "Restarted ✅ — fixes are now active!（已重启 — 修复生效了！）"
    else
        warn "Restart failed, manually run: hermes gateway restart（重启失败，请手动执行：hermes gateway restart）"
    fi
    echo ""
}

# ── 应用所有 ──────────────────────────────────────────────────────────────

apply_all() {
    info "Fixing issues with Hermes in Mattermost...（正在修复 Mattermost 相关问题...）"
    echo ""
    patch_user_id
    patch_progress_thread
    patch_clarify_session
    patch_clarify_guard
    patch_commentary_merge
    patch_ws_heartbeat
    patch_stream_fallback_reply_to
    patch_api_put_timeout
    patch_ghost_fence
    echo ""
    ok "Fixes applied!（修复完成！）"
    echo ""

    # 交互式重启询问
    echo "───────────────────────────────────────────────────"
    echo -n "Restart required for fixes to take effect. Restart now? [Y/n]（需要重启才能生效，是否现在重启？） "
    read -r REPLY
    echo ""

    case "${REPLY:-y}" in
        [Yy]|"")
            restart_gateway
            ;;
        *)
            warn "Skipped. Fixes are installed but require a restart.（已跳过 — 修复已安装，重启后生效）"
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
        echo "  check   — Check if all fixes are applied (default)（检查所有修复是否生效，默认）"
        echo "  apply   — Apply fixes, then ask whether to restart（安装所有修复，完成后询问是否重启）"
        echo "  status  — Same as check（同 check）"
        ;;
esac
