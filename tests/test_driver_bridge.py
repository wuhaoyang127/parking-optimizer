"""Cloud configuration and authenticated request construction, without external calls."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from driver_bridge.settings import setting
from driver_bridge.client import call


class CloudBridgeTests(unittest.TestCase):
    def test_environment_nested_and_root_secrets_precedence(self):
        key = "PARKING_DRIVER_API_URL"
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(setting(key, secrets_store={"driver_bridge": {key: "https://nested"}}),
                             "https://nested")
            self.assertEqual(setting(key, secrets_store={key: "https://root"}), "https://root")
            os.environ[key] = "https://environment"
            self.assertEqual(setting(key, secrets_store={key: "https://root"}), "https://environment")

    def test_missing_cloud_setting_uses_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(setting("MISSING", "default", secrets_store={}), "default")

    def test_remote_plain_http_and_credentials_in_url_are_rejected(self):
        for url in ("http://remote.example", "https://user:password@example.com",
                    "https://example.com?token=bad"):
            with patch("driver_bridge.client.setting", return_value=url), self.assertRaises(ValueError):
                call("/api/research/v1/releases", {})

    def test_https_call_uses_server_token_and_json(self):
        values = {"PARKING_DRIVER_API_URL": "https://driver.example",
                  "PARKING_ADMIN_TOKEN": "a" * 40}
        with patch("driver_bridge.client.setting", side_effect=lambda key, default="": values.get(key, default)), \
                patch("driver_bridge.client.urlopen", return_value=io.BytesIO(b'{"active":null}')) as opener:
            self.assertEqual(call("/api/admin/v1/driver-algorithm-activations", {}, admin=True),
                             {"active": None})
            request = opener.call_args.args[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer " + "a" * 40)
            self.assertEqual(json.loads(request.data), {})


if __name__ == "__main__":
    unittest.main()
