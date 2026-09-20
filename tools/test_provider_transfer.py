"""Offline checks for supplier configuration migration helpers."""

import copy
import threading
import types
import unittest
import uuid

from tools import feature_backend


def _cell(value):
    return (lambda: value).__closure__[0]


def _nested(name):
    module = compile(feature_backend.FEATURE_SERVER_SRC, "<features>", "exec")
    make_server = next(
        item for item in module.co_consts
        if isinstance(item, types.CodeType) and item.co_name == "make_server"
    )
    return next(
        item for item in make_server.co_consts
        if isinstance(item, types.CodeType) and item.co_name == name
    )


class ProviderTransferTests(unittest.TestCase):
    def test_export_excludes_builtin_and_keeps_key(self):
        data = {"codex": {"providers": [
            {"id": "original", "name": "官方"},
            {"id": "test-provider", "name": "Test Provider", "base_url": "https://provider.invalid",
             "api_key": "test-only-key", "models": ["test-model"]},
        ]}}
        code = _nested("_provider_export")
        fn = types.FunctionType(code, {"LOCK": threading.RLock(),
                                        "load_data": lambda: data},
                                closure=(_cell("api-switch-provider-config"),
                                         _cell(("name", "base_url", "api_key", "models"))))
        out = fn()
        self.assertEqual(out["format"], "api-switch-provider-config")
        self.assertEqual(len(out["providers"]), 1)
        self.assertEqual(out["providers"][0]["api_key"], "test-only-key")

    def test_import_merges_by_name_and_base_url(self):
        data = {"codex": {"providers": [
            {"id": "original", "name": "官方"},
            {"id": "old-test-provider", "name": "Test Provider", "base_url": "https://provider.invalid",
             "api_key": "old-test-key", "models": ["old-test-model"]},
        ]}}
        saved = []
        code = _nested("_provider_import")
        fn = types.FunctionType(
            code,
            {"LOCK": threading.RLock(), "load_data": lambda: data,
             "ensure_builtin": lambda value: value,
             "sanitize_id": lambda name, pid: pid or name.lower(),
             "save_data": lambda value: saved.append(copy.deepcopy(value)),
             "ValueError": ValueError},
            closure=(_cell(("name", "base_url", "wire_api", "auth_mode", "api_key",
                            "env_key", "reasoning_effort", "models", "model",
                            "review_model", "context_window", "max_output_tokens")),
                     _cell(lambda: None), _cell(uuid)),
        )
        out = fn({"providers": [{"id": "different-test-id", "name": "Test Provider",
                                  "base_url": "https://provider.invalid", "api_key": "new-test-key",
                                  "models": ["test-model", "test-model"]}]})
        self.assertEqual((out["added"], out["updated"], out["skipped"]), (0, 1, 0))
        self.assertEqual(saved[0]["codex"]["providers"][1]["api_key"], "new-test-key")
        self.assertEqual(saved[0]["codex"]["providers"][1]["models"], ["test-model"])


if __name__ == "__main__":
    unittest.main()
