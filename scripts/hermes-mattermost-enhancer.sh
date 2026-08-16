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
#   活跃 patch（当前 3 个）：
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
#
#   已移除：
#     ❌ P1 工具进度进 Thread → 上游 _handle_ws_event 已对 thread 模式
#       channel-root 帖子置 thread_id=post_id，配合 _resolve_progress_thread_id
#       + _progress_metadata + adapter send() 的 metadata.thread_id fallback，
#       进度消息已正确进 Thread（前提失效 + old_string 断裂，移除）。
#     ❌ P5 Status 路由 → 上游 v2026.7.30 重构 _status_thread_metadata，
#       引入 _thread_metadata_for_target 降级路径，功能等价实现。
#
#   已消除：
#     ❌ 评论→正文合并              → 已迁至主脚本 hermes-patches.sh（平台通用修复）
#     ❌ 幽灵代码围栏               → 已迁至主脚本 hermes-patches.sh（平台通用修复）
#     ❌ stream fallback 丢失 reply_to → 已迁至主脚本 hermes-patches.sh（平台通用修复）
#
#   版本感知：
#     最后验证: 2026-08-16
#     Hermes 版本: v2026.8.13-834-gb2369172ad (origin/main=b2369172ad)
#     验证方式: 双重验证（check_pattern + old_string match）
#     上游变更：
#       P1 — 上游 _progress_reply_to 重构为多行括号 + _relay_prospective_thread_id，
#       且 _handle_ws_event 已对 channel-root 置 thread_id=post_id，前提失效，移除。
#       P4 — 上游 _restart_loop_guard_config 返回 3 元组 + check_and_record
#       多行调用（max_gap_seconds），old_string 断裂，改用最小锚点重写。
#
#   已验证（v2026.8.13-834 / origin:main=b2369172ad）：
#     P1. run.py (工具进度 Thread)     — ✅ 前提失效 + old_string 断裂，移除
#     P2. run.py (Clarify Session)    — ❌ 未合入，old_string ✅ 仍匹配，改用 async_session_store
#     P3. run.py (Clarify 并发守护)    — ❌ 未合入，old_string ✅ 仍匹配
#     P4. run.py (Session 串台去重)    — ❌ 未合入，old_string ✅ 重写（最小锚点 Defense-3 注释）
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

# ── P2: Clarify Session 分裂修复 ────────────────────────────────────────
#
# Mattermost Thread 模型下，thread_sessions_per_user 配置会导致
# _quick_key ≠ canonical session key。Clarify 使用 _quick_key 查找
# pending clarify，找不到就以为是新消息，创建新的 agent session，
# 导致「AI 失忆」（之前的对话上下文丢失）。

patch_clarify_session() {
    _do_patch "gateway/run.py" \
        "Fix: clarify session split causing AI amnesia（修复「Clarify 打断导致 AI 失忆」的问题）" \
        '_canonical_entry = await self.async_session_store.get_or_create_session' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, 'r') as f:
    content = f.read()

old = '''            _pending_clarify = _clarify_mod.get_pending_for_session(
                _quick_key, include_choice_prompts=True,
            )
        except Exception:
            _pending_clarify = None'''

new = '''            _pending_clarify = _clarify_mod.get_pending_for_session(
                _quick_key, include_choice_prompts=True,
            )
            # When _quick_key doesn't match (thread_sessions_per_user config
            # mismatch), fall back to the canonical session key.  Only in
            # Thread contexts — non-Thread paths always have _quick_key ==
            # canonical key, and calling get_or_create_session there breaks
            # Telegram topic mode lobby.
            if _pending_clarify is None and source.thread_id:
                try:
                    _canonical_entry = await self.async_session_store.get_or_create_session(source)
                    _canonical_key = _canonical_entry.session_key
                    if _canonical_key != _quick_key:
                        _pending_clarify = _clarify_mod.get_pending_for_session(
                            _canonical_key, include_choice_prompts=True,
                        )
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
# 上游 v2026.7.7.2-1653 (8f33e39682) 完全移除了「Preserve original session
# source」注释块和 _get_cached_session_source guard，改为无条件调用
# _cache_session_source。
#
# v2026.7.7.5: 自适应缩进 — 运行时检测 hermes-patches.sh P60a 守卫是否存在，
# 自动选择 12sp（守卫内）或 8sp（无守卫），兼容独立安装和联合使用两种场景。
# old_string 使用 \n 前缀防止 12sp/8sp 子串误匹配。
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

# P60a guard (from hermes-patches.sh) may wrap this region with an
# additional `if not self._get_cached_session_source` at 8-space.
# When present, our clarify check must sit at 12-space inside the guard;
# _cache_session_source stays at 8-space outside (matching Colin's fix).
_p60a_guard = "if not self._get_cached_session_source(session_key):" in content
_ind = "            " if _p60a_guard else "        "  # 12sp vs 8sp

# old_string adapts to P60a guard presence: matches the 12sp guarded
# copy when guard exists, the 8sp original otherwise.  \n prefix
# prevents false substring matches across indent levels.
old = f"\n{_ind}self._cache_session_source(session_key, source)"

new = "\n" + f"""{_ind}# Belt-and-suspenders clarify check using the canonical session
{_ind}# key.  When _quick_key != session_key and no agent is found in
{_ind}# _running_agents under _quick_key, intercept the message before
{_ind}# a new Session spawns.
{_ind}if session_key != _quick_key:
{_ind}    try:
{_ind}        from tools import clarify_gateway as _clarify_mod2
{_ind}        _pc = _clarify_mod2.get_pending_for_session(session_key)
{_ind}        if _pc is not None:
{_ind}            _raw = (event.text or "").strip()
{_ind}            if _raw and not _raw.startswith("/"):
{_ind}                _clarify_mod2.resolve_gateway_clarify(_pc.clarify_id, _raw)
{_ind}                logger.info(
{_ind}                    "Gateway intercepted clarify at session guard "
{_ind}                    "(session=%s, clarify_id=%s)",
{_ind}                    session_key, _pc.clarify_id,
{_ind}                )
{_ind}                return None  # consumed by clarify — no new turn
{_ind}    except Exception:
{_ind}        pass
        self._cache_session_source(session_key, source)"""

if old in content and "Gateway intercepted clarify at session guard" not in content:
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

old = """        # Defense-3 (#30719): break the SIGTERM-respawn loop. Only count this"""

new = """        # Deduplicate: keep only the most recent session per (platform, chat_id).
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

        # Defense-3 (#30719): break the SIGTERM-respawn loop. Only count this"""

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
    echo "  🔍 Checking Mattermost patches..."
    echo "     （正在检查 Mattermost 补丁）"
    echo "═══════════════════════════════════════════════════"
    echo ""

    # ── Built-in capabilities (adapter override, no shell patch needed) ──
    info "WebSocket heartbeat 15s — adapter override（WebSocket 心跳 15 秒）"
    info "Edit message timeout 30s — adapter override（编辑消息 30 秒超时）"
    echo ""

    local ok_count=0 total=3

    # P2
    if grep -q '_canonical_entry = await self.async_session_store.get_or_create_session' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
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
    patch_clarify_session
    patch_clarify_guard
    patch_session_dedup
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
