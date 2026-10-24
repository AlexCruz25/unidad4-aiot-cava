export const STALE_AFTER_MS = 20_000;
export const ACK_WARNING_MS = 15_000;
export const WRITE_WARNING_MS = 10_000;

export const READ_PATHS = Object.freeze({
  temperature: "bodega/zona_crianza/ambiente/temperatura",
  humidity: "bodega/zona_crianza/ambiente/humedad",
  timestamp: "bodega/zona_crianza/ambiente/timestamp",
  requested: "bodega/zona_crianza/control/extractor_solicitado",
  origin: "bodega/zona_crianza/control/origen",
  confirmed: "bodega/zona_crianza/extractor_confirmado",
  qualityAlert: "bodega/zona_crianza/supervisor/alerta_calidad",
  forced: "bodega/zona_crianza/supervisor/forzar_climatizacion",
  impact: "bodega/zona_crianza/supervisor/impacto_enologico",
  evaluation: "bodega/zona_crianza/supervisor/ultima_evaluacion",
});

export const isBoolean = (value) => typeof value === "boolean";
export const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

export function temperatureStatus(value) {
  if (!isNumber(value)) return { tone: "muted", label: "Sin lectura válida" };
  if (value > 22) return { tone: "danger", label: "Temperatura crítica" };
  if (value > 18) return { tone: "warning", label: "Temperatura elevada" };
  if (value < 12) return { tone: "warning", label: "Por debajo del ideal" };
  return { tone: "good", label: "En rango ideal" };
}

export function humidityStatus(value) {
  if (!isNumber(value) || value < 0 || value > 100) return { tone: "muted", label: "Sin lectura válida" };
  if (value < 60) return { tone: "danger", label: "Humedad crítica" };
  if (value < 65) return { tone: "warning", label: "Humedad baja" };
  if (value > 80) return { tone: "warning", label: "Humedad elevada" };
  return { tone: "good", label: "En rango ideal" };
}

// Firebase usa server timestamp (ms). También se admiten segundos, strings
// numéricos e ISO con zona explícita; nunca adivinar fechas locales.
export function parseTimestamp(value) {
  let milliseconds;
  if (typeof value === "string") {
    const text = value.trim();
    if (/^\d+(?:\.\d+)?$/.test(text)) value = Number(text);
    else if (/^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/i.test(text)) milliseconds = Date.parse(text);
    else return null;
  }
  if (isNumber(value) && value > 0) milliseconds = value < 100_000_000_000 ? value * 1000 : value;
  if (!Number.isFinite(milliseconds) || milliseconds < 946_684_800_000 || milliseconds > 4_102_444_800_000) return null;
  return milliseconds;
}

export function freshness(timestamp, now) {
  const time = parseTimestamp(timestamp);
  if (time === null) return { tone: "muted", label: "Sin fecha de actualización", time };
  if (time - now > 60_000) return { tone: "warning", label: "Fecha futura: revisar el reloj", time };
  if (now - time >= STALE_AFTER_MS) return { tone: "warning", label: "Datos antiguos · más de 20 s", time };
  return { tone: "good", label: "Telemetría reciente", time };
}

export function acknowledgement(requested, confirmed, elapsed = 0) {
  if (!isBoolean(requested) || !isBoolean(confirmed)) {
    return { tone: "muted", label: "Confirmación no verificable", detail: "Esperando un estado solicitado y confirmado válidos." };
  }
  if (requested === confirmed) {
    return { tone: "good", label: "Solicitado y confirmado coinciden", detail: "Último estado aplicado informado por el ESP32. No es una lectura eléctrica del actuador." };
  }
  return {
    tone: elapsed >= ACK_WARNING_MS ? "warning" : "pending",
    label: "Orden pendiente de confirmación del ESP32",
    detail: elapsed >= ACK_WARNING_MS
      ? "Los estados difieren hace más de 15 s. Revisá la placa y la conexión; esto no demuestra una falla física. Podés enviar otra orden."
      : "La solicitud y el último estado confirmado todavía son distintos.",
  };
}

export function readableError(error) {
  const code = String(error?.code ?? "").toLowerCase();
  if (code.includes("permission") || code.includes("denied")) {
    return "Permiso denegado por Firebase. Revisá las reglas y la autenticación; no se modificaron desde el dashboard.";
  }
  return "No se pudo completar la operación. Revisá la conexión y los permisos de Firebase.";
}
