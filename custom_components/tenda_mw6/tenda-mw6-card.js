/**
 * Tenda MW6 Devices Card
 *
 * A dependency-free Lovelace card bundled with the Tenda MW6 integration.
 * It discovers clients through stable state attributes instead of entity IDs.
 *
 * Dashboard:
 *   type: custom:tenda-mw6-card
 *   title: Tenda MW6 — urządzenia
 */

const MW6_CARD_VERSION = "1.6.3";
const MW6_PERIODS = ["total", "day", "month"];
const MW6_DIRECTIONS = ["download", "upload"];

function mw6Escape(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function mw6Number(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function mw6Available(state) {
  return Boolean(state && !["unknown", "unavailable", "none"].includes(state.state));
}

function mw6Ipv4Value(ip) {
  const parts = String(ip || "").split(".");
  if (parts.length !== 4 || parts.some(function (part) {
    return !/^\d{1,3}$/.test(part) || Number(part) > 255;
  })) {
    return null;
  }
  return parts.reduce(function (total, part) {
    return total * 256 + Number(part);
  }, 0);
}

function mw6CompareIp(left, right) {
  const a = mw6Ipv4Value(left);
  const b = mw6Ipv4Value(right);
  if (a !== null && b !== null) return a - b;
  if (a !== null) return -1;
  if (b !== null) return 1;
  return String(left || "").localeCompare(String(right || ""), "pl", {
    numeric: true,
    sensitivity: "base",
  });
}

function mw6FormatRate(value) {
  const rate = mw6Number(value);
  if (rate === null) return "—";
  if (rate >= 1024) {
    return (rate / 1024).toLocaleString("pl-PL", {
      maximumFractionDigits: 1,
    }) + " MiB/s";
  }
  return rate.toLocaleString("pl-PL", {
    maximumFractionDigits: rate < 10 ? 1 : 0,
  }) + " KiB/s";
}

function mw6FormatBytes(value, unit) {
  const bytes = mw6Number(value);
  if (bytes === null) return "—";
  const divisor = unit === "GB" ? 1000000000 : 1000000;
  const decimals = unit === "GB" ? 3 : 2;
  return (bytes / divisor).toLocaleString("pl-PL", {
    minimumFractionDigits: bytes === 0 ? 1 : 0,
    maximumFractionDigits: decimals,
  }) + " " + unit;
}

const MW6_STYLES = [
  ":host { display:block; width:100%; min-width:0; max-width:100%; }",
  "ha-card { width:100%; min-width:0; max-width:100%; padding:16px; box-sizing:border-box; overflow:hidden; }",
  ".header { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }",
  ".title { display:flex; align-items:center; gap:8px; font-size:1.1rem; font-weight:600; color:var(--primary-text-color); }",
  ".title ha-icon { color:var(--primary-color); }",
  ".meta { margin-top:3px; font-size:.73rem; color:var(--secondary-text-color); }",
  ".controls { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)) auto; gap:8px; padding:10px; margin-bottom:12px; border:1px solid var(--divider-color); border-radius:12px; background:color-mix(in srgb,var(--card-background-color) 85%,var(--primary-color) 3%); }",
  ".control { display:flex; flex-direction:column; gap:4px; min-width:0; }",
  ".control label { font-size:.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.04em; color:var(--secondary-text-color); }",
  "select,button { font:inherit; color:var(--primary-text-color); background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; }",
  "select { width:100%; height:34px; padding:0 28px 0 9px; cursor:pointer; }",
  ".order { align-self:end; width:36px; height:34px; display:flex; align-items:center; justify-content:center; cursor:pointer; color:var(--primary-color); }",
  ".order ha-icon { --mdc-icon-size:19px; }",
  ".summary { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:10px; font-size:.78rem; color:var(--secondary-text-color); }",
  ".summary span { display:flex; align-items:center; gap:5px; }",
  ".summary b { color:var(--primary-text-color); }",
  ".dot { width:8px; height:8px; border-radius:50%; background:var(--secondary-text-color); }",
  ".dot.on { background:var(--success-color,#4caf50); }",
  ".dot.off { background:var(--error-color,#db4437); }",
  ".table-wrap { width:100%; min-width:0; overflow:hidden; border:1px solid var(--divider-color); border-radius:12px; }",
  "table { width:100%; max-width:100%; border-collapse:collapse; table-layout:auto; }",
  "th { padding:8px 10px; text-align:left; font-size:.69rem; text-transform:uppercase; letter-spacing:.045em; color:var(--secondary-text-color); background:color-mix(in srgb,var(--divider-color) 30%,transparent); }",
  "th.numeric,td.numeric { text-align:right; }",
  "tbody tr { border-top:1px solid var(--divider-color); cursor:pointer; transition:background .12s ease; }",
  "tbody tr:hover { background:color-mix(in srgb,var(--primary-color) 6%,transparent); }",
  "td { padding:10px; vertical-align:middle; font-size:.84rem; }",
  ".device { display:flex; align-items:center; gap:9px; min-width:160px; }",
  ".device-icon { width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:color-mix(in srgb,var(--primary-color) 13%,transparent); color:var(--primary-color); }",
  ".device-icon ha-icon { --mdc-icon-size:17px; }",
  ".device-name { font-weight:600; color:var(--primary-text-color); max-width:190px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }",
  ".device-status { display:flex; align-items:center; gap:5px; margin-top:2px; font-size:.7rem; color:var(--secondary-text-color); }",
  ".ip { font-family:var(--code-font-family,monospace); color:var(--secondary-text-color); white-space:nowrap; }",
  ".rate { font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap; }",
  ".rate.download { color:var(--info-color,#2196f3); }",
  ".rate.upload { color:var(--success-color,#4caf50); }",
  ".transfer { margin-top:3px; color:var(--secondary-text-color); font-size:.72rem; font-variant-numeric:tabular-nums; white-space:nowrap; }",
  ".empty { padding:28px 12px; text-align:center; color:var(--secondary-text-color); }",
  ".empty ha-icon { display:block; margin:0 auto 8px; --mdc-icon-size:38px; color:var(--primary-color); opacity:.45; }",
  ".hint { margin-top:10px; font-size:.72rem; color:var(--secondary-text-color); }",
  "ha-card.compact { padding:12px; }",
  "ha-card.compact .header { margin-bottom:10px; }",
  "ha-card.compact .controls { grid-template-columns:1fr 1fr; }",
  "ha-card.compact .order { align-self:end; }",
  "ha-card.compact .table-wrap { border:0; overflow:hidden; }",
  "ha-card.compact table,ha-card.compact tbody { display:block; min-width:0; }",
  "ha-card.compact thead { display:none; }",
  "ha-card.compact tbody { display:grid; gap:8px; }",
  "ha-card.compact tbody tr { display:grid; min-width:0; grid-template-columns:repeat(3,minmax(0,1fr)); border:1px solid var(--divider-color); border-radius:11px; overflow:hidden; }",
  "ha-card.compact td { display:block; padding:9px; }",
  "ha-card.compact td.device-cell { grid-column:1 / 3; }",
  "ha-card.compact td.ip-cell { grid-column:3; min-width:0; text-align:right; align-self:center; overflow-wrap:anywhere; white-space:normal; }",
  "ha-card.compact td.numeric { text-align:left; border-top:1px solid var(--divider-color); background:color-mix(in srgb,var(--divider-color) 18%,transparent); }",
  "ha-card.compact td.numeric::before { display:block; margin-bottom:3px; color:var(--secondary-text-color); font-size:.65rem; text-transform:uppercase; }",
  "ha-card.compact td.download-cell::before { content:'Download'; }",
  "ha-card.compact td.upload-cell::before { content:'Upload'; }",
  "ha-card.compact td.signal-cell::before { content:'Sygnał'; }",
  "ha-card.compact .device-name { max-width:180px; }",
].join("\n");

class TendaMW6Card extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._signature = "";
    this._settings = null;
    this._compact = false;
    this._resizeObserver = null;
  }

  connectedCallback() {
    if (!window.ResizeObserver || this._resizeObserver) return;
    this._resizeObserver = new ResizeObserver(function (entries) {
      const width = entries[0] && entries[0].contentRect
        ? entries[0].contentRect.width
        : 0;
      const compact = width > 0 && width < 720;
      if (compact === this._compact) return;
      this._compact = compact;
      this._render();
    }.bind(this));
    this._resizeObserver.observe(this);
  }

  disconnectedCallback() {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
  }

  static getStubConfig() {
    return { title: "Tenda MW6 — urządzenia" };
  }

  setConfig(config) {
    this._config = Object.assign({}, config || {});
    this._settings = this._loadSettings();
    this._signature = "";
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const signature = this._relevantSignature();
    if (signature === this._signature) return;
    this._signature = signature;
    this._render();
  }

  getCardSize() {
    const rows = this._devices().length;
    return Math.max(3, Math.ceil(rows * 0.7) + 2);
  }

  // Home Assistant Sections view has a 12-column grid. Explicitly claim the
  // full section width instead of accepting the editor's small-card default.
  getGridOptions() {
    return {
      columns: "full",
      min_columns: 12,
    };
  }

  _storageKey() {
    const configured = this._config.storage_key || this._config.title || "default";
    return "tenda-mw6-card:" + configured;
  }

  _loadSettings() {
    const defaults = {
      sort: this._config.sort || "device",
      order: this._config.order || "auto",
      period: this._config.period || "total",
      unit: this._config.unit || "MB",
    };
    try {
      return Object.assign(defaults, JSON.parse(localStorage.getItem(this._storageKey())) || {});
    } catch (_) {
      return defaults;
    }
  }

  _saveSettings() {
    try {
      localStorage.setItem(this._storageKey(), JSON.stringify(this._settings));
    } catch (_) {
      // Local storage may be disabled; the card remains fully functional.
    }
  }

  _relevantStates() {
    if (!this._hass) return [];
    const entryId = this._config.entry_id;
    return Object.values(this._hass.states).filter(function (state) {
      const attrs = state.attributes || {};
      return attrs.tenda_mw6_client === true &&
        (!entryId || attrs.config_entry_id === entryId);
    });
  }

  _relevantSignature() {
    return this._relevantStates().map(function (state) {
      const attrs = state.attributes || {};
      return [
        state.entity_id,
        state.state,
        attrs.client_name,
        attrs.client_ip,
        attrs.total_bytes,
        attrs.tenda_mw6_metric,
        attrs.period,
        attrs.direction,
      ].join("|");
    }).sort().join(";");
  }

  _blankDevice(attrs) {
    return {
      key: String(attrs.config_entry_id || "") + ":" + String(attrs.client_mac || ""),
      entryId: attrs.config_entry_id || "",
      mac: attrs.client_mac || "",
      name: attrs.client_name || attrs.client_ip || "Nieznane urządzenie",
      ip: attrs.client_ip || "",
      online: null,
      signal: null,
      entityId: null,
      rates: { download: null, upload: null },
      transfers: {
        total: { download: null, upload: null },
        day: { download: null, upload: null },
        month: { download: null, upload: null },
      },
    };
  }

  _devices() {
    const devices = new Map();
    this._relevantStates().forEach(function (state) {
      const attrs = state.attributes || {};
      const key = String(attrs.config_entry_id || "") + ":" + String(attrs.client_mac || "");
      if (!attrs.client_mac) return;
      if (!devices.has(key)) devices.set(key, this._blankDevice(attrs));
      const device = devices.get(key);

      device.name = attrs.client_name || device.name;
      device.ip = attrs.client_ip || device.ip;
      device.entityId = device.entityId || state.entity_id;

      if (attrs.tenda_mw6_metric === "online") {
        device.entityId = state.entity_id;
        device.online = mw6Available(state)
          ? state.state === "on"
          : null;
      } else if (attrs.tenda_mw6_metric === "signal") {
        device.signal = mw6Available(state) ? mw6Number(state.state) : null;
      } else if (
        attrs.tenda_mw6_metric === "rate" &&
        MW6_DIRECTIONS.includes(attrs.direction)
      ) {
        device.rates[attrs.direction] = mw6Available(state)
          ? mw6Number(state.state)
          : null;
      } else if (
        attrs.tenda_mw6_metric === "transfer" &&
        MW6_PERIODS.includes(attrs.period) &&
        MW6_DIRECTIONS.includes(attrs.direction)
      ) {
        const bytes = mw6Number(attrs.total_bytes);
        device.transfers[attrs.period][attrs.direction] =
          mw6Available(state) && bytes !== null ? bytes : null;
      }
    }, this);
    return Array.from(devices.values());
  }

  _effectiveOrder(sort) {
    if (this._settings.order === "asc" || this._settings.order === "desc") {
      return this._settings.order;
    }
    return sort === "download" || sort === "upload" ? "desc" : "asc";
  }

  _sortedDevices() {
    const devices = this._devices();
    const sort = this._settings.sort;
    const period = this._settings.period;
    const order = this._effectiveOrder(sort);
    const direction = order === "desc" ? -1 : 1;

    devices.sort(function (left, right) {
      let result = 0;
      if (sort === "ip") {
        result = mw6CompareIp(left.ip, right.ip);
      } else if (sort === "download" || sort === "upload") {
        const a = left.transfers[period][sort];
        const b = right.transfers[period][sort];
        if (a === null && b !== null) return 1;
        if (a !== null && b === null) return -1;
        result = (a || 0) - (b || 0);
      } else {
        result = left.name.localeCompare(right.name, "pl", {
          numeric: true,
          sensitivity: "base",
        });
      }
      if (result === 0) {
        result = left.name.localeCompare(right.name, "pl", {
          numeric: true,
          sensitivity: "base",
        });
      }
      return result * direction;
    });
    return devices;
  }

  _option(value, label, selected) {
    return '<option value="' + value + '"' +
      (value === selected ? " selected" : "") + ">" +
      mw6Escape(label) + "</option>";
  }

  _controlsHtml() {
    return [
      '<div class="controls">',
      '  <div class="control"><label for="mw6-sort">Sortowanie</label>',
      '    <select id="mw6-sort">',
      this._option("device", "Urządzenie", this._settings.sort),
      this._option("ip", "IP", this._settings.sort),
      this._option("download", "Download", this._settings.sort),
      this._option("upload", "Upload", this._settings.sort),
      "    </select></div>",
      '  <div class="control"><label for="mw6-period">Transfer</label>',
      '    <select id="mw6-period">',
      this._option("total", "Całkowity", this._settings.period),
      this._option("day", "Dzisiaj", this._settings.period),
      this._option("month", "Ten miesiąc", this._settings.period),
      "    </select></div>",
      '  <div class="control"><label for="mw6-unit">Jednostka</label>',
      '    <select id="mw6-unit">',
      this._option("MB", "MB", this._settings.unit),
      this._option("GB", "GB", this._settings.unit),
      "    </select></div>",
      '  <button class="order" type="button" title="Odwróć kolejność" aria-label="Odwróć kolejność">',
      '    <ha-icon icon="' + (this._effectiveOrder(this._settings.sort) === "desc"
        ? "mdi:sort-descending" : "mdi:sort-ascending") + '"></ha-icon>',
      "  </button>",
      "</div>",
    ].join("");
  }

  _statusHtml(device) {
    if (device.online === true) {
      return '<span class="dot on"></span><span>Online</span>';
    }
    if (device.online === false) {
      return '<span class="dot off"></span><span>Offline</span>';
    }
    return '<span class="dot"></span><span>Stan nieznany</span>';
  }

  _rowHtml(device) {
    const period = this._settings.period;
    const unit = this._settings.unit;
    const download = device.transfers[period].download;
    const upload = device.transfers[period].upload;
    const signal = device.signal === null ? "—" : device.signal + " dBm";
    return [
      '<tr data-entity-id="' + mw6Escape(device.entityId || "") + '">',
      '  <td class="device-cell"><div class="device">',
      '    <div class="device-icon"><ha-icon icon="mdi:laptop"></ha-icon></div>',
      '    <div><div class="device-name" title="' + mw6Escape(device.name) + '">' +
             mw6Escape(device.name) + "</div>",
      '      <div class="device-status">' + this._statusHtml(device) + "</div>",
      "    </div></div></td>",
      '  <td class="ip ip-cell">' + mw6Escape(device.ip || "—") + "</td>",
      '  <td class="numeric download-cell">',
      '    <div class="rate download">' + mw6Escape(mw6FormatRate(device.rates.download)) + "</div>",
      '    <div class="transfer">↓ ' + mw6Escape(mw6FormatBytes(download, unit)) + "</div>",
      "  </td>",
      '  <td class="numeric upload-cell">',
      '    <div class="rate upload">' + mw6Escape(mw6FormatRate(device.rates.upload)) + "</div>",
      '    <div class="transfer">↑ ' + mw6Escape(mw6FormatBytes(upload, unit)) + "</div>",
      "  </td>",
      '  <td class="numeric signal-cell">' + mw6Escape(signal) + "</td>",
      "</tr>",
    ].join("");
  }

  _html() {
    if (!this._hass) {
      return '<div class="empty"><ha-icon icon="mdi:router-wireless"></ha-icon>Ładowanie…</div>';
    }
    const devices = this._sortedDevices();
    const online = devices.filter(function (device) { return device.online === true; }).length;
    const title = this._config.title || "Tenda MW6 — urządzenia";
    const periodLabel = {
      total: "całkowity",
      day: "dzisiaj",
      month: "ten miesiąc",
    }[this._settings.period];

    const body = devices.length
      ? [
          '<div class="summary">',
          '<span><b>' + devices.length + "</b> urządzeń</span>",
          '<span><span class="dot on"></span><b>' + online + "</b> online</span>",
          '<span>↓/↑ transfer: <b>' + periodLabel + "</b></span>",
          "</div>",
          '<div class="table-wrap"><table>',
          "<thead><tr>",
          "<th>Urządzenie</th><th>IP</th>",
          '<th class="numeric">Download</th><th class="numeric">Upload</th>',
          '<th class="numeric">Sygnał</th>',
          "</tr></thead>",
          "<tbody>",
          devices.map(this._rowHtml.bind(this)).join(""),
          "</tbody></table></div>",
        ].join("")
      : [
          '<div class="empty">',
          '<ha-icon icon="mdi:devices"></ha-icon>',
          "Nie znaleziono urządzeń Tenda MW6.",
          '<div class="hint">Po aktualizacji integracji uruchom ponownie Home Assistant.</div>',
          "</div>",
        ].join("");

    return [
      '<div class="header"><div>',
      '  <div class="title"><ha-icon icon="mdi:router-wireless"></ha-icon>' +
         mw6Escape(title) + "</div>",
      '  <div class="meta">Dedykowana karta · v' + MW6_CARD_VERSION + "</div>",
      "</div></div>",
      this._controlsHtml(),
      body,
    ].join("");
  }

  _render() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = '<style>' + MW6_STYLES + '</style><ha-card class="' +
      (this._compact ? "compact" : "") + '">' +
      this._html() + "</ha-card>";
    this._bindEvents();
  }

  _changeSetting(name, value) {
    this._settings[name] = value;
    if (name === "sort") this._settings.order = "auto";
    this._saveSettings();
    this._render();
  }

  _bindEvents() {
    const root = this.shadowRoot;
    if (!root) return;
    const sort = root.getElementById("mw6-sort");
    const period = root.getElementById("mw6-period");
    const unit = root.getElementById("mw6-unit");
    if (sort) sort.addEventListener("change", function (event) {
      this._changeSetting("sort", event.target.value);
    }.bind(this));
    if (period) period.addEventListener("change", function (event) {
      this._changeSetting("period", event.target.value);
    }.bind(this));
    if (unit) unit.addEventListener("change", function (event) {
      this._changeSetting("unit", event.target.value);
    }.bind(this));

    const order = root.querySelector(".order");
    if (order) order.addEventListener("click", function () {
      this._settings.order = this._effectiveOrder(this._settings.sort) === "desc"
        ? "asc" : "desc";
      this._saveSettings();
      this._render();
    }.bind(this));

    root.querySelectorAll("tbody tr").forEach(function (row) {
      row.addEventListener("click", function () {
        const entityId = row.dataset.entityId;
        if (!entityId) return;
        this.dispatchEvent(new CustomEvent("hass-more-info", {
          detail: { entityId: entityId },
          bubbles: true,
          composed: true,
        }));
      }.bind(this));
    }, this);
  }
}

if (!customElements.get("tenda-mw6-card")) {
  customElements.define("tenda-mw6-card", TendaMW6Card);
}

window.customCards = window.customCards || [];
if (!window.customCards.some(function (card) { return card.type === "tenda-mw6-card"; })) {
  window.customCards.push({
    type: "tenda-mw6-card",
    name: "Tenda MW6 Devices Card",
    description: "Lista urządzeń MW6 z transferem, jednostkami i sortowaniem.",
    preview: true,
  });
}
