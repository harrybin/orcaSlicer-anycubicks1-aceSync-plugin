# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.orcaslicer.plugin]
# name = "ACE Filament Sync for Rinkhals"
# description = "Read Kobra S1 ACE slots and import missing Spoolman spools."
# author = "harrybin"
# version = "0.4.14"
# ///

"""Dependency-free, read-only Moonraker client and OrcaSlicer script plugin."""

import hashlib
import http.client
import ipaddress
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit


QUERY = "/printer/objects/query?filament_hub"
SPOOLMAN_STATUS = "/server/spoolman/status"
SPOOLMAN_PROXY = "/server/spoolman/proxy"
MAX_RESPONSE = 128 * 1024
TITLE = "ACE Filament Sync"
SPOOLMAN_TITLE = "ACE Spoolman Sync"
PANEL_TITLE = "Anycubic ACE sync"
DEFAULT_CONFIG = {"preview_only": False, "open_on_startup": True, "sync_spoolman_after_ace": False}
DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07}

PANEL_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; overflow-y: auto; scrollbar-gutter: stable; }
  body { margin: 0; background: Canvas; color: CanvasText;
         font: 13px/1.3 system-ui, sans-serif; }
  main { padding: 8px; }
  main:focus-visible, #spoolman:focus-visible { outline: 2px solid Highlight; outline-offset: -2px; }
  .overview { display: grid; grid-template-columns: minmax(0, 1fr) max-content;
              gap: 8px; align-items: start; }
  ol { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
       gap: 4px 8px; padding: 0; margin: 0; list-style: none; }
  li { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 4px; align-items: start;
       padding: 4px 0; border-bottom: 1px solid color-mix(in srgb, CanvasText 22%, Canvas);
       overflow-wrap: anywhere; }
  .dot { width: 18px; height: 18px; border: 1px solid GrayText;
         border-radius: 50%; box-sizing: border-box; }
  strong { display: block; }
  .hex-line { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; gap: 2px 4px; }
  code { font-size: 12px; user-select: text; }
  .actions { display: grid; gap: 4px; }
  button { font: inherit; min-width: 0; min-height: 28px; padding: 4px; cursor: pointer; }
  .actions button:not([hidden]) { display: flex; align-items: center; justify-content: center;
                    gap: 4px; padding-inline: 6px; white-space: nowrap; }
  .actions svg { flex: none; width: 16px; height: 16px; fill: none; stroke: currentColor;
                 stroke-width: 1.65; stroke-linecap: round; stroke-linejoin: round; }
  #refresh { min-height: 34px; }
  button:disabled { cursor: default; }
  button:focus-visible { outline: 2px solid Highlight; outline-offset: 2px; }
  .copy-hex { display: inline-grid; place-items: center; min-height: 22px; width: 22px;
              padding: 2px; border: 0; border-radius: 3px; background: transparent; color: inherit; }
  .copy-hex:hover { background: ButtonFace; }
  .copy-hex svg { width: 14px; height: 14px; }
  .copy-hex[data-copied] .copy-icon, .copy-hex:not([data-copied]) .check-icon { display: none; }
  #copy-status:not(:empty) { margin-top: 4px; }
  #status, #spoolman { margin: 4px 0 0; overflow-wrap: anywhere; }
  #spoolman { white-space: pre-line; max-height: 4lh; overflow-y: auto; scrollbar-gutter: stable; }
  @media (max-width: 250px) {
    body { font-size: 12px; }
    main { padding: 4px; }
    .overview, ol { column-gap: 4px; }
    li { column-gap: 3px; padding: 3px 0; }
    code { font-size: 11px; }
    .hex-line { column-gap: 2px; }
    .copy-hex { width: 18px; }
  }
</style></head>
<body>
<main tabindex="0" aria-label="ACE slots and sync results">
<div class="overview">
  <ol id="slots" aria-label="ACE filament slots"></ol>
  <div class="actions">
    <button type="button" id="refresh" title="Refresh ACE slot materials and colors without changing anything.">
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8 16H3V5h14v4M6.5 8v3M9 8v2M11.5 8v1M14 8v1M17.5 13.5A3.5 3.5 0 1 0 17 17M17.5 10.5v3h-3"/></svg>
      ACE sync
    </button>
    <button type="button" id="import-spools" title="Check for missing ACE spools and ask before adding them to Spoolman.">
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M13.2 6.5a6.6 6.6 0 1 0-.8 8.5M13 13h6m-3-3v6"/><circle cx="7.5" cy="10" r="2"/></svg>
      Spoolman
    </button>
  </div>
</div>
<div id="copy-status" role="status"></div>
<p id="status" role="status">Refresh to read the selected printer's ACE slots.</p>
<p id="spoolman" role="status" aria-label="Spoolman log" tabindex="0" hidden></p>
</main>
<script>
  const slots = document.querySelector('#slots');
  const copyStatus = document.querySelector('#copy-status');
  const status = document.querySelector('#status');
  const spoolman = document.querySelector('#spoolman');
  const refresh = document.querySelector('#refresh');
  const importSpools = document.querySelector('#import-spools');
  async function copyHex(button, value) {
    const digits = value.textContent.slice(1);
    let copied = false;
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(digits);
        copied = true;
      }
    } catch (error) {
      // Embedded WebViews may reject the Clipboard API despite a user click.
      if (!(error instanceof DOMException)) throw error;
    }
    if (!button.isConnected) return;
    if (!copied) {
      const range = document.createRange();
      range.selectNodeContents(value);
      range.setStart(value.firstChild, 1);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      try {
        copied = document.execCommand('copy');
      } catch (error) {
        if (!(error instanceof DOMException)) throw error;
      }
      if (copied) selection.removeAllRanges();
    }
    if (copied) {
      slots.querySelector('[data-copied]')?.removeAttribute('data-copied');
      button.setAttribute('data-copied', '');
    }
    copyStatus.textContent = copied ? `Copied ${digits}.` :
      'Clipboard unavailable. Press Ctrl+C (Cmd+C on Mac) to copy the selected code.';
  }
  function render(rows) {
    slots.replaceChildren(...rows.map(row => {
      const item = document.createElement('li');
      const dot = document.createElement('span');
      dot.className = 'dot';
      dot.setAttribute('aria-hidden', 'true');
      const color = /^#[0-9A-F]{6}$/.test(row.color) ? row.color : null;
      if (color) dot.style.backgroundColor = color;
      const label = document.createElement('strong');
      label.textContent = `ACE ${row.number} \u00b7 ${row.label}`;
      const value = document.createElement(color ? 'code' : 'span');
      value.textContent = color || row.note;
      const line = document.createElement('div');
      line.className = 'hex-line';
      line.append(value);
      if (color) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'copy-hex';
        button.title = `Copy ACE ${row.number} color ${color.slice(1)}`;
        button.setAttribute('aria-label', button.title);
        button.innerHTML = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
          stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <g class="copy-icon"><rect x="5.5" y="5.5" width="8" height="8" rx="1"/>
          <path d="M3 10V3.5a.5.5 0 0 1 .5-.5H10"/></g>
          <path class="check-icon" d="m3.5 8 3 3 6-6"/></svg>`;
        button.onclick = () => copyHex(button, value);
        line.append(button);
      }
      item.append(dot, label, line);
      return item;
    }));
  }
  function send(action) {
    if (!window.orca) {
      status.textContent = 'Open this panel from OrcaSlicer.';
      return;
    }
    refresh.disabled = importSpools.disabled = true;
    slots.replaceChildren();
    copyStatus.textContent = '';
    status.textContent = 'Reading ACE slots\u2026';
    spoolman.hidden = true;
    spoolman.textContent = '';
    window.orca.postMessage(action);
  }
  refresh.onclick = () => send('refresh');
  importSpools.onclick = () => send('import-spools');
  if (window.orca) window.orca.onMessage(data => {
    render(data.rows);
    status.textContent = data.status;
    spoolman.hidden = !data.spoolman;
    spoolman.textContent = data.spoolman ? `Spoolman: ${data.spoolman}` : '';
    spoolman.scrollTop = 0;
    refresh.disabled = importSpools.disabled = data.busy;
  });
</script></body></html>"""


class SyncError(ValueError):
    """A user-actionable failure."""


def panel_html(sync_spoolman_after_ace):
    if not sync_spoolman_after_ace:
        return PANEL_HTML
    return PANEL_HTML.replace(
        'id="import-spools"', 'id="import-spools" hidden', 1,
    ).replace(
        "Refresh ACE slot materials and colors without changing anything.",
        "Refresh ACE slots, then check for missing Spoolman spools. Adding spools requires confirmation.",
        1,
    )


@dataclass(frozen=True)
class Slot:
    number: int
    status: str
    material: str
    color: str | None
    sku: str = ""


def endpoint(value):
    if not isinstance(value, str) or not value:
        raise SyncError("A Moonraker URL is required.")
    try:
        url = urlsplit(value)
        address = ipaddress.ip_address(url.hostname or "")
        port = url.port
    except ValueError:
        raise SyncError("Use an http:// or https:// URL with a numeric LAN IP and optional port.") from None
    if (
        url.scheme not in {"http", "https"} or url.username is not None
        or url.path not in {"", "/"} or url.query or url.fragment or port == 0
        or not (address.is_private or address.is_loopback)
        or address.is_unspecified or address.is_multicast
        or (address.is_reserved and not address.is_loopback)
        or "%" in str(address)
    ):
        raise SyncError("Use a private LAN Moonraker base URL without credentials, path, query or fragment.")
    return url.scheme, str(address), port


def config_from(raw):
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        raise SyncError("The Config tab must contain a valid JSON object.") from None
    if not isinstance(values, dict):
        raise SyncError("Config must be a JSON object.")
    # Accept settings saved by older versions without using them.
    for key in ("printer_url", "ace_slot", "orca_slot"):
        values.pop(key, None)
    if values.keys() - DEFAULT_CONFIG.keys():
        raise SyncError(f"Config must contain only: {', '.join(DEFAULT_CONFIG)}.")
    config = DEFAULT_CONFIG | values
    for key in DEFAULT_CONFIG:
        if type(config[key]) is not bool:
            raise SyncError(f"{key} must be true or false.")
    return config


class HttpError(SyncError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Moonraker returned HTTP {status}. Check the URL and LAN access.")


def request_json(url, path, body=None):
    scheme, host, port = endpoint(url)
    connection = (http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection)(
        host, port, timeout=5
    )
    try:
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request("GET" if body is None else "POST", path,
                           body=None if body is None else json.dumps(body), headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise HttpError(response.status)
        data = response.read(MAX_RESPONSE + 1)
    except PermissionError:
        raise SyncError(
            f"Orca blocked network access to {host}. In Plugins > Permissions > Network access, "
            f"allow {scheme}://{'[' + host + ']' if ':' in host else host} and the socket host {host}, then run again."
        ) from None
    except (OSError, http.client.HTTPException):
        raise SyncError("Could not reach Moonraker. Check the printer and its Connection address.") from None
    finally:
        connection.close()
    if len(data) > MAX_RESPONSE:
        raise SyncError("Moonraker returned an unexpectedly large response.")
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        raise SyncError("Moonraker did not return valid JSON.") from None


def read_moonraker(url):
    return request_json(url, QUERY)


def parse_slots(payload):
    try:
        hub = payload["result"]["status"]["filament_hub"]
        hubs = hub["filament_hubs"]
    except (KeyError, TypeError):
        raise SyncError("Moonraker did not report filament_hub. Check that Rinkhals Moonraker is running.") from None
    if hub.get("ext_spool") in (1, "1") or hubs is None or hubs == []:
        raise SyncError("No active ACE is reported. Check the ACE and external-spool selection at the printer.")
    if not isinstance(hubs, list) or len(hubs) != 1:
        raise SyncError("This version supports one ACE unit only.")
    unit = hubs[0]
    if not isinstance(unit, dict) or unit.get("status") != "ready":
        raise SyncError("The ACE unit is not ready.")
    if not isinstance(unit.get("slots"), list):
        raise SyncError("The ACE did not report a slot list.")
    slots = {}
    for item in unit["slots"]:
        if not isinstance(item, dict) or type(item.get("index")) is not int or not 0 <= item["index"] < 4:
            raise SyncError("The ACE returned an invalid slot index.")
        number = item["index"] + 1
        if number in slots:
            raise SyncError(f"The ACE reported slot {number} twice.")
        status = item.get("status")
        status = status if status in ("ready", "empty") else "unavailable"
        material = item.get("type")
        material = material.strip() if isinstance(material, str) else ""
        if not material.isascii() or not all(c.isalnum() or c in " +-_" for c in material) or len(material) > 40:
            material = ""
        rgb = item.get("color")
        colors = item.get("colors")
        color = None
        if (
            status == "ready" and isinstance(rgb, list) and len(rgb) == 3
            and all(type(c) is int and 0 <= c <= 255 for c in rgb)
            and (colors is None or (isinstance(colors, list) and len(colors) <= 1))
        ):
            color = "#" + "".join(f"{c:02X}" for c in rgb)
        sku = item.get("sku")
        sku = sku.strip() if isinstance(sku, str) else ""
        if len(sku) > 80 or not all(c.isascii() and (c.isalnum() or c in "-_.") for c in sku):
            sku = ""
        slots[number] = Slot(number, status, material, color, sku)
    if not slots:
        raise SyncError("The ACE did not report any slots.")
    return [slots[n] for n in sorted(slots)]


def material_family(material):
    value = material.strip().upper()
    return "PLA" if value == "PLA+" else value


def spoolman_online(url):
    try:
        result = request_json(url, SPOOLMAN_STATUS)
    except HttpError as error:
        if error.status == 404:
            return False
        raise
    status = result.get("result") if isinstance(result, dict) else None
    if not isinstance(status, dict) or type(status.get("spoolman_connected")) is not bool:
        raise SyncError("Moonraker returned an invalid Spoolman status.")
    return status["spoolman_connected"]


def spoolman_call(url, collection, *, query=None, body=None):
    args = {"request_method": "GET" if body is None else "POST", "path": "/v1/" + collection}
    if query:
        args["query"] = query
    if body is not None:
        args["body"] = body
    response = request_json(url, SPOOLMAN_PROXY, args)
    if not isinstance(response, dict) or "result" not in response:
        raise SyncError("Moonraker returned an invalid Spoolman proxy response.")
    return response["result"]


def spoolman_records(url, collection):
    records = []
    for offset in range(0, 10000, 50):
        page = spoolman_call(url, collection, query=f"sort=id:asc&limit=50&offset={offset}")
        if not isinstance(page, list) or any(not isinstance(row, dict) for row in page) or len(page) > 50:
            raise SyncError("Spoolman returned an invalid inventory page.")
        records.extend(page)
        if len(page) < 50:
            return records
    raise SyncError("Spoolman inventory is too large to check safely; nothing was created.")


def marker(*parts):
    return hashlib.sha256(json.dumps(parts).encode("ascii")).hexdigest()[:24]


def slot_inventory(url, slots, filaments, spools):
    scheme, host, port = endpoint(url)
    origin = (host, port or (443 if scheme == "https" else 80))
    plan, notes = [], []
    for slot in slots:
        family = material_family(slot.material)
        if not slot.color or family in {"", "UNKNOWN", "NONE"}:
            continue
        material = slot.material.upper()
        color = slot.color[1:]
        profile = "ACE:" + marker(material, color, slot.sku.upper())
        tag = "ACE spool:" + marker(origin, slot.number, profile)
        row = next((s for s in spools if s.get("comment") == tag), None)
        if row is not None:
            notes.append(f"ACE {slot.number}: already tracked as spool #{record_id(row)}.")
            continue
        matches = [f for f in filaments if f.get("external_id") == profile or (
            slot.sku and str(f.get("article_number") or "").upper() == slot.sku.upper()
            and str(f.get("material") or "").upper() == material
            and str(f.get("color_hex") or "").lstrip("#").upper() == color
        )]
        if len(matches) > 1:
            notes.append(f"ACE {slot.number}: multiple matching Spoolman filaments; skipped.")
            continue
        existing = record_id(matches[0]) if matches else None
        if any(s.get("filament", {}).get("id") == existing and not str(s.get("comment") or "").startswith("ACE spool:")
               for s in spools if existing is not None and isinstance(s.get("filament"), dict)):
            notes.append(f"ACE {slot.number}: matching untracked inventory already exists; skipped to avoid a duplicate.")
            continue
        if existing is None and family not in DENSITY:
            notes.append(f"ACE {slot.number}: no existing filament and no density estimate for {material}; skipped.")
            continue
        details = {
            "name": f"ACE {slot.sku or material} {slot.color}", "material": material,
            "diameter": 1.75, "color_hex": color, "external_id": profile,
        }
        if slot.sku:
            details["article_number"] = slot.sku
        if existing is None:
            details["density"] = DENSITY[family]
            details["comment"] = "Created from ACE metadata. Density is a material-family estimate; verify it."
        plan.append((slot, tag, existing, details))
    return plan, notes


def sync_spoolman(host, url, *, slots=None, preview_only=False, show_details=True):
    if slots is not None and printer_url_from(host) != url:
        raise SyncError("The selected printer changed. Refresh the ACE slots and run sync again.")
    if not spoolman_online(url):
        message = "Not connected. Check Moonraker's [spoolman] configuration."
        if show_details:
            host.ui.message(message, SPOOLMAN_TITLE)
            return None
        return message
    if slots is None:
        slots = parse_slots(read_moonraker(url))
    plan, notes = slot_inventory(url, slots, spoolman_records(url, "filament"), spoolman_records(url, "spool"))
    if not plan:
        message = "\n".join(notes) or "No usable single-color ACE slots to import."
        if show_details:
            host.ui.message(message, SPOOLMAN_TITLE)
            return None
        return message
    if preview_only:
        count = len(plan)
        return f"Preview only: {count} missing {'spool' if count == 1 else 'spools'}. Nothing created."
    summary = "\n".join(notes + [f"ACE {s.number}: create one spool for {s.material} {s.color}." for s, *_ in plan])
    if host.ui.message(summary + "\n\nCreate the listed Spoolman records?", SPOOLMAN_TITLE, "yes_no", "question") != "yes":
        return None if show_details else "Import declined. Nothing created."
    if printer_url_from(host) != url or parse_slots(read_moonraker(url)) != slots:
        raise SyncError("The selected printer or its ACE slots changed. Run Spoolman sync again.")
    current_plan, _ = slot_inventory(url, slots, spoolman_records(url, "filament"), spoolman_records(url, "spool"))
    if current_plan != plan:
        raise SyncError("Spoolman inventory changed during confirmation. Run sync again to review the new plan.")
    new_filaments = {}
    created = []
    try:
        for slot, tag, existing, details in plan:
            profile = details["external_id"]
            if existing is None and profile not in new_filaments:
                row = spoolman_call(url, "filament", body=details)
                new_filaments[profile] = record_id(row)
            row = spoolman_call(url, "spool", body={
                "filament_id": existing if existing is not None else new_filaments[profile], "comment": tag,
            })
            created.append(f"ACE {slot.number}: created spool #{record_id(row)}.")
    except SyncError as error:
        prefix = "\n".join(created) + "\n\n" if created else ""
        raise SyncError(prefix + f"Spoolman import stopped: {error}\nCheck inventory before retrying.") from None
    if show_details:
        host.ui.message("\n".join(created), SPOOLMAN_TITLE)
    return f"Created {len(created)} Spoolman spool records."


def record_id(row):
    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0:
        raise SyncError("Spoolman did not confirm the record ID.")
    return row["id"]


def slot_report(slots):
    return "\n".join(
        f"ACE {s.number}: {s.material or 'Unknown'} {s.color or '(' + s.status + '; no usable color)'}"
        for s in slots
    )


def slot_rows(slots):
    by_number = {slot.number: slot for slot in slots}
    rows = []
    for number in range(1, 5):
        slot = by_number.get(number)
        if slot is None:
            label, color, note = "Not reported", None, "No slot data"
        elif slot.status != "ready":
            label, color, note = slot.status.capitalize(), None, "No usable color"
        else:
            label, color, note = slot.material or "Unknown material", slot.color, "No usable color"
        rows.append({"number": number, "label": label, "color": color, "note": note})
    return rows


def preset_text(value):
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    return value if isinstance(value, str) else ""


def printer_url_from(host):
    preset = host.preset_bundle().current_printer_preset()
    address = preset_text(preset.config_value("print_host")).strip()
    if not address:
        raise SyncError("Set and save the Moonraker address in Prepare > Printer > Connection.")
    if "://" not in address:
        address = "http://" + address
    try:
        endpoint(address)
    except SyncError:
        raise SyncError(
            "In Prepare > Printer > Connection, use a numeric LAN IP or Moonraker base URL "
            "with an optional port, but no credentials or URL path."
        ) from None
    return address


def panel_action(host, get_config, action, post):
    if action not in ("refresh", "import-spools"):
        raise SyncError("Unsupported ACE panel action.")
    rows = []
    spoolman = ""
    try:
        config = config_from(get_config())
        url = printer_url_from(host)
        slots = parse_slots(read_moonraker(url))
        rows = slot_rows(slots)
        status = f"Slots refreshed at {datetime.now():%Y-%m-%d %H:%M:%S} (local time)."
        if action == "import-spools" or config["sync_spoolman_after_ace"]:
            post({"rows": rows, "status": status, "spoolman": "Checking inventory.", "busy": True})
            try:
                spoolman = sync_spoolman(
                    host, url, slots=slots, preview_only=config["preview_only"], show_details=False,
                )
            except (ValueError, RuntimeError) as error:
                spoolman = str(error)
    except (ValueError, RuntimeError) as error:
        status = str(error)
    post({"rows": rows, "status": status, "spoolman": spoolman, "busy": False})


try:
    import orca
except ModuleNotFoundError as error:
    if error.name != "orca":
        raise
    orca = None


if orca is not None:
    def execute_action(title, action):
        try:
            message = action(printer_url_from(orca.host))
        except SyncError as error:
            orca.host.ui.message(str(error), title, "ok", "warning")
            return orca.ExecutionResult.skipped(str(error))
        except (ValueError, RuntimeError) as error:
            return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError, str(error))
        if message is None:
            return orca.ExecutionResult.skipped("No changes made.")
        return orca.ExecutionResult.success(message)

    class AceSyncScript(orca.script.ScriptPluginCapabilityBase):
        _panel = None
        _panel_action = None

        def get_name(self):
            return TITLE

        def get_default_config(self):
            return DEFAULT_CONFIG.copy()

        def on_load(self):
            try:
                config = config_from(self.get_config())
            except SyncError as error:
                print(f"{PANEL_TITLE}: skipped opening on startup: {error}", file=sys.stderr)
                return
            if config["open_on_startup"]:
                self._open_panel(config)

        def _on_panel_message(self, action):
            if action not in ("refresh", "import-spools") or self._panel_action is not None:
                return
            self._panel_action = action
            try:
                # The C++ trampoline restores this capability's audit context.
                orca.script.ScriptPluginCapabilityBase.execute(self)
            except RuntimeError as error:
                self._panel.post({"rows": [], "status": str(error), "busy": False})
            finally:
                self._panel_action = None

        def _open_panel(self, config):
            if self._panel is None or not self._panel.is_open():
                self._panel = orca.host.ui.create_dock_panel(
                    panel_html(config["sync_spoolman_after_ace"]), PANEL_TITLE, width=320, height=150,
                    on_message=self._on_panel_message, dock="left",
                )
            else:
                self._panel.show()

        def execute(self):
            if self._panel_action is not None:
                panel_action(orca.host, self.get_config, self._panel_action, self._panel.post)
                return orca.ExecutionResult.success("ACE panel updated.")
            try:
                config = config_from(self.get_config())
            except SyncError as error:
                orca.host.ui.message(str(error), PANEL_TITLE, "ok", "warning")
                return orca.ExecutionResult.skipped(str(error))
            self._open_panel(config)
            return orca.ExecutionResult.success("ACE Sync panel opened.")

    class AceSpoolmanScript(orca.script.ScriptPluginCapabilityBase):
        def get_name(self):
            return SPOOLMAN_TITLE

        def execute(self):
            return execute_action(SPOOLMAN_TITLE, lambda url: sync_spoolman(orca.host, url))

    @orca.plugin
    class AceSyncPlugin(orca.base):
        def register_capabilities(self):
            orca.register_capability(AceSyncScript)
            orca.register_capability(AceSpoolmanScript)


if __name__ == "__main__" and orca is None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python ace_filament_sync.py http://PRINTER_IP")
    try:
        print(slot_report(parse_slots(read_moonraker(sys.argv[1]))))
    except SyncError as error:
        sys.exit(str(error))
