import { db } from "./firebase-config.js";
import { onValue, ref, update } from "https://www.gstatic.com/firebasejs/12.19.0/firebase-database.js";

const ROOT = "bodega/zona_crianza";

export function createFirebaseClient() {
  return {
    subscribe(path, onData, onError) {
      return onValue(ref(db, path), (snapshot) => onData(snapshot.val()), onError);
    },
    writeControl(enabled) {
      if (typeof enabled !== "boolean") throw new TypeError("La orden debe ser booleana");
      if (!["localhost", "127.0.0.1", "::1", "[::1]"].includes(location.hostname)) {
        throw new Error("El control manual está limitado al entorno local");
      }
      // Una escritura atómica conserva los demás hijos del nodo control.
      // El navegador jamás escribe extractor_confirmado ni otros nodos.
      return update(ref(db, `${ROOT}/control`), {
        extractor_solicitado: enabled,
        origen: "manual",
      });
    },
  };
}
