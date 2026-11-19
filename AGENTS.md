# Contributor instructions

- Keep `ace_filament_sync.py` self-contained, dependency-free and compatible with OrcaSlicer's embedded Python 3.12. It is the distributable plugin.
- Keep ACE and Moonraker printer operations read-only. Only the explicit, confirmed Spoolman action may write inventory, via Moonraker's Spoolman proxy. Never change printer firmware settings, run G-code, or put private printer details in fixtures or logs.
- Use Orca's public API to read the selected printer connection. Do not edit presets or project settings.
- Read the [protocol notes](docs/protocol.md) and use the repository's [protocol and smoke-test skill](.github/skills/ace-orca-integration/SKILL.md) when changing either integration.
- Run `python -m unittest discover -s tests -v`. Before tagging, follow the [release checklist](docs/release.md).
