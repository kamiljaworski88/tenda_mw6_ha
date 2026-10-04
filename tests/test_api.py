from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import unittest


API_PATH = Path(__file__).parents[1] / "custom_components" / "tenda_mw6" / "api.py"
SPEC = importlib.util.spec_from_file_location("tenda_mw6_api_test", API_PATH)
assert SPEC is not None and SPEC.loader is not None
API = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = API
SPEC.loader.exec_module(API)


class InventorySummaryTest(unittest.TestCase):
    def client(self, raw_online: int | None) -> object:
        return API.TendaMW6Client(
            ip="", mac="", name="", node_sn="", signal=None, access=None,
            condition_time=None, raw_online=raw_online, raw_uprate=None,
            raw_downrate=None,
        )

    def test_all_reported_offline_is_explicit(self) -> None:
        summary = API.summarize_inventory([self.client(0), self.client(0)])
        self.assertTrue(summary.all_reported_offline)
        self.assertEqual(summary.total_clients, 2)
        self.assertEqual(summary.reported_offline, 2)
        self.assertEqual(summary.reported_online, 0)

    def test_online_or_unknown_record_prevents_global_offline_flag(self) -> None:
        summary = API.summarize_inventory([self.client(1), self.client(None)])
        self.assertFalse(summary.all_reported_offline)
        self.assertEqual(summary.reported_online, 1)
        self.assertEqual(summary.unknown_online_state, 1)

    def test_decode_preserves_text_access_field(self) -> None:
        host = b"\x1a\x05wired"
        payload = b"\x00\x00\x00\x00\x0a" + bytes([len(host)]) + host

        status, clients = API._decode_mesh_hosts(payload)

        self.assertEqual(status, 0)
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].access, "wired")

    def test_decode_qos_extracts_up_and_down_caps(self) -> None:
        """QOS_GET exposes the up/down bandwidth caps (fields 2 and 3)."""
        # Observed frame: status (4 bytes) then protobuf
        #   08 00            field 1 = 0
        #   10 80 c0 3e      field 2 (up)   = 1,024,000
        #   18 80 c0 3e      field 3 (down) = 1,024,000
        #   20 00            field 4 = 0
        payload = bytes.fromhex("0000000008001080c03e1880c03e2000")
        qos = API._decode_qos(payload)
        self.assertEqual(qos.up_cap, 1_024_000)
        self.assertEqual(qos.down_cap, 1_024_000)

    def test_decode_qos_handles_missing_fields(self) -> None:
        """Without cap fields, values stay None rather than raising."""
        qos = API._decode_qos(b"\x00\x00\x00\x00")
        self.assertIsNone(qos.up_cap)
        self.assertIsNone(qos.down_cap)

    def test_estimate_transfer_uses_kib_per_second(self) -> None:
        self.assertEqual(API.estimate_transfer_bytes(3, 10.5), 32256.0)
        self.assertEqual(API.estimate_transfer_bytes(None, 10), 0.0)
        self.assertEqual(API.estimate_transfer_bytes(-1, 10), 0.0)

    def test_transfer_readiness_requires_online_client_and_nonzero_rate(self) -> None:
        offline = self.client(0)
        offline.raw_uprate = 12
        online_zero = self.client(1)
        online_rate = self.client(1)
        online_rate.raw_downrate = 42

        readiness = API.summarize_transfer_readiness(
            [offline, online_zero, online_rate]
        )

        self.assertEqual(readiness.eligible_clients, 2)
        self.assertEqual(readiness.clients_with_rate, 1)
        self.assertEqual(readiness.clients_with_upload_rate, 0)
        self.assertEqual(readiness.clients_with_download_rate, 1)
        self.assertFalse(readiness.inventory_all_reported_offline)


if __name__ == "__main__":
    unittest.main()
