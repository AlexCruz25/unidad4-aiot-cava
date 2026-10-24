import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createContext, SourceTextModule, SyntheticModule } from "node:vm";
import { createDashboard } from "../dashboard-controller.js";
import { createView } from "../dashboard-view.js";
import {
  READ_PATHS, temperatureStatus, humidityStatus, parseTimestamp,
  freshness, acknowledgement,
} from "../dashboard-state.js";

const EPOCH = 1_792_851_315_451;

function harness(writeControl = async () => {}) {
  let clock = EPOCH;
  let sequence = 0;
  let latest;
  const timers = new Map();
  const subscriptions = new Map();
  const unsubscriptions = [];
  const client = {
    subscribe(path, data, error) {
      subscriptions.set(path, { data, error });
      return () => unsubscriptions.push(path);
    }, writeControl,
  };
  const dashboard = createDashboard(client, (state) => { latest = structuredClone(state); }, {
    localControl: true, now: () => clock,
    setTimer(fn, ms) { const id = ++sequence; timers.set(id, { fn, at: clock + ms }); return id; },
    clearTimer(id) { timers.delete(id); },
  });
  return {
    dashboard, subscriptions, timers, unsubscriptions,
    get state() { return latest; },
    data(key, value) { subscriptions.get(READ_PATHS[key] ?? key).data(value); },
    error(key) { subscriptions.get(READ_PATHS[key] ?? key).error({ code: "PERMISSION_DENIED" }); },
    advance(ms) {
      clock += ms;
      for (const [id, timer] of [...timers]) {
        if (timer.at <= clock && timers.delete(id)) timer.fn();
      }
    },
  };
}

test("temperatura: límites exactos y datos inválidos", () => {
  for (const value of [12, 16, 18]) assert.equal(temperatureStatus(value).tone, "good");
  for (const value of [11.9, 18.1, 22]) assert.equal(temperatureStatus(value).tone, "warning");
  assert.equal(temperatureStatus(22.1).tone, "danger");
  for (const value of [null, "16", NaN, Infinity, false]) assert.equal(temperatureStatus(value).tone, "muted");
});

test("humedad: ideal, crítica estrictamente menor de 60 y datos inválidos", () => {
  for (const value of [65, 70, 80]) assert.equal(humidityStatus(value).tone, "good");
  for (const value of [60, 64.9, 80.1]) assert.equal(humidityStatus(value).tone, "warning");
  assert.equal(humidityStatus(59.9).tone, "danger");
  for (const value of [-1, 101, null, "70", NaN]) assert.equal(humidityStatus(value).tone, "muted");
});

test("timestamps reales en ms, segundos, strings, ISO y valores ausentes", () => {
  assert.equal(parseTimestamp(EPOCH), EPOCH);
  assert.equal(parseTimestamp(EPOCH / 1000), EPOCH);
  assert.equal(parseTimestamp(String(EPOCH)), EPOCH);
  assert.equal(parseTimestamp(new Date(EPOCH).toISOString()), EPOCH);
  for (const value of [0, null, undefined, false, {}, { ".sv": "timestamp" }, "Sin evaluacion", "", NaN, Infinity, -1]) {
    assert.equal(parseTimestamp(value), null);
  }
  assert.equal(freshness(EPOCH, EPOCH + 19_999).tone, "good");
  assert.equal(freshness(EPOCH, EPOCH + 20_000).tone, "warning");
  assert.match(freshness(EPOCH + 61_000, EPOCH).label, /futura/);
});

test("ACK usa booleanos reales y distingue igualdad, desconocido y espera prolongada", () => {
  assert.equal(acknowledgement(true, false).tone, "pending");
  assert.equal(acknowledgement(true, false, 15_000).tone, "warning");
  assert.equal(acknowledgement(false, false).tone, "good");
  assert.equal(acknowledgement(true, "true").tone, "muted");
  assert.equal(acknowledgement(null, false).tone, "muted");
});

test("se suscribe una sola vez a rutas específicas; no hay lectura de nodos padres", () => {
  const h = harness();
  assert.deepEqual([...h.subscriptions.keys()], [".info/connected", ".info/serverTimeOffset", ...Object.values(READ_PATHS)]);
  h.data("temperature", 24);
  assert.equal(h.state.fields.temperature.value, 24);
  assert.equal(h.state.fields.humidity.value, null);
  h.dashboard.destroy();
  assert.equal(h.unsubscriptions.length, h.subscriptions.size);
  assert.equal(h.timers.size, 0);
});

test("la telemetría vence sin nuevos eventos ni nuevas consultas de red", () => {
  const h = harness();
  h.data("timestamp", EPOCH);
  const count = h.subscriptions.size;
  h.advance(20_001);
  assert.equal(freshness(h.state.fields.timestamp.value, h.state.now).tone, "warning");
  assert.equal(h.subscriptions.size, count);
  h.data("timestamp", EPOCH + 20_001);
  assert.equal(freshness(h.state.fields.timestamp.value, h.state.now).tone, "good");
  h.dashboard.destroy();
});

test("el offset del servidor corrige el cálculo de frescura", () => {
  const h = harness();
  h.data(".info/serverTimeOffset", 120_000);
  h.data("timestamp", EPOCH + 120_000);
  assert.equal(h.state.now, EPOCH + 120_000);
  assert.equal(freshness(h.state.fields.timestamp.value, h.state.now).tone, "good");
  h.dashboard.destroy();
});

test("solo bloquea durante la escritura; ACK pendiente permite una nueva orden", async () => {
  const calls = [];
  let resolve;
  const h = harness((value) => { calls.push(value); return new Promise((done) => { resolve = done; }); });
  h.data(".info/connected", true);
  h.data("requested", true);
  h.data("confirmed", false);
  const writing = h.dashboard.sendCommand(true);
  assert.equal(h.state.busy, true);
  assert.equal(await h.dashboard.sendCommand(false), false);
  assert.deepEqual(calls, [true]);
  h.advance(10_001);
  assert.equal(h.state.slowWrite, true);
  assert.equal(h.state.busy, true); // No se finge cancelar una escritura encolada por el SDK.
  resolve();
  assert.equal(await writing, true);
  assert.equal(h.state.busy, false);
  assert.equal(h.state.fields.confirmed.value, false); // El navegador no inventa el ACK.
  h.advance(5_001);
  assert.equal(acknowledgement(true, false, h.state.pendingElapsed).tone, "warning");
  const next = h.dashboard.sendCommand(false);
  assert.deepEqual(calls, [true, false]);
  resolve();
  await next;
  h.data("confirmed", true);
  assert.equal(h.state.pendingSince, null);
  h.dashboard.destroy();
});

test("los errores liberan el botón, se aíslan por campo y no escriben al recibir datos", async () => {
  let writes = 0;
  const h = harness(async () => { writes++; throw { code: "PERMISSION_DENIED" }; });
  h.data(".info/connected", true);
  h.data("temperature", 16);
  h.data("qualityAlert", true);
  h.error("humidity");
  assert.equal(writes, 0);
  assert.equal(h.state.fields.temperature.value, 16);
  assert.match(h.state.fields.humidity.error, /Permiso denegado/);
  assert.equal(await h.dashboard.sendCommand(true), false);
  assert.equal(h.state.busy, false);
  assert.match(h.state.message.text, /Permiso denegado/);
  h.dashboard.setOnline(false);
  await h.dashboard.sendCommand(false);
  assert.equal(writes, 1);
  h.dashboard.destroy();
});

async function adapter(hostname = "localhost") {
  const calls = [];
  let subscription;
  const context = createContext({ location: { hostname } });
  const sdk = new SyntheticModule(["onValue", "ref", "update"], function () {
    this.setExport("ref", (db, path) => ({ db, path }));
    this.setExport("update", (reference, payload) => { calls.push({ reference, payload }); return Promise.resolve(); });
    this.setExport("onValue", (reference, data, error) => { subscription = { reference, data, error }; return () => {}; });
  }, { context });
  const config = new SyntheticModule(["db"], function () { this.setExport("db", "existing-database"); }, { context });
  const source = await readFile(new URL("../firebase-client.js", import.meta.url), "utf8");
  const module = new SourceTextModule(source, { context });
  await module.link((specifier) => specifier === "./firebase-config.js" ? config : sdk);
  await module.evaluate();
  return { client: module.namespace.createFirebaseClient(), calls, get subscription() { return subscription; } };
}

test("SDK: update atómico true/false + origen manual; nunca escribe ACK ni nodos padres", async () => {
  const h = await adapter();
  await h.client.writeControl(true);
  await h.client.writeControl(false);
  assert.deepEqual(h.calls.map((call) => call.reference.path), Array(2).fill("bodega/zona_crianza/control"));
  assert.equal(h.calls[0].reference.db, "existing-database");
  for (const [index, enabled] of [true, false].entries()) {
    assert.deepEqual(Object.keys(h.calls[index].payload).sort(), ["extractor_solicitado", "origen"]);
    assert.equal(h.calls[index].payload.extractor_solicitado, enabled);
    assert.equal(h.calls[index].payload.origen, "manual");
  }
  assert.throws(() => h.client.writeControl("true"));
});

test("SDK: onValue recibe ruta, snapshot y callback de error; devuelve cancelación", async () => {
  const h = await adapter();
  let value;
  const error = () => {};
  assert.equal(typeof h.client.subscribe(READ_PATHS.confirmed, (data) => { value = data; }, error), "function");
  h.subscription.data({ val: () => false });
  assert.equal(value, false);
  assert.equal(h.subscription.reference.path, READ_PATHS.confirmed);
  assert.equal(h.subscription.error, error);
});

test("SDK: controles rechazados fuera del host local", async () => {
  const h = await adapter("dashboard.example.com");
  assert.throws(() => h.client.writeControl(true), /entorno local/);
  assert.equal(h.calls.length, 0);
});

// Doble de DOM para verificar textos/estados, sin pretender medir layout real.
async function fakeDocument() {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  function element() {
    return { textContent: "", dataset: {}, hidden: false, disabled: false, attributes: {},
      style: { setProperty() {} },
      setAttribute(key, value) { this.attributes[key] = value; },
      removeAttribute(key) { delete this.attributes[key]; },
      replaceChildren(...children) { this.textContent = children.map((child) => child.textContent).join(""); },
    };
  }
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => [match[1], element()]));
  return {
    getElementById(id) { assert.ok(elements.has(id), `Falta #${id} en HTML`); return elements.get(id); },
    createElement: element,
  };
}

test("vista: valores reales, sin supervisor inventado; textos externos no usan HTML", async () => {
  const document = await fakeDocument();
  const view = createView(document);
  const h = harness();
  h.data(".info/connected", true);
  h.data("temperature", 16);
  h.data("humidity", 70);
  h.data("requested", true);
  h.data("confirmed", false);
  h.data("impact", "<img src=x onerror=alert(1)>");
  h.data("evaluation", "Sin evaluacion");
  view.render(h.state);
  assert.equal(document.getElementById("temperature-value").textContent, "16,0");
  assert.equal(document.getElementById("humidity-value").textContent, "70");
  assert.match(document.getElementById("confirmed-value").textContent, /apagado/);
  assert.match(document.getElementById("ack-title").textContent, /pendiente/);
  assert.match(document.getElementById("supervisor-status").textContent, /pendiente de integración/);
  assert.equal(document.getElementById("evaluation-value").textContent, "Sin evaluacion");
  assert.equal(document.getElementById("impact-value").textContent, "<img src=x onerror=alert(1)>");
  assert.equal(document.getElementById("command-on").disabled, false);
  h.error("confirmed");
  h.error("qualityAlert");
  view.render(h.state);
  assert.match(document.getElementById("confirmed-value").textContent, /desconocido/);
  assert.equal(document.getElementById("supervisor-errors").hidden, false);
  h.dashboard.destroy();
});

test("vista: fallos del CDN y falta de conexión dejan mensajes y controles deshabilitados", async () => {
  const document = await fakeDocument();
  const view = createView(document);
  const h = harness();
  view.render(h.state);
  assert.equal(document.getElementById("command-on").disabled, true);
  assert.equal(document.getElementById("connection-warning").hidden, false);
  view.fatal("CDN inaccesible");
  assert.equal(document.getElementById("app-error").textContent, "CDN inaccesible");
  assert.equal(document.getElementById("command-off").disabled, true);
  h.dashboard.destroy();
});
