"""单元测试 — DM 审批发起者精确定位（修复多用户频道误发管理员）。

验证 MattermostApprovalAdapter 的 sender 追踪链路：
  1. build_source 覆写记录入站消息的 sender
  2. send_exec_approval 在 user_id 缺失时，优先用追踪结果定位发起者，
     而非 members 反查（多用户频道下 members 反查会误取第一个非 bot = 管理员）。

多用户频道的复现场景：
  - 管理员 admin 先发言 → members 反查会返回 admin
  - 普通用户 user1 后发起危险命令 → 审批 DM 必须发给 user1

不依赖真实 MM 服务器 / gateway runner — 全部 mock。
"""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

# ── stub 掉 hermes 运行时依赖（与 test_callback_responsive.py 同法） ──
types_mod = __import__("types")
gateway_mod = types_mod.ModuleType("gateway")
platforms_mod = types_mod.ModuleType("gateway.platforms")
base_mod = types_mod.ModuleType("gateway.platforms.base")


class SendResult:
    def __init__(self, success=True, message_id=None, error=None):
        self.success = success
        self.message_id = message_id
        self.error = error


base_mod.SendResult = SendResult


class Source:
    """模拟 SessionSource 返回值。"""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


bundled_mm = types_mod.ModuleType("hermes_plugins.platforms_mattermost.adapter")


class MattermostAdapter:
    MAX_POST_LENGTH = 4000

    def __init__(self, config):
        self.config = config
        self._bot_user_id = "bot123"
        self._base_url = "http://localhost:8065"
        self._token = "tok"
        self._reply_mode = "thread"
        self._closing = False

    def build_source(self, chat_id, **kwargs):
        # 模拟 bundled adapter：把入参透传为 source 对象
        return Source(chat_id=chat_id, **kwargs)

    async def _api_get(self, path):
        # 模拟多用户频道 members 反查：admin 排第一（管理员/频道创建者）
        if path == "channels/multi/members":
            return [
                {"user_id": "admin1"},
                {"user_id": "user1"},
                {"user_id": "user2"},
                {"user_id": "bot123"},
            ]
        return []

    async def _api_post(self, path, payload):
        return {"id": "post1"}


bundled_mm.MattermostAdapter = MattermostAdapter
bundled_mm.MAX_POST_LENGTH = 4000
bundled_mm._apply_yaml_config = lambda *a, **k: None
bundled_mm._is_connected = lambda *a, **k: True
bundled_mm._standalone_send = AsyncMock(return_value={})
bundled_mm.interactive_setup = lambda *a, **k: None
bundled_mm.validate_mattermost_config = lambda *a, **k: (True, "")

hermes_plugins = types_mod.ModuleType("hermes_plugins")
hermes_plugins.__path__ = []
sys.modules["hermes_plugins"] = hermes_plugins
sys.modules["hermes_plugins.platforms_mattermost"] = types_mod.ModuleType(
    "hermes_plugins.platforms_mattermost"
)
sys.modules["hermes_plugins.platforms_mattermost.adapter"] = bundled_mm
sys.modules["gateway"] = gateway_mod
sys.modules["gateway.platforms"] = platforms_mod
sys.modules["gateway.platforms.base"] = base_mod

# tools.approval — 真实模块（纯内存逻辑）
tools_pkg = types_mod.ModuleType("tools")
tools_pkg.__path__ = []
sys.modules["tools"] = tools_pkg

import importlib.util

approval_src = Path("/Users/Colin/.hermes/hermes-agent/tools/approval.py")


def _load_real(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load_real("tools.approval", approval_src)

# adapter 顶部 `from tools.approval import resolve_gateway_approval`
import tools.approval  # noqa: E402, F401

# 加载插件 adapter
pkg_name = "mm_sender_test_pkg"
pkg = types_mod.ModuleType(pkg_name)
pkg.__path__ = [str(PLUGIN_DIR)]
sys.modules[pkg_name] = pkg


def _load_pkg_mod(mod_name, filename):
    spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.{mod_name}", PLUGIN_DIR / filename
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg_name}.{mod_name}"] = mod
    spec.loader.exec_module(mod)
    return mod


_load_pkg_mod("cards", "cards.py")
_load_pkg_mod("models", "models.py")
adapter_mod = _load_pkg_mod("adapter", "adapter.py")
MattermostApprovalAdapter = adapter_mod.MattermostApprovalAdapter


PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


async def main():
    cfg = MagicMock()
    cfg.extra = {}
    ad = MattermostApprovalAdapter(cfg)
    # 阻断真实网络：直接给 send( ) 打桩，避免审批后回执发消息
    ad.send = AsyncMock(return_value=SendResult(success=True, message_id="x"))

    print("── 1. build_source 记录 sender（channel 维度）──")
    # 管理员 admin 先发言（会被 members 反查误认为是发起者）
    ad.build_source(chat_id="multi", user_id="admin1", thread_id=None)
    # 普通用户 user1 随后发言（真正的发起者）
    ad.build_source(chat_id="multi", user_id="user1", thread_id="t1")
    check("channel 维度记录最近 sender = user1", ad._last_sender_by_channel["multi"] == "user1")
    check(
        "thread 维度记录 sender = user1",
        ad._last_sender_by_thread[("multi", "t1")] == "user1",
    )

    print("\n── 2. _resolve_approval_requester 精确定位 ──")
    # thread 精确匹配优先
    uid = ad._resolve_approval_requester("multi", {"thread_id": "t1"})
    check("thread 匹配返回 user1（而非 admin）", uid == "user1", f"got {uid}")
    # 无 thread 时回退 channel 维度
    uid2 = ad._resolve_approval_requester("multi", {})
    check("channel 回退返回 user1（而非 admin）", uid2 == "user1", f"got {uid2}")

    print("\n── 3. send_exec_approval 多用户频道不再误发管理员 ──")
    # 记录 admin 是频道里"第一个"非 bot 成员（members 反查的坑）
    # 但发起者是 user1。构造：admin 的 DM channel 也被记录过（模拟历史 DM）
    captured_dm = {}

    async def _fake_get_or_create_dm(user_id):
        captured_dm["user_id"] = user_id
        return f"dm_{user_id}"

    ad._get_or_create_dm = _fake_get_or_create_dm

    result = await ad.send_exec_approval(
        chat_id="multi",
        command="rm -rf /tmp/x",
        session_key="agent:main:mattermost:channel:multi",
        description="dangerous",
        metadata={"thread_id": "t1"},
        user_id=None,  # 模拟 gateway 未传 user_id
    )
    check("审批发送成功", result.success, f"got {result}")
    check(
        "DM 发给真正的发起者 user1（而非 admin1）",
        captured_dm.get("user_id") == "user1",
        f"got {captured_dm.get('user_id')}",
    )

    print("\n── 4. DM 场景仍正确（无 thread、单用户）──")
    ad.build_source(chat_id="dm1", user_id="alice", thread_id=None)
    captured_dm.clear()
    await ad.send_exec_approval(
        chat_id="dm1",
        command="ls",
        session_key="agent:main:mattermost:dm:dm1",
        description="x",
        metadata=None,
        user_id=None,
    )
    check("DM 场景发给 alice", captured_dm.get("user_id") == "alice", f"got {captured_dm.get('user_id')}")

    # 清理真实 approval 状态残留，避免影响其它测试
    try:
        from tools.approval import _gateway_queues
        _gateway_queues.clear()
    except Exception:
        pass

    return FAIL


if __name__ == "__main__":
    rc = asyncio.run(main())
    print(f"\n{'❌' if rc else '✅'} 结果: {PASS} passed, {rc} failed")
    sys.exit(1 if rc else 0)