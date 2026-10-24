import { temperatureStatus, humidityStatus, freshness, acknowledgement, parseTimestamp, isBoolean, isNumber } from "./dashboard-state.js";

const number = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });
const date = new Intl.DateTimeFormat("es-AR", { dateStyle: "medium", timeStyle: "medium" });

export function createView(document) {
  const get = (id) => document.getElementById(id);
  function text(id, value) {
    if (get(id).textContent !== value) get(id).textContent = value;
  }
  function badge(id, tone, label) {
    get(id).dataset.tone = tone;
    if (label !== undefined) text(id, label);
  }
  function message(id, value) {
    get(id).hidden = !value;
    text(id, value ?? "");
  }
  function time(id, value, fallback) {
    const milliseconds = parseTimestamp(value);
    text(id, milliseconds === null ? fallback : date.format(new Date(milliseconds)));
    if (milliseconds === null) get(id).removeAttribute("datetime");
    else get(id).setAttribute("datetime", new Date(milliseconds).toISOString());
  }
  function metric(key, field, status, formatter, max) {
    const value = field.error ? null : field.value;
    const valid = isNumber(value) && status.tone !== "muted";
    text(`${key}-value`, valid ? formatter.format(value) : "—");
    badge(`${key}-state`, status.tone, field.error ? "Lectura no disponible" : status.label);
    badge(`${key}-card`, status.tone);
    get(`${key}-marker`).hidden = !valid;
    if (valid) get(`${key}-marker`).style.setProperty("--position", `${Math.max(0, Math.min(100, value / max * 100))}%`);
    message(`${key}-error`, field.error);
  }
  function bool(value, yes, no, fallback = "Sin datos") {
    return isBoolean(value) ? (value ? yes : no) : fallback;
  }

  function render(state) {
    const f = state.fields;
    const connected = state.connected && state.online;
    badge("connection-badge", connected ? "good" : "warning");
    text("connection-text", connected ? "Firebase conectado" : (state.online ? "Firebase sin conexión" : "Navegador sin red"));
    message("connection-warning", connected ? null : "Sin conexión activa con Firebase. Los valores visibles son el último registro recibido; los controles están deshabilitados.");
    message("app-error", state.connectionError);
    const recent = freshness(f.timestamp.error ? null : f.timestamp.value, state.now);
    badge("freshness-badge", recent.tone);
    text("freshness-text", f.timestamp.error ? "Fecha no disponible" : recent.label);
    message("timestamp-error", f.timestamp.error);
    time("updated-at", f.timestamp.error ? null : f.timestamp.value, "Sin fecha");
    metric("temperature", f.temperature, temperatureStatus(f.temperature.value), number, 35);
    metric("humidity", f.humidity, humidityStatus(f.humidity.value), percent, 100);

    const enabled = connected && state.localControl && !state.busy;
    get("command-on").disabled = !enabled;
    get("command-off").disabled = !enabled;
    get("control-buttons").setAttribute("aria-busy", String(state.busy));
    text("control-policy", !state.localControl
      ? "Solo lectura fuera de localhost. El control público requiere autenticación y reglas de acceso."
      : state.busy ? "Esperando la respuesta de escritura de Firebase…"
      : !connected ? "Conectate a Firebase para habilitar el control manual."
      : "Control local habilitado. Esperar un ACK no bloquea una nueva orden.");
    message("write-message", state.message?.text);
    if (state.message) badge("write-message", state.message.tone);
    text("requested-value", bool(f.requested.value, "Encendido", "Apagado", "Desconocido") + (state.busy ? " · solicitud en tránsito" : ""));
    text("origin-value", typeof f.origin.value === "string" && f.origin.value.trim() ? f.origin.value : "Sin datos");
    message("control-error", f.requested.error ?? f.origin.error);
    const confirmed = f.confirmed.error ? null : f.confirmed.value;
    text("confirmed-value", bool(confirmed, "Climatizador encendido", "Climatizador apagado", "Estado desconocido"));
    badge("confirmed-icon", confirmed === true ? "good" : "muted");
    message("confirmed-error", f.confirmed.error);
    const ack = acknowledgement(f.requested.error ? null : f.requested.value, confirmed, state.pendingElapsed);
    badge("ack-box", state.busy ? "pending" : ack.tone);
    text("ack-title", state.busy ? "Solicitud en tránsito" : ack.label);
    text("ack-detail", state.busy
      ? "El evento local del SDK todavía no acredita aceptación de Firebase ni una nueva confirmación del ESP32."
      : ack.detail);

    text("alert-value", bool(f.qualityAlert.value, "Alerta activa", "Sin alerta registrada"));
    badge("alert-value", f.qualityAlert.value === true ? "danger" : f.qualityAlert.value === false ? "good" : "muted");
    text("forced-value", bool(f.forced.value, "Solicitado por supervisor", "No solicitado"));
    badge("forced-value", f.forced.value === true ? "warning" : "muted");
    text("impact-value", typeof f.impact.value === "string" && f.impact.value.trim() ? f.impact.value : "Sin descripción registrada");
    const evaluationFallback = typeof f.evaluation.value === "string" && f.evaluation.value.trim()
      ? f.evaluation.value : "Sin evaluación registrada";
    time("evaluation-value", f.evaluation.value, evaluationFallback);
    badge("supervisor-status", "muted", parseTimestamp(f.evaluation.value) === null
      ? "Supervisor IA pendiente de integración" : "Evaluación registrada en Firebase");
    const errors = ["qualityAlert", "forced", "impact", "evaluation"].filter((key) => f[key].error);
    const errorsNode = get("supervisor-errors");
    errorsNode.hidden = errors.length === 0;
    const descriptions = { qualityAlert: "Alerta de calidad", forced: "Forzar climatización", impact: "Impacto enológico", evaluation: "Última evaluación" };
    const errorText = errors.map((key) => `${descriptions[key]}: ${f[key].error}`);
    if (errorsNode.textContent !== errorText.join("")) {
      errorsNode.replaceChildren(...errorText.map((value) => {
        const item = document.createElement("li");
        item.textContent = value;
        return item;
      }));
    }
  }

  return {
    render,
    loading() { text("connection-text", "Conectando con Firebase…"); },
    fatal(value) {
      badge("connection-badge", "danger");
      text("connection-text", "Firebase no disponible");
      message("app-error", value);
      text("control-policy", "Control no disponible: no se pudo iniciar Firebase.");
      get("command-on").disabled = true;
      get("command-off").disabled = true;
    },
  };
}
