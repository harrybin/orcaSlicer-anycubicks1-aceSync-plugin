# Release checklist

- [x] Initialize the local MIT repository with a self-contained `.py` plugin, contributor guidance and CI.
- [x] Exercise the Moonraker endpoint on a Rinkhals Kobra S1 and check the returned slot order, materials and RGB values.
- [x] Verify OrcaSlicer 2.5.0 on Windows discovers, loads and registers the script capability in an isolated data directory.
- [x] Verify the active printer address and port through the native OrcaSlicer 2.5.0 preset API. Verify the live Moonraker Spoolman status and read-only inventory proxy.
- [x] Verify that the v0.3.0 panel renders color dots and hex codes in light and dark browser tests and that a live read-only Moonraker query produces four valid swatches. These checks do not exercise OrcaSlicer's desktop dock or its permission prompts.
- [ ] Before publishing, verify a confirmed Spoolman import and repeat run on a disposable Spoolman inventory.
- [ ] Before publishing, run the installed plugin against the live printer from the **Anycubic ACE sync** dock to verify the network permission prompt and swatches together.
- [ ] In a disposable profile, restart OrcaSlicer with the plugin active and the default config. Confirm that one dock appears on Prepare without any printer or Spoolman request. Reopen from Speed Dial and confirm it reuses the dock. Set `open_on_startup` to `false` and verify the next launch stays closed.
- [ ] Choose a public GitHub repository and create a release for the same version as the PEP 723 header. Include the MIT license and link to the usage and compatibility docs.
- [ ] Follow the official [Orca Cloud Help Guide](https://cloud.orcaslicer.com/wiki/) to create a plugin listing as a third-party author. Include supported hardware, confirmed OrcaSlicer versions, screenshots, permissions and known limitations. Publish only after review. Listing on Orca Cloud is not OrcaSlicer endorsement or bundling.

## Native Windows smoke test

Use an isolated OrcaSlicer data directory and a scratch Kobra S1 project, not your working profiles. The following Windows command uses a new directory each time:

```powershell
$testData = Join-Path $env:TEMP ("OrcaAceSmoke-" + [guid]::NewGuid())
& 'C:\Program Files\OrcaSlicer\orca-slicer.exe' --datadir $testData
```

1. Install the local `.py` through **Plugins**. Activate it and confirm no dependency installation or Python import error occurs.
2. Save the Moonraker address in the selected printer's **Connection** settings. Open **Anycubic ACE sync** and verify that a fresh layout places it on the left. Hover over both action buttons to check their tooltips. Choose **ACE sync** and check that the four reported materials, dots and hex codes match the printer and that the preset remains unmodified. Close the dock and run **ACE Filament Sync** to reopen it.
3. With disposable Spoolman inventory, verify preview, declined and confirmed imports, and no duplicates on repeat. Decline any import shown for real inventory.
4. Verify disabling the plugin leaves normal printer connections usable.

## Prepare the Orca Cloud upload

The current guide accepts standalone `.py` files and uses an `_any.py` suffix for cross-platform files. Package the exact tested source and record its hash:

```powershell
New-Item -ItemType Directory -Force .\dist | Out-Null
Copy-Item -LiteralPath .\ace_filament_sync.py -Destination .\dist\ace_filament_sync_any.py
Get-FileHash -Algorithm SHA256 .\dist\ace_filament_sync_any.py
```

Report only platforms tested in the native application. CI on Windows and Linux exercises Python logic and does not establish Orca GUI support.
