---
name: ace-orca-integration
description: Change or verify the Rinkhals Moonraker ACE protocol and OrcaSlicer filament preset integration.
---

# ACE and Orca integration

1. Check [protocol notes](../../../docs/protocol.md) for the Rinkhals contract and link to the Orca source for the minimum supported version. Do not copy upstream plugin implementations.
2. Verify protocol changes using a read-only Moonraker query and synthetic fixture data. Cover missing ACE, invalid or empty slots, and zero-based indexes before testing on a printer.
3. Use a disposable OrcaSlicer data directory and scratch project for GUI tests. Test preview, declined confirmation, and a confirmed edit to a dedicated compatible user preset. Verify only Default color changes, save it manually, reopen, and check that it persisted.
4. Do not report a GUI smoke as passed based on fake host tests or a successful CLI read. Leave publication blocked if the host smoke has not passed.
