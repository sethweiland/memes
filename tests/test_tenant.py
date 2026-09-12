"""Tenant config + secrets adapter."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests.bootstrap  # noqa: F401

from src.core.secrets_backend import (
    EnvSecretsBackend,
    get_secrets_backend,
)
from src.core.tenant import (
    SPEND_ONLY_PROJECT_IDS,
    load_tenant,
    load_tenant_from_path,
    normalize_lane,
    normalize_tenant,
    reset_tenant,
)


_ROOT = Path(__file__).resolve().parents[1]
_SETH = _ROOT / "config" / "tenant.yaml"
_EXAMPLE = _ROOT / "config" / "tenant.example.yaml"

SETH_IDS = (
    "memes",
    "sethweiland-com",
    "waiver-wire",
    "x",
    "linkmarketcap",
    "whippoorwill",
    "millgrass",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TenantLoadTests(unittest.TestCase):
    def tearDown(self):
        reset_tenant()

    def test_example_tenant_loads(self):
        tenant = load_tenant_from_path(_EXAMPLE)
        self.assertEqual(tenant.human_name, "Your Name")
        self.assertEqual(tenant.timezone, "America/New_York")
        self.assertEqual(tenant.secrets_backend, "env")
        self.assertTrue(tenant.module_enabled("projects"))
        self.assertTrue(tenant.module_enabled("spend"))
        self.assertFalse(tenant.module_enabled("x"))
        self.assertFalse(tenant.module_enabled("grok_bot"))
        self.assertFalse(tenant.module_enabled("memes"))
        self.assertTrue(tenant.calendar_enabled)
        ids = tenant.project_ids()
        self.assertGreaterEqual(len(ids), 2)
        self.assertLessEqual(len(ids), 3)
        self.assertIn("home-ops", ids)
        for pid in SPEND_ONLY_PROJECT_IDS:
            self.assertNotIn(pid, ids)
        self.assertEqual(tenant.default_usage_project, "home-ops")

    def test_seth_tenant_has_seven_ids_and_no_equinox(self):
        tenant = load_tenant_from_path(_SETH)
        self.assertEqual(tenant.human_name, "Seth")
        self.assertEqual(tenant.timezone, "America/New_York")
        self.assertEqual(tenant.site_domain, "ops.sethweiland.com")
        self.assertTrue(tenant.module_enabled("projects"))
        self.assertTrue(tenant.module_enabled("spend"))
        self.assertTrue(tenant.module_enabled("x"))
        self.assertTrue(tenant.module_enabled("grok_bot"))
        self.assertTrue(tenant.module_enabled("memes"))
        self.assertTrue(tenant.calendar_enabled)
        self.assertEqual(tenant.project_ids(), SETH_IDS)
        self.assertNotIn("equinox", tenant.project_ids())
        self.assertNotIn("equinox-cancel-reply-watch", tenant.project_ids())
        for pid in SPEND_ONLY_PROJECT_IDS:
            self.assertNotIn(pid, tenant.project_ids())
        lanes = {p.id: p.lane for p in tenant.kanban_projects()}
        self.assertEqual(lanes["memes"], "active")
        self.assertEqual(lanes["x"], "active")
        self.assertEqual(lanes["sethweiland-com"], "active")
        for pid in ("waiver-wire", "linkmarketcap", "whippoorwill", "millgrass"):
            self.assertIn(lanes[pid], ("idea", "parked"))
        for project in tenant.kanban_projects():
            self.assertIsNone(project.last_done)
            self.assertIsNone(project.next_steps)

    def test_default_load_path_is_seth_tenant(self):
        reset_tenant()
        tenant = load_tenant(reload=True)
        self.assertEqual(tenant.project_ids(), SETH_IDS)

    def test_tenant_config_env_overrides_path(self):
        reset_tenant()
        with patch.dict(os.environ, {"TENANT_CONFIG": str(_EXAMPLE)}):
            tenant = load_tenant(reload=True)
        self.assertEqual(tenant.human_name, "Your Name")
        self.assertIn("home-ops", tenant.project_ids())

    def test_yaml_files_contain_no_secrets(self):
        forbidden = (
            "sk-",
            "xai-",
            "AKIA",
            "BEGIN PRIVATE",
            "password:",
            "api_key:",
            "api-key:",
            "secret:",
            "arn:aws:secretsmanager",
        )
        for path in (_SETH, _EXAMPLE):
            text = _read(path).lower()
            for needle in forbidden:
                self.assertNotIn(needle.lower(), text, msg=f"{path} has {needle}")
            self.assertNotIn("Bearer ", _read(path))
            self.assertNotIn("ics_url", text)
            self.assertNotIn("calendar_ics", text)
            self.assertNotIn("googleapis.com", text)


class TenantNormalizeTests(unittest.TestCase):
    def test_waiting_on_seth_alias_becomes_waiting_on_you(self):
        self.assertEqual(normalize_lane("waiting_on_seth"), "waiting_on_you")
        self.assertEqual(normalize_lane("waiting_on_you"), "waiting_on_you")
        tenant = normalize_tenant(
            {
                "projects": [
                    {"id": "shared", "name": "Shared", "lane": "active"},
                    {"id": "unallocated", "name": "Unallocated", "lane": "idea"},
                    {"id": "alpha", "name": "Alpha", "lane": "waiting_on_seth"},
                ]
            },
            source_path="memory",
        )
        self.assertEqual(tenant.project_ids(), ("alpha",))
        self.assertEqual(tenant.projects[0].lane, "waiting_on_you")


class SecretsBackendTests(unittest.TestCase):
    def test_env_backend_reads_process_env(self):
        backend = EnvSecretsBackend()
        with patch.dict(os.environ, {"LIFE_OPS_TEST_SECRET": "from-env"}):
            self.assertEqual(backend.get("LIFE_OPS_TEST_SECRET"), "from-env")
        self.assertEqual(backend.get("LIFE_OPS_TEST_SECRET_MISSING", "fallback"), "fallback")

    def test_aws_and_bitwarden_are_documented_not_implemented(self):
        aws = get_secrets_backend("aws")
        bitwarden = get_secrets_backend("bitwarden")
        with self.assertRaises(NotImplementedError):
            aws.get("XAI_API_KEY")
        with self.assertRaises(NotImplementedError):
            bitwarden.get("XAI_API_KEY")

    def test_get_secrets_backend_defaults_to_env(self):
        backend = get_secrets_backend("env")
        self.assertIsInstance(backend, EnvSecretsBackend)


class TenantFileTempTests(unittest.TestCase):
    def test_missing_file_raises(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            missing = Path(tmp.name) / "nope.yaml"
            with self.assertRaises(FileNotFoundError):
                load_tenant_from_path(missing)
        finally:
            tmp.cleanup()
