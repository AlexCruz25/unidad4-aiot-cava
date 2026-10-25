# Paso 9 · Registro de resultados

Fecha: **24/10/2026** · Zona horaria de trabajo: **America/Argentina/Mendoza
(UTC−03)**. Revisión base: **a42042a**, con cambios de este trabajo sin commit.
El `.gitignore` ya tenía modificaciones locales: se conservaron y solo se
agregaron exclusiones para las dependencias de tests y `firebase-admin.json`.

El usuario informa funcionamiento físico previo de los pasos 1 a 8. No se
observaron ni se ejecutaron nuevos ensayos físicos durante esta revisión.
Los resultados siguientes corresponden a tests en computadora y emulador.

## Ejecución automatizada

| Área | Comando desde la raíz | Aprobadas | Fallidas finales | Alcance |
| --- | --- | --- | --- | --- |
| Firmware | `python3 scripts/test_firmware.py` | **2 suites C++** | **0** | ACK y parser HTTP/SSE, compilados con `-Wall -Wextra -Werror` |
| Frontend | `npm --prefix 02_frontend test` | **14 tests** | **0** | DOM/SDK simulados; sin conexión a Firebase |
| Supervisor | `03_supervisor_aiot/.venv/bin/python -m pytest -q 03_supervisor_aiot/tests` | **91 tests** | **0** | Reglas, runtime, API ASGI, adaptadores, JSON y diagnóstico |
| Reglas propuestas | `python3 scripts/test_firebase.py` | **26 tests** | **0** | RTDB Emulator 4.11.2, demo-cava-paso9, identidades simuladas |
| Dependencias Python | `03_supervisor_aiot/.venv/bin/python -m pip check` | Sin conflictos | 0 | `No broken requirements found` |
| Secretos/Git | `python3 scripts/audit_private_files.py` | Sin hallazgos en alcance | 0 | 50 archivos rastreados, archivos nuevos públicos y nombres históricos |
| Formato | `git diff --check` | Correcto | 0 | Diferencias rastreadas sin errores de whitespace |

Son **131 tests Python/JavaScript y 2 ejecutables C++ aprobados**. No se cuentan
cada assert C++ como un test independiente. La suite del supervisor pasó de 84 a
91 casos; el frontend conserva sus 14 casos. No se hicieron generaciones reales
de Gemini ni lecturas/escrituras de la base real durante estos tests.

Entorno observado: Python 3.12, Node 20.19.5, npm 10.8.2, Firebase CLI 14.20.0,
Java 17.0.20.1; dependencias Python fijadas en `03_supervisor_aiot/requirements.txt`.
Pruebas de reglas con `@firebase/rules-unit-testing` 5.0.0 y `firebase` 12.19.0,
fijados con package-lock. No se actualizó Node, Java o CLI del sistema.

La máquina no tiene `libcjson-dev`/pkg-config de cJSON. Para PC se utilizó el
encabezado del SDK esp32-libs 3.3.11 ya instalado y `libcjson.so.1` de Ubuntu;
el ejecutor detecta esa alternativa. En una instalación limpia se recomienda
`libcjson-dev`. No se afirma equivalencia con handshake, tareas o memoria del
ESP32. No se compiló una imagen nueva ni se cargó la placa en esta revisión.

El registro de la última ejecución del emulador está en
`/tmp/cava-paso9-emulador-salida.log` (temporal, datos simulados, sin credenciales).
Finalizó con 26 pass, 0 fail, 0 skipped y cierre del emulador. Puede regenerarse
con el comando indicado. No es una captura o evidencia del dispositivo físico.

## Defectos e incidencias

| ID | Evidencia reproducida | Corrección / resultado |
| --- | --- | --- |
| D01 | Nuevo test ASGI con token no ASCII provocó `TypeError: comparing strings with non-ASCII characters is not supported` en `POST /evaluar`; la comparación ASCII inválida sí se rechazaba | `main.py` compara UTF-8 bytes con `secrets.compare_digest`; ambas entradas inválidas reciben 403. La autenticación válida y ausencia de escrituras en tests siguen aprobadas |
| D02 | README y arquitectura principales describían estructura inicial y desarrollos futuros, a pesar de implementación existente | Documentación actualizada a PATCH/SSE/ACK, onValue, reglas antes de IA, transacciones, DRY_RUN y límites reales del ACK |
| T01 | Primera suite nueva de reglas: 24/25; el test anónimo usaba `ref("")`, ruta rechazada por el SDK antes de evaluar reglas | Se corrigió el test a `ref("/")`. Pasó 25/25 y, al añadir la comprobación explícita del bypass Admin, 26/26. No era un defecto del firmware ni una regla pública |

D01 fue el **único cambio funcional**. No se encontró otro defecto reproducible
que justificara modificar firmware, Dashboard, reglas ambientales o umbrales.
El wrapper del emulador ejecuta con entorno reducido para no heredar `DEBUG`
ni posibles secretos del shell al registro de una herramienta externa.

## Comunicación e interfaces revisadas

| Comprobación | Resultado observado en fuente/tests | Límite |
| --- | --- | --- |
| PATCH | Turno 5000 ms, `isnan`, timestamp servidor, HTTPS con CA; omite turnos ocupados/sin red | Periodicidad y HTTP reales pendientes F01 |
| SSE | GET persistente exclusivo, sin polling; fragmentación/chunked/307; backoff y estados cancel/auth_revoked | TLS y reconexión en placa pendientes F06/F07 |
| ACK | GPIO/estado local antes de registrar ACK; confirma también el mismo valor; solo 200 resuelve versión actual | Orden temporal revisado en código; medir físicamente F02/F07 |
| Clientes | TLS de SSE exclusivo; PATCH/PUT serializados, HTTP/TLS cerrados y destrucción en orden correcto | Heap/TLS real pendientes F07/M03 |
| Pines/TLS | GPIO 2 conservado; ninguna llamada `delay()` ni `setInsecure()`; CA vigente en implementación | No certifica conectividad ni cadena del servidor en placa hoy |
| Dashboard | 10 rutas de datos por onValue, solicitado/confirmado, pendiente, origen, resultados, errores y duplicados cubiertos | Layout real no probado por DOM simulado |
| Responsive | Viewport y media queries 1200/900/650 px revisados, grillas de una columna y textos con ajuste | Pendiente observación en navegador/móvil M01; no se cambió el diseño |
| Supervisor | 22/60 estrictos, recuperación continua, manual/protección, datos inválidos/viejos, IA ausente, caché, carrera y DRY_RUN cubiertos | Operación real y evidencias físicas pendientes |

Las rutas y tipos de firmware, Dashboard y supervisor siguen compatibles con
el contrato descrito en [arquitectura.md](arquitectura.md). El prototipo de
reglas agrega requisitos de identidad **a futuro**, no altera clientes actuales.

## Riesgos pendientes

- Reglas desplegadas ausentes: acceso público real no verificado.
- REST/SSE y Dashboard actuales sin Firebase Authentication.
- Localhost en JavaScript no autoriza solicitudes directas a la base.
- Firebase Admin privilegiado; la propuesta con claims no limita automáticamente
  el certificado actual. El test de bypass lo muestra en emulador.
- ACK booleano sin correlación/fecha; simulación no prueba efecto microclimático.
- Migración pendiente: usuarios/roles, dispositivo, renovación/revocación y
  buffers/redirecciones de SSE autenticado.
- Node 20 de las herramientas está EOL; se documentó actualizar a Node 24 LTS
  y repetir las suites antes de preparar un entorno nuevo de entrega/CI.

Detalle, matriz de permisos y orden de migración en
[paso9-seguridad.md](paso9-seguridad.md). No se publicó ninguna regla.

## Registro físico por completar

Seguir el procedimiento y criterio individual de cada caso en
[paso9-plan-pruebas.md](paso9-plan-pruebas.md). Estados admitidos: pendiente,
aprobada, fallida o bloqueada con motivo. Completar fecha/hora con zona,
operador, modo DRY_RUN y evidencia accesible antes de cambiar el estado.

| ID | Escenario | Fecha/hora/TZ y operador | DRY_RUN | Resultado observado | Veredicto | Evidencia |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | 16 °C / 70 % | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| F02 | 24 °C / 70 %; protección térmica | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| F03 | 17 °C / 55 %; protección por humedad | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| F04 | 60 s de recuperación e interrupción | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| F05 | Orden manual, duplicados y ACK | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| F06 | ESP32 desconectado, pendiente y datos viejos | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| F07 | Reconexión y sincronización SSE/ACK | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| F08 | Gemini ausente con reglas operativas | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| M01 | Móvil, horizontal y zoom | Pendiente | No aplica | Pendiente | **Pendiente** | Pendiente |
| M02 | NAN simulado (`9`) y recuperación (`1`) | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |
| M03 | Estabilidad y heap durante 15 min | Pendiente | Pendiente | Pendiente | **Pendiente** | Pendiente |

Plantilla para ampliar una observación:

```text
Caso / revisión / operador:
Fecha y hora, zona horaria:
Versiones y variante firmware (SSE/ACK activos):
DRY_RUN y estado inicial de control/ACK:
Inicio/fin, pasos efectuados:
Valores y timestamps ambientales observados:
Orden → GPIO → ACK; latencias medidas:
HTTP/reconexiones/heap libre-mínimo-bloque mayor:
Resultado observado y criterio aplicado:
Veredicto y defectos asociados:
Archivos/enlaces de evidencia sin secretos:
Restauración de escenario/proceso y estado final:
```

No se inventaron capturas ni resultados físicos. Una prueba en DRY_RUN no
aprueba actuación automática real; un HTTP aceptado no aprueba ejecución del pin.

## Archivos de este trabajo

- `.gitignore`: exclusiones añadidas, sin descartar las previas.
- `README.md`, `docs/arquitectura.md`: estado y contratos actuales.
- `docs/paso9-plan-pruebas.md`, `docs/paso9-resultados.md`,
  `docs/paso9-seguridad.md`: documentación nueva de validación.
- `01_firmware/tests/test_ack.cpp`, `01_firmware/tests/test_sse.cpp`: más casos
  negativos, sin modificar el firmware de la placa.
- `03_supervisor_aiot/main.py`: corrección D01.
- `03_supervisor_aiot/tests/test_api.py`, `test_rules.py`, `test_runtime.py`:
  siete casos adicionales (incluida parametrización).
- `scripts/test_firmware.py`, `test_firebase.py`, `audit_private_files.py`:
  ejecutores y auditoría reproducibles.
- `tests/firebase/package.json`, `package-lock.json`, `firebase.emulator.json`,
  `database.proposed.rules.json`, `rules.test.mjs`: propuesta aislada y tests.

## Criterio de cierre

Automatización y preparación documental: aprobadas con los límites indicados.
**Validación física final: pendiente** de F01–F08/M01–M03 con evidencia revisada.
**Publicación segura: pendiente** de exportar/revisar reglas reales y completar
la migración de seguridad antes de exponer el sistema. No hubo commit ni push,
ni cambios a archivos privados, base real, firmware o diseño del Dashboard.
