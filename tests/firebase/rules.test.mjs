// Propuesta para migración: este archivo nunca carga configuración de producción.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { after, before, beforeEach, test } from "node:test";
import { initializeTestEnvironment, assertFails, assertSucceeds } from "@firebase/rules-unit-testing";

const PROJECT = "demo-cava-paso9";
const ROOT = "bodega/zona_crianza";
// Fallar cerrado: jamás intentar contactar una base real ni otro emulador.
assert.equal(process.env.FIREBASE_DATABASE_EMULATOR_HOST, "127.0.0.1:9019",
  "Ejecutar npm run test:emulator; se exige el emulador local del Paso 9.");
assert.equal(process.env.GCLOUD_PROJECT, PROJECT, "Se exige el proyecto demo aislado.");
let env;
const claims = (role, zone = "zona_crianza") => ({ role, zone });
const db = (role, uid = role === "device" ? "esp32-cava-01" : role === "supervisor" ? "supervisor-cava" : "operador-prueba") =>
  env.authenticatedContext(uid, claims(role)).database();
const telemetry = () => ({ temperatura: 16, humedad: 70, timestamp: { ".sv": "timestamp" } });
const report = () => ({ alerta_calidad: false, forzar_climatizacion: false,
  impacto_enologico: "Análisis simulado para verificar permisos; no proviene de Gemini.",
  ultima_evaluacion: new Date().toISOString() });

before(async () => {
  env = await initializeTestEnvironment({ projectId: PROJECT, database: {
    host: "127.0.0.1", port: 9019,
    rules: readFileSync(new URL("database.proposed.rules.json", import.meta.url), "utf8"),
  } });
});
beforeEach(async () => {
  await env.clearDatabase();
  await env.withSecurityRulesDisabled(async (context) => {
    await context.database().ref(ROOT).set({ ambiente: telemetry(),
      control: { extractor_solicitado: false, origen: "manual" },
      extractor_confirmado: false, supervisor: report() });
  });
});
after(async () => { await env?.cleanup(); });

test("anónimo: sin lectura pública en raíz, zona ni rutas de la aplicación", async () => {
  const anonymous = env.unauthenticatedContext().database();
  for (const path of ["/", ROOT, ...["ambiente", "control", "extractor_confirmado", "supervisor"].map(p => `${ROOT}/${p}`)]) {
    await assertFails(anonymous.ref(path).once("value"));
  }
});
test("anónimo: sin escrituras públicas ni borrado de la zona", async () => {
  const anonymous = env.unauthenticatedContext().database();
  for (const [path, value] of [["ambiente", telemetry()], ["control", { extractor_solicitado: true, origen: "manual" }],
    ["extractor_confirmado", true], ["supervisor", report()]]) {
    await assertFails(anonymous.ref(`${ROOT}/${path}`).set(value));
  }
  await assertFails(anonymous.ref(ROOT).remove());
});
test("estar autenticado sin claims no habilita ningún permiso", async () => {
  const unknown = env.authenticatedContext("usuario-sin-rol").database();
  await assertFails(unknown.ref(`${ROOT}/ambiente`).once("value"));
  await assertFails(unknown.ref(`${ROOT}/control`).update({ extractor_solicitado: true, origen: "manual" }));
});
test("dispositivo: publica ambiente con timestamp servidor, lee orden y confirma booleano", async () => {
  const device = db("device");
  await assertSucceeds(device.ref(`${ROOT}/ambiente`).update(telemetry()));
  assert.equal((await assertSucceeds(device.ref(`${ROOT}/control/extractor_solicitado`).once("value"))).val(), false);
  await assertSucceeds(device.ref(`${ROOT}/extractor_confirmado`).set(true));
  await assertSucceeds(device.ref(`${ROOT}/extractor_confirmado`).set(false));
});
test("dispositivo: no lee nodos padres ni escribe órdenes o análisis", async () => {
  const device = db("device");
  await assertFails(device.ref(ROOT).once("value"));
  await assertFails(device.ref(`${ROOT}/control`).once("value"));
  await assertFails(device.ref(`${ROOT}/control`).update({ extractor_solicitado: true, origen: "manual" }));
  await assertFails(device.ref(`${ROOT}/supervisor`).update(report()));
});
test("UID ajeno o zona ajena no suplanta la identidad del dispositivo", async () => {
  await assertFails(db("device", "esp32-no-autorizado").ref(`${ROOT}/ambiente`).update(telemetry()));
  const wrongZone = env.authenticatedContext("esp32-cava-01", claims("device", "otra_zona")).database();
  await assertFails(wrongZone.ref(`${ROOT}/extractor_confirmado`).set(true));
});
for (const [field, value] of [["temperatura", "24"], ["temperatura", true], ["temperatura", 81],
  ["humedad", -1], ["humedad", 101], ["timestamp", 0], ["timestamp", Date.now() + 86400000], ["extra", "intrusión"]]) {
  test(`telemetría rechazada: ${field}=${JSON.stringify(value)}`, async () => {
    await assertFails(db("device").ref(`${ROOT}/ambiente`).update({ ...telemetry(), [field]: value }));
  });
}
test("no se borran telemetría, hijos obligatorios ni confirmaciones", async () => {
  const device = db("device");
  await assertFails(device.ref(`${ROOT}/ambiente`).remove());
  await assertFails(device.ref(`${ROOT}/ambiente/temperatura`).remove());
  await assertFails(device.ref(`${ROOT}/extractor_confirmado`).remove());
});
test("ACK rechaza cadenas, números y objetos", async () => {
  for (const value of ["true", 1, { estado: true }]) {
    await assertFails(db("device").ref(`${ROOT}/extractor_confirmado`).set(value));
  }
});
for (const role of ["operator", "viewer"]) {
  test(`${role}: lee las rutas exactas del Dashboard`, async () => {
    for (const path of ["ambiente/temperatura", "ambiente/humedad", "ambiente/timestamp",
      "control/extractor_solicitado", "control/origen", "extractor_confirmado",
      "supervisor/alerta_calidad", "supervisor/forzar_climatizacion", "supervisor/impacto_enologico", "supervisor/ultima_evaluacion"]) {
      await assertSucceeds(db(role).ref(`${ROOT}/${path}`).once("value"));
    }
    await assertFails(db(role).ref(ROOT).once("value"));
  });
}
test("operador: orden manual atómica; no falsifica origen supervisor ni ACK", async () => {
  const operator = db("operator");
  await assertSucceeds(operator.ref(`${ROOT}/control`).update({ extractor_solicitado: true, origen: "manual" }));
  await assertFails(operator.ref(`${ROOT}/control`).update({ extractor_solicitado: false, origen: "supervisor" }));
  await assertFails(operator.ref(`${ROOT}/extractor_confirmado`).set(true));
  await assertFails(operator.ref(`${ROOT}/ambiente`).update(telemetry()));
  await assertFails(operator.ref(`${ROOT}/supervisor`).update(report()));
});
test("visor: lectura sin órdenes ni escalamiento de privilegios", async () => {
  await assertFails(db("viewer").ref(`${ROOT}/control`).update({ extractor_solicitado: true, origen: "manual" }));
  await assertFails(db("viewer").ref("roles/operador-prueba").set("operator"));
});
test("control: booleanos estrictos, origen válido y sin hijos extra", async () => {
  for (const update of [{ extractor_solicitado: "true", origen: "manual" },
    { extractor_solicitado: 1, origen: "manual" }, { extractor_solicitado: true, origen: "manual", extra: true }]) {
    await assertFails(db("operator").ref(`${ROOT}/control`).update(update));
  }
  await assertFails(db("operator").ref(`${ROOT}/control`).remove());
});
test("supervisor limitado: lee zona y hace transacción de control; publica solo análisis", async () => {
  const supervisor = db("supervisor");
  await assertSucceeds(supervisor.ref(ROOT).once("value"));
  const result = await assertSucceeds(supervisor.ref(`${ROOT}/control`).transaction(current =>
    current ? { ...current, extractor_solicitado: true, origen: "supervisor" } : current));
  assert.equal(result.committed, true);
  await assertSucceeds(supervisor.ref(`${ROOT}/supervisor`).update(report()));
  await assertFails(supervisor.ref(`${ROOT}/ambiente`).update(telemetry()));
  await assertFails(supervisor.ref(`${ROOT}/extractor_confirmado`).set(true));
  await assertFails(supervisor.ref("bodega/otra_zona").set({ control: true }));
});
test("supervisor: UID incorrecto no obtiene permisos por declarar solo el rol", async () => {
  await assertFails(db("supervisor", "otro-servicio").ref(ROOT).once("value"));
  await assertFails(db("supervisor", "otro-servicio").ref(`${ROOT}/supervisor`).update(report()));
});
test("análisis: sin booleanos coercibles, campos omitidos, texto corto o timestamp ficticio", async () => {
  const supervisor = db("supervisor");
  for (const invalid of [{ ...report(), alerta_calidad: "false" }, { ...report(), impacto_enologico: "corto" },
    { ...report(), ultima_evaluacion: "Sin evaluacion" }, { ...report(), extra: true }, { alerta_calidad: false }]) {
    await assertFails(supervisor.ref(`${ROOT}/supervisor`).set(invalid));
  }
  await assertFails(supervisor.ref(`${ROOT}/supervisor`).remove());
});
test("actualización multipath con un destino prohibido se rechaza completa", async () => {
  await assertFails(db("operator").ref(ROOT).update({
    "control/extractor_solicitado": true, "control/origen": "manual", extractor_confirmado: true,
  }));
  const zone = (await db("supervisor").ref(ROOT).once("value")).val();
  assert.equal(zone.control.extractor_solicitado, false);
  assert.equal(zone.extractor_confirmado, false);
});
test("administración del emulador omite reglas: una clave Admin requiere protección adicional", async () => {
  await env.withSecurityRulesDisabled(async (context) => {
    await assertSucceeds(context.database().ref(`${ROOT}/extractor_confirmado`).set(true));
  });
  assert.equal((await db("viewer").ref(`${ROOT}/extractor_confirmado`).once("value")).val(), true);
});
