# Integration contracts

## Rinkhals / Moonraker

The read-only request is `GET /printer/objects/query?filament_hub`. The plugin reads `print_host` from the active OrcaSlicer printer preset on each run. As in Orca's own Moonraker client, a bare address uses HTTP; an explicit HTTP(S) scheme and port are preserved. The plugin does not read API keys or use a previously saved plugin URL. No dependency on Home Assistant itself is needed.

The plugin reads `result.status.filament_hub.filament_hubs[0]` when external-spool mode is off and the single ACE unit is `ready`. Each slot has a zero-based `index`, `status`, material `type` and `color` (three integer RGB channels). If `colors` advertises multiple colors the slot is not eligible. The displayed slot number is `index + 1`; returned array order does not determine the slot. RGB `[0, 0, 0]` is a legitimate black for a ready, typed filament, not evidence that an empty slot is loaded. The optional SKU is used only for Spoolman matching; RFID and remaining amount are not used.

The client uses a five-second socket timeout and a bounded response size. It does not use proxies or redirects, scan the LAN, or send credentials. HTTPS uses Python's normal certificate validation. Stock Anycubic MQTT/LAN firmware and multiple ACE units are not supported.

References: [Rinkhals OrcaSlicer guide](https://rinkhals-community.github.io/Rinkhals/guides/orca-slicer-usage/), [Moonraker printer objects API](https://moonraker.readthedocs.io/en/latest/external_api/printer/#query-printer-object-status).

## Spoolman

The panel's **Spoolman** and the standalone **ACE Spoolman Sync** actions do not edit presets. Both check `GET /server/spoolman/status` and use Moonraker's `POST /server/spoolman/proxy` to forward only `GET` and confirmed `POST` requests to `/v1/filament` and `/v1/spool`. Panel preview mode permits only reads. Neither action uses the active-spool setter. The plugin checks the printer, slots and inventory again after confirmation; partial writes are not rolled back.

Filament identity uses normalized material, RGB and optional product SKU. A spool marker additionally includes the Moonraker address and ACE slot. Keep these markers in the Spoolman spool comments for repeat imports. This is not a physical-spool identifier.

## OrcaSlicer

The distributable is a single PEP 723 script with no dependencies. It reads the active printer's connection from OrcaSlicer and does not modify presets or projects. OrcaSlicer 2.5 does not expose a project color setter or a native Filament header extension point.

The contract was checked against the [OrcaSlicer v2.5.0 preset bindings](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/plugin/host/PluginHostPresets.cpp), not inferred from the `anycubic-orca-plugin` implementation. No code from that AGPL-licensed plugin is incorporated.

The **ACE Filament Sync** script opens a left dock using `orca.host.ui.create_dock_panel`. OrcaSlicer controls the height of side docks and restores saved pane positions in preference to the default. The dock uses its available viewport: the Spoolman log scrolls after four lines, and the page also scrolls if the dock is too short to show the slots and log together. With `open_on_startup: true`, its `on_load()` hook calls the same panel opener; the host defers mounting the dock until the workspace is shown. Neither opening path starts a network request. The panel sends only `refresh` or `import-spools`; it cannot supply a printer address, color or preset. The callback re-enters the registered script through the native capability trampoline so network access uses Orca's normal per-plugin permissions. With `sync_spoolman_after_ace: true`, a successful refresh passes its slot data to the existing Spoolman import flow; the separate panel button is hidden when the dock opens.
