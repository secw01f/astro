import importlib
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SecurityHelperTests(unittest.TestCase):
    def test_tools_security_requires_explicit_allowlist(self):
        spec = importlib.util.spec_from_file_location(
            "tools_security_for_test",
            ROOT / "tools" / "lib" / "security.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.assertEqual(module.block_reason_for_url("http://127.0.0.1:8000"), "Execution Blocked")
        self.assertEqual(module.block_reason_for_url("http://93.184.216.34"), "Execution Blocked")

        old_allowlist = os.environ.get("OUTBOUND_ALLOWLIST")
        os.environ["OUTBOUND_ALLOWLIST"] = "93.184.216.34/32"
        module._allowlist.cache_clear()
        try:
            self.assertIsNone(module.block_reason_for_url("http://93.184.216.34"))
        finally:
            if old_allowlist is None:
                os.environ.pop("OUTBOUND_ALLOWLIST", None)
            else:
                os.environ["OUTBOUND_ALLOWLIST"] = old_allowlist
            module._allowlist.cache_clear()

    def test_client_config_permissions(self):
        with tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home
            spec = importlib.util.spec_from_file_location(
                "client_config_for_test",
                ROOT / "client" / "lib" / "config.py",
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            module.save_config({"token": "secret", "url": "http://localhost:8000"})
            self.assertEqual(stat.S_IMODE(module.CONFIG_DIR.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(module.CONFIG_FILE.stat().st_mode), 0o600)
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

    def test_api_outbound_policy_requires_allowlist_when_deps_available(self):
        os.environ.update(
            {
                "DB_URL": "postgresql+asyncpg://u:p@db:5432/d",
                "JWT_SECRET_KEY": "j" * 40,
                "CREDENTIAL_ENCRYPTION_KEY": "c" * 40,
                "TOOLS_HMAC_SECRET": "h" * 40,
                "DEFAULT_TOOLS_BASE_URL": "http://tools:7001",
                "DEFAULT_EXP_MINUTES": "30",
                "ENV": "test",
            }
        )
        sys.path.insert(0, str(ROOT / "api"))
        try:
            network = importlib.import_module("lib.security.network")
        except ImportError as exc:
            self.skipTest(f"API dependencies unavailable: {exc}")
        with self.assertRaises(Exception):
            network.validate_outbound_url("http://127.0.0.1:8000")
        with self.assertRaises(Exception):
            network.validate_outbound_url("http://93.184.216.34")

        old_allowlist = network.settings.OUTBOUND_ALLOWLIST
        network.settings.OUTBOUND_ALLOWLIST = "93.184.216.34/32"
        network._allowlist.cache_clear()
        try:
            network.validate_outbound_url("http://93.184.216.34")
        finally:
            network.settings.OUTBOUND_ALLOWLIST = old_allowlist
            network._allowlist.cache_clear()


if __name__ == "__main__":
    unittest.main()
