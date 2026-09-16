"""Static contract regressions for the public Hermes plugin boundary.

These tests intentionally inspect source instead of importing the full Hermes runtime,
so they remain runnable in GitHub Actions without a local Hermes checkout.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _class(tree: ast.AST, name: str) -> ast.ClassDef:
    return next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == name)


def _method(cls: ast.ClassDef, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return next(
        node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def test_platform_registration_keeps_bundled_adapter_contract():
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    register = _function(tree, "register")
    call = next(
        node
        for node in ast.walk(register)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_platform"
    )
    names = {keyword.arg for keyword in call.keywords}
    required = {
        "name",
        "adapter_factory",
        "check_fn",
        "validate_config",
        "is_connected",
        "setup_fn",
        "apply_yaml_config_fn",
        "allowed_users_env",
        "allow_all_env",
        "cron_deliver_env_var",
        "standalone_sender_fn",
        "max_message_length",
        "allow_update_command",
    }
    assert required <= names


def test_dm_approval_cards_are_explicitly_advertised():
    tree = ast.parse((ROOT / "adapter.py").read_text(encoding="utf-8"))
    adapter = _class(tree, "MattermostApprovalAdapter")
    method = _method(adapter, "supports_exec_approval_buttons")
    assert any(
        isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value is True
        for node in ast.walk(method)
    )


def test_model_switch_writes_through_for_gateway_restart_rehydration():
    tree = ast.parse((ROOT / "session_actions.py").read_text(encoding="utf-8"))
    method = _function(tree, "switch_session_model")
    calls = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_model_override"
    ]
    assert calls, "session model selections must persist across Gateway restarts"
