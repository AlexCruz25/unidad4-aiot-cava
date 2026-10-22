/*
 * Proyecto: Sistema AIoT para Cava de Crianza
 * Unidad: Trabajo Práctico Integrador - Unidad 4
 * Componente: Configuración de Firebase para el frontend
 *
 */

import { initializeApp } from "https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js";
import { getDatabase } from "https://www.gstatic.com/firebasejs/12.19.0/firebase-database.js";

const firebaseConfig = {
  apiKey: "AIzaSyChDdcN4Ikkl0SJ4L2XVx26PDrrOytwngU",
  authDomain: "unidad4-aiot-cava.firebaseapp.com",
  databaseURL: "https://unidad4-aiot-cava-default-rtdb.firebaseio.com",
  projectId: "unidad4-aiot-cava",
  storageBucket: "unidad4-aiot-cava.firebasestorage.app",
  messagingSenderId: "881958103281",
  appId: "1:881958103281:web:d81f09b3b894616b8a6150",
  measurementId: "G-E4KNXFLV70"
};

const app = initializeApp(firebaseConfig);
const db = getDatabase(app);

export { db };
