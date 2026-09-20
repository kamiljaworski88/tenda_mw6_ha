const assert = require("node:assert/strict");
const fs = require("node:fs");

const registry = new Map();
global.HTMLElement = class {};
global.customElements = {
  define(name, klass) { registry.set(name, klass); },
  get(name) { return registry.get(name); },
};
global.window = global;
global.window.customCards = [];

require("../custom_components/tenda_mw6/tenda-mw6-card.js");
const source = fs.readFileSync(
  require.resolve("../custom_components/tenda_mw6/tenda-mw6-card.js"),
  "utf8"
);
assert.match(source, /ResizeObserver/);
assert.match(source, /ha-card\.compact/);
assert.match(source, /getGridOptions\(\)/);
assert.match(source, /columns: "full"/);
assert.doesNotMatch(source, /min-width:690px/);
const Card = registry.get("tenda-mw6-card");
assert.ok(Card);

function metric(id, mac, ip, name, kind, state, extra) {
  return {
    entity_id: id,
    state: String(state),
    attributes: Object.assign({
      tenda_mw6_client: true,
      tenda_mw6_metric: kind,
      config_entry_id: "entry",
      client_mac: mac,
      client_ip: ip,
      client_name: name,
    }, extra || {}),
  };
}

const card = Object.create(Card.prototype);
card._config = {};
card._settings = { sort: "ip", order: "auto", period: "total", unit: "MB" };
card._hass = { states: {
  a_online: metric("binary_sensor.a_online", "02:00:00:00:00:0a", "192.0.2.10", "A", "online", "on"),
  a_rate: metric("sensor.a_download_rate", "02:00:00:00:00:0a", "192.0.2.10", "A", "rate", 8, { direction: "download" }),
  a_total: metric("sensor.a_download_transfer", "02:00:00:00:00:0a", "192.0.2.10", "A", "transfer", 2, { direction: "download", period: "total", total_bytes: 2000000 }),
  b_online: metric("binary_sensor.b_online", "02:00:00:00:00:0b", "192.0.2.2", "B", "online", "off"),
  b_rate: metric("sensor.b_download_rate", "02:00:00:00:00:0b", "192.0.2.2", "B", "rate", 4, { direction: "download" }),
  b_total: metric("sensor.b_download_transfer", "02:00:00:00:00:0b", "192.0.2.2", "B", "transfer", 10, { direction: "download", period: "total", total_bytes: 10000000 }),
} };

assert.deepEqual(card._sortedDevices().map((device) => device.name), ["B", "A"]);
card._settings.sort = "download";
assert.deepEqual(card._sortedDevices().map((device) => device.name), ["B", "A"]);
card._settings.order = "asc";
assert.deepEqual(card._sortedDevices().map((device) => device.name), ["A", "B"]);
card._settings.unit = "GB";
assert.match(card._rowHtml(card._devices()[0]), /GB/);
assert.equal(card._devices().length, 2);

console.log("Tenda MW6 card logic tests passed");
