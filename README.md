# ACE Filament Sync for Rinkhals

An independent OrcaSlicer script plugin for the Anycubic Kobra S1 with Rinkhals and one ACE Pro. It reads all four ACE slots directly from Moonraker, displays their material and color, and can sync one selected ACE color to the **Default color** of an existing OrcaSlicer filament preset. It does not depend on Home Assistant, Anycubic Cloud, or any third-party Python packages.

The reported material is used to check the destination preset, not to change its material or print settings. For example, ACE `PLA+` can use a PLA preset, but you should assign a PLA+ profile tuned for that spool. The plugin does not create presets, change existing project color overrides, reassign slots, replace the printer connection, or control the printer. Repeat the sync for each slot you want to update.

## Install and preview

1. Use OrcaSlicer 2.5.0 or later with Python plugin support, and enable Moonraker in Rinkhals. The latest status is in the [release checklist](docs/release.md).
2. In OrcaSlicer, open **Plugins** from the menu button next to **File**. Choose **Install local plugin**, select [ace_filament_sync.py](ace_filament_sync.py), and activate it.
3. In **Prepare**, select your Rinkhals printer. The plugin uses its saved **Printer > Connection** address automatically. Use a numeric LAN IP or a Moonraker URL, including its port if needed, not the Rinkhals management portal. An old `printer_url` in the plugin config is ignored.
4. **ACE Filament Sync → Run** opens **Anycubic ACE sync** at the bottom of the Prepare workspace with an initial height of 150 logical pixels, unless OrcaSlicer restores a saved layout. Click **Refresh slots** to see the four slots in a two-column grid, with their materials, color dots and hex codes. Click the copy icon beside a hex code to copy it, including the `#`. Scroll down for longer sync results. Refresh does not edit anything. Allow the network request if OrcaSlicer asks.

## Open the panel automatically

By default, the **Anycubic ACE sync** dock opens without contacting the printer or Spoolman. To open it manually instead, set `"open_on_startup": false` in **Plugins → ACE Filament Sync → Config**.

## Open the panel with Speed Dial

In **Prepare**, click the 3D workspace and press **Space**. Search for **ACE Filament Sync** and click its bookmark icon to pin it. After that, press **Space** and click the pinned action, or press **Alt** plus the number shown on its tile (for example, **Alt+1**). This opens the panel without opening Plugins or running a sync.

If Space does not open Speed Dial, enable **Open the Speed Dial from the keyboard** in OrcaSlicer's Preferences. Stock OrcaSlicer 2.5 does not let a plugin add a button inside the native Filament header.

## Sync to a filament preset

1. In **Prepare**, assign a compatible, dedicated **user** filament preset to the target project slot. If necessary, save a copy of your tuned preset and assign that copy. Do not assign the same copy to multiple project slots.
2. In **Plugins → ACE Preset Color → Config**, set `ace_slot` and `orca_slot` if needed. Both default to 1. Set `preview_only: true` to preview without edits.
3. Run **ACE Preset Color** from Plugins. Confirm the proposed edit, then save the filament preset to keep its new **Default color**, or discard the edit. The dock no longer edits presets, and this action does not change the open project's numbered color swatch.

## Import ACE spools into Spoolman

Click **Import spools** in the dock or run **ACE Spoolman Sync** separately. Both look for missing spools across all reported ACE slots and ask for confirmation before writing. Neither edits filament presets. **Refresh slots** never contacts Spoolman. Set `preview_only: true` in the dock's **ACE Filament Sync** config to preview imports there. Set up Moonraker's `[spoolman]` connection first; no separate address is needed in Orca.

ACE reports a product SKU when available, not a unique physical spool ID. The plugin tracks records by printer address, ACE slot and filament metadata, so rerunning an unchanged setup does not create duplicates. It cannot recognize an identical replacement spool or follow a spool that moves between slots. It skips untracked inventory matched to the same filament rather than creating a duplicate. The plugin does not assign gates, update weights, or change existing inventory. New PLA/PLA+, PETG, ABS and ASA filament entries use estimated densities; review them in Spoolman.

## Troubleshooting

- **Only a preview appears:** Check `preview_only` in the config for the action you're using: **ACE Filament Sync** for dock imports or **ACE Preset Color** for preset edits. Both still require confirmation before changes.
- **No active ACE:** Check the ACE status at the printer and make sure external-spool mode is not selected.
- **Connection or HTTP error:** Check the selected printer's **Printer > Connection** address and OrcaSlicer's plugin network permissions. The plugin can only read connections exposed on the active printer preset; endpoints requiring credentials are not supported. Do not expose Moonraker to the internet.
- **Network access blocked:** In **Plugins > Permissions > Network access**, allow the printer's HTTP(S) URL and its socket host for this plugin. Then run it again. No separate Spoolman host grant is needed.
- **No usable color:** Empty, unavailable, malformed and multicolor slots are not applied. The plugin does not guess missing colors.
- **The project color still looks different:** Orca's plugin API exposes the project's current colors for reading only. To change one, click its numbered color swatch in **Prepare > Filament**, set the ACE color shown in the preview, and save the project.
- **Uninstall:** Deactivate/remove the plugin from **Plugins**. Previously saved colors are ordinary preset settings; reset the color manually or remove the dedicated copy if you no longer want it.

## Development

```powershell
python -m unittest discover -s tests -v
python .\ace_filament_sync.py http://192.168.1.50
```

The standalone command is a read-only hardware check. See the [protocol notes](docs/protocol.md), [release checklist](docs/release.md), and [MIT license](LICENSE).
