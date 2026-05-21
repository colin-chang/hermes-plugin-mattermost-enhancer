#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# hermes-mattermost-enhancer.sh — Mattermost Enhancer 配套 Shell Patch
# ═══════════════════════════════════════════════════════════════════════════
#
# 此脚本为 hermes-plugin-mattermost-enhancer 插件的配套补丁。
# 修复 Hermes Agent 上游代码中 Mattermost 适配器的两个调用方问题。
#
# 为什么需要此脚本：
#   这两个问题修改的是 gateway/run.py 中的调用方代码，
#   Hermes Platform Plugin 机制只能覆盖适配器方法，无法触及调用方。
#   详见插件 README。
#
# 问题 1 — DM 审批缺少 user_id 参数：
#   run.py 调用 send_exec_approval() 时没有传入 user_id，
#   导致插件无法知道将审批卡片发送给谁。
#
# 问题 2 — 工具进度消息不进 Thread：
#   run.py 的 _progress_reply_to 条件判断只检查了 Platform.FEISHU，
#   遗漏了 Platform.MATTERMOST，导致工具链进度回退到频道主会话流。
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
        warn "$1 文件不存在，跳过"
        return 1
    fi
    if grep -q "$check" "$file" 2>/dev/null; then
        ok "$label — 已经好了 ✅，跳过"
        return 0
    fi

    python3 - "$file"
    local rc=$?
    if [[ $rc -eq 0 ]]; then
        ok "$label — 修复成功 ✅"
    else
        warn "$label — 修复失败 ❌，请检查 Hermes 是否正常安装"
    fi
    return $rc
}

# ── Patch 1: DM 审批传入 user_id ─────────────────────────────────────────

patch_user_id() {
    _do_patch "gateway/run.py" \
        "修复「审批卡片收不到」的问题" \
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

# ── Patch 2: 工具进度进 Thread ────────────────────────────────────────────

patch_progress_thread() {
    _do_patch "gateway/run.py" \
        "修复「任务进度跑到频道里」的问题" \
        'or source.platform == Platform.MATTERMOST' <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path, 'r') as f:
    content = f.read()

old = '''        _progress_reply_to = (
            event_message_id
            if source.platform == Platform.FEISHU and source.thread_id and event_message_id
            else None
        )'''

new = '''        _progress_reply_to = (
            event_message_id
            if (
                (source.platform == Platform.FEISHU and source.thread_id)
                or source.platform == Platform.MATTERMOST
            ) and event_message_id
            else None
        )'''

if old in content:
    content = content.replace(old, new)
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
    echo "  🔍 正在检查你的 Hermes 是否完整支持 Mattermost..."
    echo "═══════════════════════════════════════════════════"
    echo ""

    local ok_count=0 total=2

    echo "  ── 检查 ①：审批卡片能不能发到你的私信 ──"
    echo ""
    if grep -q 'user_id=source.user_id' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "审批卡片能正常发送 ✅（Hermes 知道该把卡片发给谁）"
        ok_count=$((ok_count + 1))
    else
        warn "审批卡片可能收不到 ⚠️（Hermes 还不知道该私信谁）"
    fi

    echo ""
    echo "  ── 检查 ②：任务进度会显示在 Thread 还是频道里 ──"
    echo ""
    if grep -q 'or source.platform == Platform.MATTERMOST' "${AGENT_DIR}/gateway/run.py" 2>/dev/null; then
        ok "进度显示在 Thread 里 ✅（你在 Thread 里聊，进度就出现在 Thread 里）"
        ok_count=$((ok_count + 1))
    else
        warn "进度会跑到频道里 ⚠️（你在 Thread 里等结果，过程中却看不到任何反馈）"
    fi

    echo ""
    echo "───────────────────────────────────────────────────"
    echo "  检查结果：${ok_count}/${total} 项通过"
    echo "───────────────────────────────────────────────────"
    echo ""

    if [[ $ok_count -eq $total ]]; then
        ok "一切正常，所有修复都已生效，不需要再做什么 ✨"
    elif [[ $ok_count -eq 0 ]]; then
        warn "两项修复都还没装，建议运行：$0 apply"
    else
        warn "还有一项修复没装完，建议运行：$0 apply"
    fi
}

# ── 重启 Gateway ──────────────────────────────────────────────────────────

restart_gateway() {
    echo ""
    info "正在重启 Hermes..."
    if hermes gateway restart 2>&1; then
        ok "已重启 ✅ — 修复现在生效了！"
    else
        warn "重启失败，请稍后在终端手动执行：hermes gateway restart"
    fi
    echo ""
}

# ── 应用所有 ──────────────────────────────────────────────────────────────

apply_all() {
    info "正在修复 Hermes 在 Mattermost 里的两个小问题..."
    echo ""
    patch_user_id
    patch_progress_thread
    echo ""
    ok "修复完成！"
    echo ""

    # 交互式重启询问
    echo "───────────────────────────────────────────────────"
    echo -n "修复需要重启 Hermes 才能生效。是否现在重启？[Y/n] "
    read -r REPLY
    echo ""

    case "${REPLY:-y}" in
        [Yy]|"")
            restart_gateway
            ;;
        *)
            warn "已跳过。修复已经安装好了，但需要重启后才能生效。"
            warn "请稍后手动执行：hermes gateway restart"
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
        echo "用法: $0 {apply|check|status}"
        echo ""
        echo "  check   — 检查两个修复是否生效（默认）"
        echo "  apply   — 安装修复，完成后询问是否立即重启 Gateway"
        echo "  status  — 同 check"
        ;;
esac
