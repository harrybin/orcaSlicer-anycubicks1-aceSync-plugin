import json
import runpy
import threading
import unittest
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
        fake.ExecutionResult = Mock()
        with patch.dict("sys.modules", {"orca": fake}):
            plugin = runpy.run_path(sync.__file__)
        self.capability = plugin["AceSyncScript"]()
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
        for raw in ('[]', '{"orca_slot":true}', '{"ace_slot":0}', '{"ace_slot":5}',
                    '{"preview_only":1}', '{"open_on_startup":"true"}', '{"typo":1}'):
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
                with patch.object(sync, "run_sync") as preset_sync:
                    sync.panel_action(host, lambda: '{"preview_only":true}', "import-spools", post)
                    self.assertIn("2 missing spools", post.call_args.args[0]["spoolman"])
                    self.assertFalse(writes)
                    host.ui.message.assert_not_called()
                    host.ui.message.return_value = "no"
                    sync.panel_action(host, lambda: "{}", "import-spools", post)
                    self.assertIn("Import declined", post.call_args.args[0]["spoolman"])
                    self.assertFalse(writes)
                    host.ui.message.reset_mock()
                    host.ui.message.return_value = "yes"
                    sync.panel_action(host, lambda: "{}", "import-spools", post)
                    self.assertEqual(post.call_args.args[0]["spoolman"], "Created 2 Spoolman spool records.")
                    self.assertEqual(post.call_args.args[0]["status"], "Slots refreshed.")
                    sync.panel_action(host, lambda: "{}", "import-spools", post)
                    self.assertIn("already tracked", post.call_args.args[0]["spoolman"])
                    host.ui.message.assert_called_once()
                    preset_sync.assert_not_called()
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
        self.preset = SimpleNamespace(
            name="ACE 1 PLA", is_user=lambda: True, is_external=False, is_project_embedded=False,
            is_from_bundle=lambda: False, is_compatible=True,
            config_value={"filament_type": "PLA", sync.COLOR_KEY: "#FFFFFF"}.get,
        )
        self.bundle = self.host.preset_bundle.return_value
        self.bundle.current_filament_presets.return_value = [self.preset]
        self.bundle.filaments.edited_preset.return_value.is_dirty = False
        self.host.ui.message.return_value = "yes"
        self.editor = self.host.preset.filament
        self.edit = SimpleNamespace(target_name=self.preset.name, set=Mock(), commit=Mock())
        self.editor.begin_update.return_value = self.edit
        self.slots = sync.parse_slots(payload(spool()))
        self.config = sync.config_from("{}")
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

    def test_legacy_url_is_discarded_without_losing_slot_settings(self):
        settings = sync.config_from('{"printer_url":"http://192.168.1.99","ace_slot":3,"preview_only":false}')
        self.assertEqual(settings, sync.DEFAULT_CONFIG | {"ace_slot": 3, "preview_only": False})

    def test_preview_reports_project_color_mismatch_without_edits(self):
        self.bundle.full_config_value.return_value = "#123456"
        settings = sync.config_from('{"preview_only":true}')
        sync.run_sync(self.host, settings, self.slots)
        self.bundle.full_config_value.assert_called_once_with("filament_colour")
        self.bundle.current_filament_presets.assert_not_called()
        self.editor.begin_update.assert_not_called()
        report = self.host.ui.message.call_args.args[0]
        self.assertIn("ACE 1: PLA+ #009CBD", report)
        self.assertIn("Project slot 1 is #123456; ACE slot 1 is #009CBD", report)

    def test_unconfigured_run_updates_only_default_color_after_confirmation(self):
        sync.run_sync(self.host, self.config, self.slots)
        self.editor.begin_update.assert_called_once_with(1)
        self.edit.set.assert_called_once_with(sync.COLOR_KEY, "#009CBD")
        self.edit.commit.assert_called_once_with()

    def test_panel_refresh_shows_black_empty_and_unreported_slots_without_editing(self):
        self.bundle.current_printer_preset.return_value.config_value.return_value = "192.168.1.50"
        post, config = Mock(), Mock()
        with patch.object(sync, "read_moonraker", return_value=payload(
            spool(color=[0, 0, 0]), spool(1, status="empty"),
        )) as read:
            sync.panel_action(self.host, config, "refresh", post)
        read.assert_called_once_with("http://192.168.1.50")
        self.assertEqual([(row["number"], row["label"], row["color"])
                          for row in post.call_args.args[0]["rows"]],
                         [(1, "PLA+", "#000000"), (2, "Empty", None),
                          (3, "Not reported", None), (4, "Not reported", None)])
        config.assert_not_called()
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

    def test_preset_sync_rejects_a_printer_switch_during_confirmation(self):
        printer = self.bundle.current_printer_preset.return_value
        printer.config_value.return_value = "192.168.1.51"
        with self.assertRaisesRegex(sync.SyncError, "selected printer changed"):
            sync.run_sync(self.host, self.config, self.slots, printer_url="http://192.168.1.50")
        self.spoolman_online.assert_not_called()
        self.editor.begin_update.assert_not_called()

    def test_panel_refresh_error_clears_previous_swatches(self):
        self.bundle.current_printer_preset.return_value.config_value.return_value = ""
        post = Mock()
        sync.panel_action(self.host, lambda: "{}", "refresh", post)
        self.assertEqual(post.call_args.args[0]["rows"], [])
        self.assertIn("Printer > Connection", post.call_args.args[0]["status"])
        self.assertFalse(post.call_args.args[0]["busy"])

    def test_no_write_when_declined_or_already_matching(self):
        self.host.ui.message.return_value = "no"
        self.assertIsNone(sync.run_sync(self.host, self.config, self.slots))
        with patch.object(self.preset, "config_value",
                          {"filament_type": ["PLA"], sync.COLOR_KEY: ["#009cbd"]}.get):
            self.assertIn("already matches", sync.run_sync(self.host, self.config, self.slots))
        self.editor.begin_update.assert_not_called()

    def test_rejects_shared_dirty_bundled_and_wrong_material_presets(self):
        cases = [
            (self.bundle, "current_filament_presets", lambda: [self.preset, self.preset], "shared"),
            (self.bundle.filaments.edited_preset.return_value, "is_dirty", True, "Save or discard"),
            (self.preset, "is_from_bundle", lambda: True, "dedicated"),
            (self.preset, "config_value", {"filament_type": ["PETG"]}.get, "matching"),
        ]
        for obj, key, val, message in cases:
            with self.subTest(message=message), patch.object(obj, key, val):
                with self.assertRaisesRegex(sync.SyncError, message):
                    sync.run_sync(self.host, self.config, self.slots)
        self.editor.begin_update.assert_not_called()

    def test_rechecks_target_after_confirmation(self):
        self.host.ui.message.side_effect = lambda *_: setattr(self.preset, "name", "Other") or "yes"
        with self.assertRaisesRegex(sync.SyncError, "changed while previewing"):
            sync.run_sync(self.host, self.config, self.slots)
        self.editor.begin_update.assert_not_called()

    def test_does_not_commit_to_a_different_resolved_preset(self):
        self.edit.target_name = "Different preset"
        with self.assertRaisesRegex(sync.SyncError, "different preset assignment"):
            sync.run_sync(self.host, self.config, self.slots)
        self.edit.set.assert_not_called()
        self.edit.commit.assert_not_called()
