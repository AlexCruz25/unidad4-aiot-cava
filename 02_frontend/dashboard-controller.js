import {
  READ_PATHS, STALE_AFTER_MS, ACK_WARNING_MS, WRITE_WARNING_MS,
  isBoolean, isNumber, parseTimestamp, readableError,
} from "./dashboard-state.js";

export function createDashboard(client, render, options = {}) {
  const now = options.now ?? Date.now;
  const setTimer = options.setTimer ?? setTimeout;
  const clearTimer = options.clearTimer ?? clearTimeout;
  const fields = Object.fromEntries(Object.keys(READ_PATHS).map((key) => [key, {
    value: null, loaded: false, error: null,
  }]));
  const state = {
    fields, connected: false, connectionError: null, online: options.online ?? true,
    localControl: options.localControl ?? false, serverOffset: 0,
    busy: false, slowWrite: false, writeTarget: null, message: null,
    pendingSince: null, now: now(),
  };
  let destroyed = false;
  let pendingKey = null;
  let freshnessTimer;
  let ackTimer;
  let writeTimer;
  const unsubscribers = [];

  function emit() {
    if (destroyed) return;
    state.now = now() + state.serverOffset;
    const requested = fields.requested.error ? null : fields.requested.value;
    const confirmed = fields.confirmed.error ? null : fields.confirmed.value;
    const mismatch = fields.requested.loaded && fields.confirmed.loaded &&
      isBoolean(requested) && isBoolean(confirmed) && requested !== confirmed;
    const key = mismatch ? `${requested}/${confirmed}` : null;
    if (key !== pendingKey) {
      pendingKey = key;
      state.pendingSince = mismatch ? now() : null;
      clearTimer(ackTimer);
      if (mismatch) ackTimer = setTimer(emit, ACK_WARNING_MS + 1);
    }
    state.pendingElapsed = state.pendingSince === null ? 0 : Math.max(0, now() - state.pendingSince);
    clearTimer(freshnessTimer);
    const timestamp = fields.timestamp.error ? null : parseTimestamp(fields.timestamp.value);
    if (timestamp !== null && timestamp - state.now <= 60_000) {
      const remaining = timestamp + STALE_AFTER_MS - state.now;
      if (remaining > 0) freshnessTimer = setTimer(emit, remaining + 1);
    }
    // Temporizadores locales: no disparan ninguna lectura de red.
    render(state);
  }

  function subscribe(path, onData, onError) {
    try {
      unsubscribers.push(client.subscribe(path, onData, onError));
    } catch (error) {
      onError(error);
    }
  }

  emit();
  subscribe(".info/connected", (value) => {
    state.connected = value === true;
    state.connectionError = null;
    emit();
  }, (error) => {
    state.connected = false;
    state.connectionError = readableError(error);
    emit();
  });
  subscribe(".info/serverTimeOffset", (value) => {
    state.serverOffset = isNumber(value) ? value : 0;
    emit();
  }, () => { state.serverOffset = 0; emit(); });

  for (const [key, path] of Object.entries(READ_PATHS)) {
    subscribe(path, (value) => {
      fields[key] = { value, loaded: true, error: null };
      emit();
    }, (error) => {
      fields[key] = { value: null, loaded: true, error: readableError(error) };
      emit();
    });
  }

  return {
    async sendCommand(enabled) {
      if (destroyed || state.busy || !isBoolean(enabled)) return false;
      if (!state.localControl || !state.online || !state.connected) {
        state.message = { tone: "warning", text: "El control requiere localhost y una conexión activa con Firebase." };
        emit();
        return false;
      }
      state.busy = true;
      state.slowWrite = false;
      state.writeTarget = enabled;
      state.message = { tone: "pending", text: "Enviando solicitud a Firebase…" };
      writeTimer = setTimer(() => {
        state.slowWrite = true;
        state.message = { tone: "warning", text: "La escritura sigue en tránsito. Puede guardarse cuando vuelva la conexión; aún no hay aceptación del servidor." };
        emit();
      }, WRITE_WARNING_MS);
      emit();
      try {
        await client.writeControl(enabled);
        state.message = { tone: "good", text: `Firebase aceptó la solicitud de ${enabled ? "encendido" : "apagado"}. La ejecución se verifica por separado con el estado confirmado.` };
        return true;
      } catch (error) {
        state.message = { tone: "danger", text: readableError(error) };
        return false;
      } finally {
        clearTimer(writeTimer);
        state.busy = false;
        state.slowWrite = false;
        state.writeTarget = null;
        emit();
      }
    },
    setOnline(online) { state.online = online; emit(); },
    refresh: emit,
    destroy() {
      destroyed = true;
      clearTimer(freshnessTimer);
      clearTimer(ackTimer);
      clearTimer(writeTimer);
      for (const unsubscribe of unsubscribers) unsubscribe?.();
    },
  };
}
