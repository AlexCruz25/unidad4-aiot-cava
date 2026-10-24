import { createDashboard } from "./dashboard-controller.js";
import { createView } from "./dashboard-view.js";

const view = createView(document);
const localHost = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(location.hostname);
let dashboard;

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => dashboard?.sendCommand(button.dataset.command === "on"));
});

view.loading();
try {
  // La interfaz y sus mensajes siguen disponibles si falla el CDN o la configuración.
  const { createFirebaseClient } = await import("./firebase-client.js");
  dashboard = createDashboard(createFirebaseClient(), view.render, {
    localControl: localHost,
    online: navigator.onLine,
  });
  window.addEventListener("online", () => dashboard.setOnline(true));
  window.addEventListener("offline", () => dashboard.setOnline(false));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) dashboard.refresh();
  });
  window.addEventListener("pagehide", (event) => {
    if (!event.persisted) dashboard.destroy();
  });
} catch (error) {
  console.error("No se pudo iniciar Firebase:", error);
  view.fatal("No se pudo cargar Firebase. Revisá Internet, firebase-config.js y el acceso a www.gstatic.com; después recargá la página.");
}
