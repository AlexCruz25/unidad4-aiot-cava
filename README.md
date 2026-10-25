# Sistema AIoT para Cava de Crianza en Barricas

Trabajo Práctico Integrador de la Unidad 4: **Arquitectura AIoT y Sistemas
Ciberfísicos**. Los pasos 1 a 8 están implementados. El usuario informa que sus
funciones principales fueron comprobadas con el ESP32 físico. El Paso 9 aporta
pruebas reproducibles, revisión de seguridad y un protocolo para registrar la
validación física final; no convierte ese antecedente en nuevos ensayos aprobados.

## Implementación actual

- ESP32 WROOM-32 con Arduino Core **3.3.11**, DHT22 simulado y actuador en **GPIO 2**.
- HTTPS PATCH de ambiente cada **5000 ms** cuando la red y los recursos permiten
  enviar; timestamp de Firebase. `millis()` e `isnan()`, sin `delay()`.
- SSE HTTPS persistente para recibir el booleano solicitado, sin polling.
  PUT de `extractor_confirmado` después de aplicar el GPIO; reintentos y TLS con CA.
- Dashboard HTML/CSS/JavaScript con `onValue()`, controles manuales locales,
  estado solicitado/confirmado, avisos de datos antiguos y resultados del supervisor.
- Supervisor Python **3.12**, FastAPI y Firebase Admin: reglas deterministas,
  transacciones de control, histéresis temporal y análisis enológico Gemini con
  JSON Schema/Pydantic. Gemini no decide directamente el actuador.
- `DRY_RUN=true` impide escrituras del supervisor; no impide lecturas ni, si está
  configurada la key, llamadas de análisis. Los tests usan dobles y no consumen API.

El dispositivo y el Dashboard todavía no incorporan Firebase Authentication.
Las reglas desplegadas no están en este repositorio y **sus permisos públicos
no están verificados**. La propuesta del Paso 9 se prueba solo en un emulador;
no debe publicarse sobre los clientes actuales sin completar la migración.

## Documentación

| Componente | Guía |
| --- | --- |
| Arquitectura e interfaces actuales | [docs/arquitectura.md](docs/arquitectura.md) |
| Firmware y comandos serie 1/2/3/9/E/A | [01_firmware/README.md](01_firmware/README.md) |
| Dashboard y servidor local | [02_frontend/README.md](02_frontend/README.md) |
| Supervisor, configuración y operación | [03_supervisor_aiot/README.md](03_supervisor_aiot/README.md) |
| Casos y protocolo físico final | [docs/paso9-plan-pruebas.md](docs/paso9-plan-pruebas.md) |
| Resultados, defectos y evidencias | [docs/paso9-resultados.md](docs/paso9-resultados.md) |
| Riesgos y migración de seguridad | [docs/paso9-seguridad.md](docs/paso9-seguridad.md) |

## Preparar Ubuntu

Para las pruebas locales: Python 3.12 con `venv`, Node **20 o superior compatible
con los paquetes fijados**, npm, g++, pkg-config y cJSON de desarrollo. En Ubuntu,
los paquetes de sistema necesarios incluyen `python3-venv`, `build-essential`,
`pkg-config` y `libcjson-dev`. No instalar dependencias Python globalmente.

Para una instalación nueva, preferir **Node 24 LTS** y repetir las suites. Node
20.19.5 es el entorno utilizado aquí, pero la rama 20 ya figura EOL en el
[calendario oficial](https://nodejs.org/en/about/previous-releases). No se cambió
el runtime del usuario durante esta revisión.

Desde la raíz del repositorio; crear `.venv` solo si no existe y reutilizarla
cuando ya esté preparada:

```bash
python3 -m venv 03_supervisor_aiot/.venv
03_supervisor_aiot/.venv/bin/python -m pip install -r 03_supervisor_aiot/requirements.txt
npm --prefix tests/firebase ci --ignore-scripts --no-audit --no-fund --cache /tmp/cava-paso9-npm-cache
```

Para el emulador se verificaron Firebase CLI **14.20.0**, Java **17.0.20.1** y
Database Emulator **4.11.2**. Si falta CLI, instalar manualmente
`npm install -g firebase-tools@14.20.0`. No hace falta `firebase login` ni un
proyecto real. CLI avisa que la versión 15 requerirá Java 21; revisar los
requisitos antes de cambiar de versión. La primera ejecución puede descargar
el JAR público a `/tmp/cava-paso9-emulators`.

El frontend no necesita un empaquetador ni paquetes npm para sus pruebas.
El firmware completo se prepara en Arduino IDE con el Core 3.3.11; las suites
C++ de PC no equivalen a compilar ni cargar la placa. El ejecutor admite como
alternativa local el encabezado cJSON del Core 3.3.11 y la biblioteca de Ubuntu.

Para operar el sistema, seguir las guías de cada componente. Crear `.env` y
`secrets.h` desde sus plantillas **solo si no existen**, completar los secretos
localmente y conservarlos fuera de Git. No iniciar el supervisor en modo real
para ejecutar las pruebas automatizadas.

## Ejecutar pruebas sin servicios reales

```bash
python3 scripts/test_firmware.py
npm --prefix 02_frontend test
03_supervisor_aiot/.venv/bin/python -m pytest -q 03_supervisor_aiot/tests
03_supervisor_aiot/.venv/bin/python -m pip check
python3 scripts/test_firebase.py
python3 scripts/audit_private_files.py
```

El ejecutor de seguridad usa exclusivamente **demo-cava-paso9 / 127.0.0.1:9019**
y no hereda claves ni `DEBUG` del shell. Las reglas propuestas y dependencias
de pruebas están en `tests/firebase/`; no hay configuración de despliegue de
producción. No ejecutar `firebase deploy` con esa propuesta.

## Parámetros ambientales conservados

| Condición | Comportamiento |
| --- | --- |
| Ideal | 12–18 °C y 65–80 % inclusive |
| Protección crítica | T **>22 °C** o HR **<60 %**; prevalece sobre apagado manual |
| T=22 °C / HR=60 % | No activa por sí sola una nueva protección crítica |
| Recuperación automática | 60 s continuos de nuevas muestras ideales; una interrupción reinicia el período |
| Encendido manual en ambiente no crítico | Se respeta; no se apaga automáticamente por cumplir 60 s |

Un ACK es el estado lógico aplicado e informado por el ESP32: no mide corriente,
posición ni efecto térmico. El DHT22 simulado no cambia por encender el LED.
Las conclusiones físicas y los requisitos pendientes para publicar el sistema
se registran en los documentos del Paso 9.
