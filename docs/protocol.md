# Integration contracts

## Rinkhals / Moonraker

The read-only request is `GET /printer/objects/query?filament_hub`. The plugin reads `print_host` from the active OrcaSlicer printer preset on each run. As in Orca's own Moonraker client, a bare address uses HTTP; an explicit HTTP(S) scheme and port are preserved. The plugin does not read API keys or use a previously saved plugin URL. No dependency on Home Assistant itself is needed.

The plugin reads `result.status.filament_hub.filament_hubs[0]` when external-spool mode is off and the single ACE unit is `ready`. Each slot has a zero-based `index`, `status`, material `type` and `color` (three integer RGB channels). If `colors` advertises multiple colors the slot is not eligible. The displayed slot number is `index + 1`; returned array order does not determine the slot. RGB `[0, 0, 0]` is a legitimate black for a ready, typed filament, not evidence that an empty slot is loaded. The optional SKU is used only for Spoolman matching; RFID and remaining amount are not used.

The client uses a five-second socket timeout and a bounded response size. It does not use proxies or redirects, scan the LAN, or send credentials. HTTPS uses Python's normal certificate validation. Stock Anycubic MQTT/LAN firmware and multiple ACE units are not supported.

References: [Rinkhals OrcaSlicer guide](https://rinkhals-community.github.io/Rinkhals/guides/orca-slicer-usage/), [Moonraker printer objects API](https://moonraker.readthedocs.io/en/latest/external_api/printer/#query-printer-object-status).

## Spoolman

The panel's **Import spools** and the standalone **ACE Spoolman Sync** actions do not edit presets. Both check `GET /server/spoolman/status` and use Moonraker's `POST /server/spoolman/proxy` to forward only `GET` and confirmed `POST` requests to `/v1/filament` and `/v1/spool`. Panel preview mode permits only reads. Neither action uses the active-spool setter. The plugin checks the printer, slots and inventory again after confirmation; partial writes are not rolled back.

Filament identity uses normalized material, RGB and optional product SKU. A spool marker additionally includes the Moonraker address and ACE slot. Keep these markers in the Spoolman spool comments for repeat imports. This is not a physical-spool identifier.

## OrcaSlicer

The distributable is a single PEP 723 script with no dependencies. The standalone **ACE Preset Color** action uses `orca.host.preset.filament.begin_update(slot_number)`, stages only `default_filament_colour`, and commits through OrcaSlicer's GUI transaction. The target is checked again after confirmation; shared, untrusted or incompatible targets are rejected. Orca leaves the edit unsaved for the user to review and save. The preview compares the mapped slot with `full_config_value("filament_colour")`, but Orca exposes no setter for that project setting and no extension point for a button in the native Filament header.

The contract was checked against the [OrcaSlicer v2.5.0 preset bindings](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/plugin/host/PluginHostPresets.cpp), not inferred from the `anycubic-orca-plugin` implementation. No code from that AGPL-licensed plugin is incorporated.

The **ACE Filament Sync** script opens a bottom dock using `orca.host.ui.create_dock_panel`, so OrcaSlicer can use the requested initial height of 150 device-independent pixels. OrcaSlicer restores any saved pane layout in preference to the default. With `open_on_startup: true`, its `on_load()` hook calls the same panel opener; the host defers mounting the dock until the workspace is shown. Neither opening path starts a network request. The panel sends only `refresh` or `import-spools`; it cannot supply a printer address, color or preset. The callback re-enters the registered script through the native capability trampoline so network access uses Orca's normal per-plugin permissions. Refresh is read-only.
