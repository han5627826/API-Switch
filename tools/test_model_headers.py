"""Offline checks for supplier-specific model discovery headers."""

import json
import os
import types
import unittest

from tools import feature_backend


class ModelHeaderTests(unittest.TestCase):
    def request_headers(self, url):
        calls = []

        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return types.SimpleNamespace(
                stdout=b'{"data":[{"id":"example-model"}]}\n__CODE__200')

        code = next(
            item for item in compile(feature_backend.NEW_UPSTREAM_JSON_SRC, "<test>", "exec").co_consts
            if isinstance(item, types.CodeType) and item.co_name == "upstream_json"
        )
        fn = types.FunctionType(code, {
            "os": os,
            "json": json,
            "subprocess": types.SimpleNamespace(run=run),
            "CREATE_NO_WINDOW": 0,
            "get_proxy": lambda: None,
        })
        status, body = fn(url, "test-key", None, None, 15, None)
        self.assertEqual((status, body["data"][0]["id"]), (200, "example-model"))
        self.assertEqual(len(calls), 1)
        cmd, _ = calls[0]
        return [cmd[i + 1] for i, value in enumerate(cmd[:-1]) if value == "-H"]

    def test_agentrouter_gets_required_user_agent(self):
        headers = self.request_headers("https://agentrouter.org/v1/models")
        self.assertIn("Authorization: Bearer test-key", headers)
        self.assertIn("User-Agent: claude-cli/2.0.0 (external, cli)", headers)

    def test_other_suppliers_keep_existing_headers(self):
        for url in ("https://example.org/v1/models",
                    "https://agentrouter.org.evil.example/v1/models"):
            with self.subTest(url=url):
                headers = self.request_headers(url)
                self.assertEqual(headers, ["Authorization: Bearer test-key",
                                           "Content-Type: application/json"])


if __name__ == "__main__":
    unittest.main()
