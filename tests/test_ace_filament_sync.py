import json
import runpy
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import ace_filament_sync as sync


def payload(*slots):
    return {"result": {"status": {"filament_hub": {
        "ext_spool": 0, "filament_hubs": [{"status": "ready", "slots": list(slots)}],
    }}}}


def spool(index=0, **changes):
    return {"index": index, "status": "ready", "type": "PLA+", "color": [0, 156, 189]} | changes


class StartupPanelTests(unittest.TestCase):
    def setUp(self):
        fake = ModuleType("orca")
        fake.script = SimpleNamespace(ScriptPluginCapabilityBase=object)
        fake.host = Mock()
        fake.base = object
        fake.plugin = lambda cls: cls
        fake.register_capability = Mock()
        fake.ExecutionResult = Mock()
        with patch.dict("sys.modules", {"orca": fake}):
            plugin = runpy.run_path(sync.__file__)
        self.capability = plugin["AceSyncScript"]()
        self.register = fake.register_capability
        self.plugin = plugin
        self.capability.get_config = Mock(return_value="{}")
        self.host = fake.host
        self.open_panel = self.host.ui.create_dock_panel
        self.open_panel.return_value.is_open.return_value = True
        self.panel_action = Mock(side_effect=AssertionError("Opening the dock must not start a sync"))
        with_scope = self.capability.on_load.__func__.__globals__
        patcher = patch.dict(with_scope, {"panel_action": self.panel_action})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_startup_only_mounts_the_dock_and_manual_launch_reuses_it(self):
        self.capability.on_load()
        self.open_panel.assert_called_once()
        self.assertEqual(self.open_panel.call_args.kwargs["dock"], "left")
        self.assertIn('id="import-spools" title=', self.open_panel.call_args.args[0])
        self.capability.execute()
        self.open_panel.assert_called_once()
        self.open_panel.return_value.show.assert_called_once()
        self.host.preset_bundle.assert_not_called()
        self.panel_action.assert_not_called()

    def test_existing_settings_without_startup_option_use_new_default(self):
        self.capability.get_config.return_value = '{"ace_slot":2,"preview_only":true}'
        self.capability.on_load()
        self.open_panel.assert_called_once()
        self.panel_action.assert_not_called()

    def test_auto_spoolman_hides_separate_button_without_running_at_startup(self):
        self.capability.get_config.return_value = '{"sync_spoolman_after_ace":true}'
        self.capability.on_load()
        self.assertIn('id="import-spools" hidden', self.open_panel.call_args.args[0])
        self.panel_action.assert_not_called()
        self.host.preset_bundle.assert_not_called()

    def test_explicit_startup_opt_out_keeps_manual_launch(self):
        self.capability.get_config.return_value = '{"open_on_startup":false}'
        self.capability.on_load()
        self.open_panel.assert_not_called()
        self.capability.execute()
        self.open_panel.assert_called_once()
        self.panel_action.assert_not_called()

    def test_removed_sync_message_is_ignored(self):
        self.capability.on_load()
        callback = self.open_panel.call_args.kwargs["on_message"]
        callback("sync")
        self.panel_action.assert_not_called()
        self.open_panel.return_value.post.assert_not_called()

    def test_only_panel_and_spoolman_actions_are_registered(self):
        self.plugin["AceSyncPlugin"]().register_capabilities()
        self.assertEqual(
            [call.args[0]().get_name() for call in self.register.call_args_list],
            ["ACE Filament Sync", "ACE Spoolman Sync"],
        )


class MoonrakerTests(unittest.TestCase):
    def test_orders_by_index_and_keeps_real_black(self):
        slots = sync.parse_slots(payload(spool(2), spool(color=[0, 0, 0])))
        self.assertEqual([(s.number, s.material, s.color) for s in slots],
                         [(1, "PLA+", "#000000"), (3, "PLA+", "#009CBD")])

    def test_unusable_slots_do_not_turn_into_valid_colors(self):
        for item in (spool(status="empty"), spool(color=[True, 0, 0]),
                     spool(color=[256, 2, 3]), spool(colors=[[0, 0, 0], [1, 1, 1]])):
            with self.subTest(item=item):
                self.assertIsNone(sync.parse_slots(payload(item))[0].color)

    def test_rejects_bad_envelopes_and_duplicate_indexes(self):
        for body in ({}, payload(spool(index=True)), payload(spool(), spool()), payload()):
            with self.subTest(body=body), self.assertRaises(sync.SyncError):
                sync.parse_slots(body)

    def test_external_spool_and_multiple_units(self):
        for changes in ({"ext_spool": 1}, {"filament_hubs": None},
                        {"filament_hubs": [{}, {}]}):
            body = payload(spool())
            body["result"]["status"]["filament_hub"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(sync.SyncError):
                sync.parse_slots(body)

    def test_validates_configuration_and_endpoint(self):
        for url in ("http://example.org", "http://8.8.8.8", "http://user@192.168.1.1",
                    "http://192.168.1.1/path", "http://localhost", "http://[::]"):
            with self.subTest(url=url), self.assertRaises(sync.SyncError):
                sync.endpoint(url)
        for raw in ('[]', '{"preview_only":1}', '{"open_on_startup":"true"}',
                    '{"sync_spoolman_after_ace":"true"}', '{"typo":1}'):
            with self.subTest(raw=raw), self.assertRaises(sync.SyncError):
                sync.config_from(raw)
        self.assertEqual(sync.endpoint("http://[::1]:7125/"), ("http", "::1", 7125))

    def test_one_http_get_and_no_redirects(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append((self.command, self.path))
                self.send_response(self.server.code)
                self.send_header("Location", "/different")
                self.end_headers()
                if self.server.code == 200:
                    self.wfile.write(self.server.body)

            def log_message(self, *_):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                server.code = 200
                server.body = json.dumps(payload(spool())).encode()
                self.assertEqual(sync.parse_slots(sync.read_moonraker(url))[0].color, "#009CBD")
                server.body = b"<html>not Moonraker</html>"
                with self.assertRaisesRegex(sync.SyncError, "valid JSON"):
                    sync.read_moonraker(url)
                server.body = b" " * (sync.MAX_RESPONSE + 1)
                with self.assertRaisesRegex(sync.SyncError, "large response"):
                    sync.read_moonraker(url)
                server.code = 302
                with self.assertRaisesRegex(sync.SyncError, "302"):
                    sync.read_moonraker(url)
                self.assertEqual(calls, [("GET", sync.QUERY)] * 4)
            finally:
                server.shutdown()
                worker.join()


class SpoolmanTests(unittest.TestCase):
    def test_disconnect_and_cancel_never_create_inventory(self):
        host = Mock()
        url = "http://127.0.0.1"
        with patch.object(sync, "spoolman_online", return_value=False), \
             patch.object(sync, "read_moonraker") as read:
            self.assertIsNone(sync.sync_spoolman(host, url))
            read.assert_not_called()
        host.ui.message.return_value = "no"
        with patch.object(sync, "spoolman_online", return_value=True), \
             patch.object(sync, "read_moonraker", return_value=payload(spool())), \
             patch.object(sync, "spoolman_records", return_value=[]), \
             patch.object(sync, "spoolman_call") as write:
            self.assertIsNone(sync.sync_spoolman(host, url))
            write.assert_not_called()

    def test_import_creates_two_spools_for_two_slots_and_repeat_creates_nothing(self):
        host = Mock()
        host.ui.message.return_value = "yes"
        inventory = {"filament": [], "spool": []}
        writes = []

        class Handler(BaseHTTPRequestHandler):
            def send_json(self, result):
                data = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == sync.SPOOLMAN_STATUS:
                    self.send_json({"result": {"spoolman_connected": True}})
                elif self.path == sync.QUERY:
                    self.send_json(payload(spool(0, sku="TEST-001"), spool(2, sku="TEST-001")))
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != sync.SPOOLMAN_PROXY or self.headers["Content-Type"] != "application/json":
                    self.send_error(400)
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                path = body["path"]
                if path not in {"/v1/filament", "/v1/spool"}:
                    self.send_error(400)
                    return
                kind = path.removeprefix("/v1/")
                records = inventory[kind]
                if body["request_method"] == "GET" and "offset=0" in body["query"]:
                    self.send_json({"result": records})
                elif body["request_method"] == "POST":
                    row = {"id": len(records) + 1} | body["body"]
                    if kind == "spool":
                        row["filament"] = {"id": row["filament_id"]}
                    records.append(row)
                    writes.append(kind)
                    self.send_json({"result": row})
                else:
                    self.send_error(400)

            def log_message(self, *_):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                host.preset_bundle.return_value.current_printer_preset.return_value.config_value.return_value = url
                post = Mock()
                sync.panel_action(
                    host, lambda: '{"preview_only":true,"sync_spoolman_after_ace":true}', "refresh", post,
                )
                self.assertIn("2 missing spools", post.call_args.args[0]["spoolman"])
                self.assertFalse(writes)
                host.ui.message.assert_not_called()
                host.ui.message.return_value = "no"
                sync.panel_action(host, lambda: "{}", "import-spools", post)
                self.assertIn("Import declined", post.call_args.args[0]["spoolman"])
                self.assertFalse(writes)
                host.ui.message.reset_mock()
                host.ui.message.return_value = "yes"
                sync.panel_action(host, lambda: '{"sync_spoolman_after_ace":true}', "refresh", post)
                self.assertEqual(post.call_args.args[0]["spoolman"], "Created 2 Spoolman spool records.")
                self.assertEqual(post.call_args.args[0]["status"], post.call_args_list[-2].args[0]["status"])
                sync.panel_action(host, lambda: "{}", "import-spools", post)
                self.assertIn("already tracked", post.call_args.args[0]["spoolman"])
                host.ui.message.assert_called_once()
                host.preset.filament.begin_update.assert_not_called()
            finally:
                server.shutdown()
                worker.join()
        self.assertEqual(writes, ["filament", "spool", "spool"])
        self.assertEqual(len(inventory["filament"]), 1)
        self.assertEqual(len(inventory["spool"]), 2)
        self.assertEqual([row["filament_id"] for row in inventory["spool"]], [1, 1])
        self.assertEqual(inventory["filament"][0]["article_number"], "TEST-001")
        self.assertNotEqual(*[spool["comment"] for spool in inventory["spool"]])

    def test_untracked_matching_spool_and_unknown_density_are_skipped(self):
        filaments = [{"id": 7, "article_number": "TEST-001", "color_hex": "009CBD", "material": "PLA+"}]
        spools = [{"id": 8, "filament": {"id": 7}, "comment": ""}]
        slots = sync.parse_slots(payload(spool(0, sku="TEST-001"), spool(1, type="PC")))
        plan, notes = sync.slot_inventory("http://127.0.0.1", slots, filaments, spools)
        self.assertFalse(plan)
        self.assertIn("untracked inventory", notes[0])
        self.assertIn("no density estimate", notes[1])

    def test_network_permission_failure_points_to_orca_permissions(self):
        with patch.object(sync.http.client, "HTTPConnection") as connection:
            connection.return_value.request.side_effect = PermissionError
            with self.assertRaisesRegex(sync.SyncError, "Permissions > Network access"):
                sync.read_moonraker("http://192.168.1.50")


class OrcaAdapterTests(unittest.TestCase):
    def setUp(self):
        self.host = Mock()
        self.bundle = self.host.preset_bundle.return_value
        self.editor = self.host.preset.filament
        status = patch.object(sync, "spoolman_online", return_value=False)
        self.spoolman_online = status.start()
        self.addCleanup(status.stop)

    def test_reads_the_current_printer_connection_each_time(self):
        printer = self.bundle.current_printer_preset.return_value
        printer.config_value.side_effect = [" 192.168.1.50:7125 ", "https://192.168.1.51:443/"]
        self.assertEqual(sync.printer_url_from(self.host), "http://192.168.1.50:7125")
        self.assertEqual(sync.printer_url_from(self.host), "https://192.168.1.51:443/")
        self.assertEqual([call.args for call in printer.config_value.call_args_list], [("print_host",)] * 2)

    def test_reports_missing_or_invalid_printer_connection(self):
        printer = self.bundle.current_printer_preset.return_value
        for address in ("", None, "ftp://192.168.1.50", "http://192.168.1.50/path"):
            with self.subTest(address=address), self.assertRaisesRegex(sync.SyncError, "Printer > Connection"):
                printer.config_value.return_value = address
                sync.printer_url_from(self.host)

    def test_legacy_url_and_slot_settings_are_ignored(self):
        settings = sync.config_from(
            '{"printer_url":"http://192.168.1.99","ace_slot":3,"orca_slot":2,"preview_only":true}'
        )
        self.assertEqual(settings, sync.DEFAULT_CONFIG | {"preview_only": True})

    def test_panel_refresh_shows_black_empty_and_unreported_slots_without_editing(self):
        self.bundle.current_printer_preset.return_value.config_value.return_value = "192.168.1.50"
        post, config = Mock(), Mock(return_value="{}")
        with patch.object(sync, "read_moonraker", return_value=payload(
            spool(color=[0, 0, 0]), spool(1, status="empty"),
        )) as read, patch.object(sync, "datetime", **{"now.return_value": datetime(2026, 11, 19, 15, 0, 59)}):
            sync.panel_action(self.host, config, "refresh", post)
        read.assert_called_once_with("http://192.168.1.50")
        self.assertEqual(post.call_args.args[0]["status"], "Slots refreshed at 2026-11-19 15:00:59 (local time).")
        self.assertEqual([(row["number"], row["label"], row["color"])
                          for row in post.call_args.args[0]["rows"]],
                         [(1, "PLA+", "#000000"), (2, "Empty", None),
                          (3, "Not reported", None), (4, "Not reported", None)])
        config.assert_called_once_with()
        self.spoolman_online.assert_not_called()
        self.editor.begin_update.assert_not_called()

    def test_spoolman_failure_does_not_hide_refreshed_slots(self):
        self.bundle.current_printer_preset.return_value.config_value.return_value = "192.168.1.50"
        self.spoolman_online.side_effect = sync.SyncError("Could not reach Moonraker.")
        post = Mock()
        with patch.object(sync, "read_moonraker", return_value=payload(spool())):
            sync.panel_action(self.host, lambda: "{}", "import-spools", post)
        result = post.call_args.args[0]
        self.assertEqual(result["rows"][0]["color"], "#009CBD")
        self.assertEqual(result["spoolman"], "Could not reach Moonraker.")
        self.editor.begin_update.assert_not_called()

    def test_panel_refresh_error_clears_previous_swatches(self):
        self.bundle.current_printer_preset.return_value.config_value.return_value = ""
        post = Mock()
        sync.panel_action(self.host, lambda: '{"sync_spoolman_after_ace":true}', "refresh", post)
        self.assertEqual(post.call_args.args[0]["rows"], [])
        self.assertIn("Printer > Connection", post.call_args.args[0]["status"])
        self.assertNotIn("Slots refreshed", post.call_args.args[0]["status"])
        self.assertFalse(post.call_args.args[0]["busy"])
        self.spoolman_online.assert_not_called()
