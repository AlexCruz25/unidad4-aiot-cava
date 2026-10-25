# Paso 9 · Plan de pruebas integrales

Fecha de preparación: **24/10/2026**. Objetivo: verificar la implementación
existente, corregir solo defectos reproducidos y reunir evidencia de entrega.
Los resultados de esta ejecución están en [paso9-resultados.md](paso9-resultados.md).

## Alcance y condiciones

Las suites automatizadas usan dobles, transporte ASGI/HTTP simulado y un
Realtime Database Emulator local. No usan la base del proyecto ni Gemini real.
No se cargan programas al ESP32, no se cambian `.env`, `secrets.h`, credenciales,
pines ni reglas desplegadas. El único cambio funcional de esta revisión es el
rechazo controlado de tokens HTTP no ASCII, explicado en resultados.

El usuario informa pruebas físicas anteriores de los pasos 1 a 8. Los ocho
escenarios de este documento deben registrarse con fecha y evidencia;
no se dan por aprobados por ese antecedente.

## Pruebas automatizadas y trazabilidad

| ID | Caso / resultado esperado | Cobertura ejecutable |
| --- | --- | --- |
| A01 | 16 °C/70 %: normal, sin orden automática nueva | Supervisor `test_environmental_thresholds`; frontend temperatura/humedad |
| A02 | 24 °C/70 %: crítico, encender si está apagado | Umbrales; runtime reglas antes de IA |
| A03 | 17 °C/55 %: crítico por humedad | Umbrales; errores de Gemini sin perder protección |
| A04 | T=22, HR=60 y 22/60: fuera del ideal, sin nueva activación crítica | Umbrales parametrizados y frontend límites exactos |
| A05 | Recuperación: a 55 s mantener; a 60 s apagar orden automática una sola vez | Reglas; `test_automatic_recovery_writes_off_once_after_stable_ideal` |
| A06 | Muestra no ideal o hueco >15 s reinicia recuperación; repetir timestamp no la avanza | `test_recovery_restarts_after_a_new_nonideal_measurement`; test de huecos |
| A07 | Encendido manual respetado; apagado manual crítico se revierte en siguiente evaluación válida | Reglas manuales; `test_manual_off_is_reversed_only_on_next_valid_critical_evaluation` |
| A08 | Ausentes, bool, cadenas, NAN, infinito, rango físico inválido: no actuar | Validación de mediciones y runtime datos inválidos |
| A09 | >20 s o futuro >5 s: rechazar; sin órdenes ni IA sobre datos viejos | Frescura, runtime y frontend vencimiento sin nuevas lecturas |
| A10 | Firebase caído: degradado, reiniciar recuperación, sin falsa ejecución | Runtime lectura/reconexión/listener; API 409/503; frontend errores |
| A11 | Gemini ausente/timeout/429/JSON inválido: reglas operativas y análisis no disponible | Runtime, adaptadores y diagnóstico sin secretos |
| A12 | Intervalo mínimo, caché, vencimiento y backoff limitan llamadas | `test_cache_frequency_and_backoff`; `test_expired_ai_cache_requires_new_generation_but_not_repeated_calls` |
| A13 | Cambio manual aborta transacción; 12 evaluaciones simultáneas emiten una sola orden | Transacciones; `test_concurrent_evaluations_issue_only_one_critical_order` |
| A14 | JSON Schema/Pydantic: bool reales, tres campos, texto válido | Transporte HTTP local del SDK real; casos inválidos/adicionales |
| A15 | DRY_RUN: ninguna llamada a escritores ni cambios en el repositorio simulado | Runtime DRY_RUN y guardas Firebase |
| A16 | POST /evaluar: token, loopback, Host, cuerpo y errores; lock excluye segunda instancia | ASGI; `test_singleton_rejects_second_instance_and_releases` |
| A17 | SSE: fragmentación, chunked, JSON estricto, 307; errores no son órdenes | `01_firmware/tests/test_sse.cpp`; reconexión revisada en fuente y pendiente en F06/F07 |
| A18 | ACK: solo 200, versiones nuevas, reintentos 5/60 s y desborde millis | `01_firmware/tests/test_ack.cpp`; GPIO→ACK revisado en fuente |
| A19 | Dashboard: onValue, solicitado/confirmado, pendiente, manual, errores, duplicados, supervisor | 14 tests `02_frontend/tests/dashboard.test.js` con dobles DOM/SDK |
| A20 | Propuesta: permisos mínimos, denegación anónima, validación y Admin privilegiado | `tests/firebase/rules.test.mjs`; alcance en seguridad |
| A21 | Secretos fuera de Git; sin PEM privada o cuenta de servicio detectada | `scripts/audit_private_files.py` y `git check-ignore` |

Comandos desde la raíz:

```bash
python3 scripts/test_firmware.py
npm --prefix 02_frontend test
03_supervisor_aiot/.venv/bin/python -m pytest -q 03_supervisor_aiot/tests
03_supervisor_aiot/.venv/bin/python -m pip check
npm --prefix tests/firebase ci --ignore-scripts --no-audit --no-fund --cache /tmp/cava-paso9-npm-cache
python3 scripts/test_firebase.py
python3 scripts/audit_private_files.py
```

Dependencias/versiones en el README y manifiestos. Dejar libres 9019/4419/4519.
No cambiar el proyecto `demo-` ni añadir credenciales. El wrapper inicia/detiene
el emulador; los tests fallan cerrados si el host/proyecto no son los esperados.

## Preparación física

1. Placa de banco, GPIO 2/LED y simulación activa; monitor serie **115200**,
   comandos `1`, `2`, `3`, `9`, `E`, `A`. No editar el firmware para crear bordes:
   22 °C y 60 % se cubren con mocks.
2. Registrar revisión Git, versiones, operador, fecha y zona horaria. Arranque
   completo: SSE/ACK/PATCH activos, Wi-Fi, NTP y TLS con CA.
3. Dashboard en localhost; registrar `/health` y `/status` sin tokens. Usar una
   instancia y un worker, sin `--reload`, con `--no-proxy-headers`.
4. Empezar con DRY_RUN. Para probar actuación real, el operador debe iniciar
   deliberadamente el supervisor configurado con `DRY_RUN=false` y verificarlo
   en `/health`; en true solo se esperan decisiones simuladas. Este plan no
   inicia ese modo ni modifica el archivo privado.
5. Conservar tiempos de espera, caché y backoff. No forzar generaciones IA por
   cada cambio ni repetir `--probe-gemini`. La protección no depende de la IA.
6. Capturar logs con timestamps, ocultando Wi-Fi, tokens, key y JSON Admin.
   No cambiar reglas para aprobar: registrar denegaciones y resolverlas mediante
   la migración de seguridad.

Para restablecer un caso que requiere salida apagada: seleccionar `1`, esperar
una nueva muestra ideal, apagar desde el Dashboard (origen manual) y esperar
GPIO/ACK false. No usar E/A como sustituto de esa orden: cambian el pin local,
pero no el control ni su origen en Firebase.

Con red saludable, PATCH aproximadamente cada 5 s, con turnos omitidos si hay
ACK/petición en curso. Aceptar una orden en Firebase no equivale a ACK.
Registrar latencias; el aviso de 15 s no es un plazo garantizado. Tras 20 s sin
muestra el Dashboard señala datos antiguos.

## Protocolo físico reproducible

### F01 · Ambiente normal: 16 °C / 70 %

- **Objetivo:** verificar telemetría, visualización y coexistencia de conexiones.
- **Inicial:** Wi-Fi/NTP válidos, versión completa, orden manual false, GPIO LOW.
- **Procedimiento:** enviar `1`; observar 2 minutos sin cambiar órdenes. Registrar
  PATCH, SSE, memoria, rutas ambientales y Dashboard/status.
- **Esperado:** 16/70, timestamp creciente, decisión normal y sin nuevo encendido;
  SSE sano permanece abierto, sin GET periódico.
- **Observado:** **Pendiente**.
- **Aprobación:** valores/frescura coherentes, PATCH exitosos entre ACK, sin
  reconexiones continuas ni caída sostenida del heap comparando estados equivalentes.
- **Evidencia:** log serie, captura Dashboard, ambiente/control/ACK y `/status`.

### F02 · Temperatura crítica: 24 °C / 70 %

- **Objetivo:** protección térmica y prioridad frente al apagado manual.
- **Inicial:** F01 reciente; supervisor real habilitado deliberadamente, control
  manual false, sin otro operador actuando.
- **Procedimiento:** enviar `2`; seguir PATCH→evaluación→control true/origen
  supervisor→SSE→GPIO HIGH→PUT. Apagar desde Dashboard una vez y esperar la
  siguiente medición crítica válida.
- **Esperado:** encendido; un apagado manual puede aplicarse transitoriamente y
  se revierte en la siguiente evaluación crítica válida.
- **Observado:** **Pendiente**.
- **Aprobación:** orden y ACK finales true, LED encendido; protección sin esperar
  Gemini y sin interpretar errores como confirmaciones exitosas.
- **Evidencia:** secuencia serie con timestamps, control/origen/ACK, decisión y LED.

### F03 · Humedad crítica: 17 °C / 55 %

- **Objetivo:** comprobar humedad independientemente de temperatura alta.
- **Inicial:** conexión sana, supervisor real, control inicialmente apagado.
- **Procedimiento:** seleccionar `3`; seguir la cadena de F02 y observar
  `humedad_inferior_60` y visualización 17/55.
- **Esperado:** mitigación true aunque la temperatura esté en rango ideal.
- **Observado:** **Pendiente**.
- **Aprobación:** crítico por humedad, GPIO HIGH, ACK true posterior y PATCH/SSE activos.
- **Evidencia:** log serie, captura ambiental, decisión y confirmación.

### F04 · Recuperación ideal continua durante 60 s

- **Objetivo:** comprobar histéresis, reinicio y apagado de orden automática.
- **Inicial:** encendido true/origen supervisor debido a F02 o F03.
- **Procedimiento:** seleccionar `1`; t0 es el primer timestamp ideal recibido
  por supervisor. Seguir muestras nuevas sin huecos >15 s: antes de 60 s debe
  mantener encendido; en la primera evaluación desde 60 s puede apagar.
  Repetir interrumpiendo a los 30 s con `2`; mantenerlo hasta observar un PATCH
  crítico y su evaluación, y recién entonces volver a `1`.
- **Esperado:** contar muestras, no clics en evaluar. Interrumpir reinicia el período;
  después, control false, SSE, GPIO LOW y ACK false.
- **Observado:** **Pendiente**.
- **Aprobación:** no apagar antes de 60 s continuos; un solo apagado por recuperación,
  sin heredar tiempo del período interrumpido.
- **Evidencia:** timestamps, segundos estables de `/status`, control, log y LED/ACK.

### F05 · Control manual desde Dashboard

- **Objetivo:** verificar control, duplicados y respeto de intención manual.
- **Inicial:** escenario `1`, datos recientes, Dashboard localhost conectado.
- **Procedimiento:** encender una vez, observar aceptación y ACK; mantener ideal
  más de 60 s; apagar una vez. Intentar el mismo botón durante una escritura
  pendiente; distinguir bloqueo de escritura de espera de ACK.
- **Esperado:** update atómico de booleano/origen manual; conservar encendido manual;
  navegador no escribe ACK. Tras terminar la escritura se admite otra orden,
  aunque el ACK siga pendiente.
- **Observado:** **Pendiente**.
- **Aprobación:** sin escrituras simultáneas duplicadas, estado final aplicado
  coherente y sin apagado automático del encendido manual por histéresis.
- **Evidencia:** solicitado/confirmado/origen, serie, LED y escrituras observadas.

### F06 · Desconexión temporal del ESP32

- **Objetivo:** observar datos antiguos y ausencia de falsa confirmación nueva.
- **Inicial:** `1`, orden y ACK false; PC/supervisor conservan Internet.
- **Procedimiento:** apagar solo el ESP32 al menos 30 s o bloquear solo su acceso.
  Solicitar true desde Dashboard. Esperar >15 s desde la diferencia de booleanos
  y >20 s desde la última medición; no desconectar la PC.
- **Esperado:** Firebase puede aceptar la orden; ACK sigue false, pendiente
  prolongado y datos antiguos. Supervisor no actúa sobre muestras vencidas.
  `.info/connected` del navegador puede seguir true.
- **Observado:** **Pendiente**.
- **Aprobación:** no afirmar ejecución con la placa ausente; distinguir conexión
  del navegador, frescura ambiental y confirmación lógica.
- **Evidencia:** captura antes/después, timestamp detenido, `/health`, ausencia de nuevos PUT.

### F07 · Reconexión y sincronización SSE/ACK

- **Objetivo:** restablecer el lazo después de F06 con una orden pendiente.
- **Inicial:** true solicitado con placa desconectada y último ACK false.
- **Procedimiento:** reconectar sin cambiar orden; observar Wi-Fi, NTP, apertura
  SSE/instantánea inicial, GPIO y PUT. Repetir perdiendo solo Wi-Fi para observar
  reintentos sin reinicio.
- **Esperado:** aplicar estado vigente y confirmar; recuperar PATCH. También se
  confirma si el pin ya coincide. Puede haber estados transitorios al sincronizar.
- **Observado:** **Pendiente**.
- **Aprobación:** solicitado/GPIO/ACK finales coherentes, datos recientes, clientes
  liberados y sin reconexión continua; -1/3xx/4xx/5xx nunca son ACK exitosos.
  No se exige que el mínimo histórico de heap vuelva a subir.
- **Evidencia:** log desde antes de desconectar hasta 2 minutos después, LED,
  confirmación, timestamps y heap libre/mínimo/bloque mayor.

### F08 · Gemini temporalmente no disponible

- **Objetivo:** protección independiente de IA.
- **Inicial:** Firebase sano, una instancia del supervisor, ESP32 en `1`.
- **Procedimiento:** detener supervisor y reiniciar con `GEMINI_API_KEY=` solo
  en el entorno de ese proceso, sin editar `.env`. Verificar key no configurada
  mediante el booleano del diagnóstico. Mantener modo real de banco si se prueba
  GPIO, seleccionar `2`/`3` y observar reglas. Detener y reiniciar sin override
  para recuperar Gemini, respetando límites de llamadas.
- **Esperado:** IA no disponible, reglas críticas operativas, sin análisis inventado.
  Timeout/429 se cubren con mocks, sin agotar cuota ni usar claves inválidas reales.
- **Observado:** **Pendiente**.
- **Aprobación:** orden/LED/ACK correctos sin Gemini. En DRY_RUN registrar solo
  decisión simulada y dejar actuación física sin aprobar.
- **Evidencia:** diagnóstico booleano sin secretos, `/status`, decisión, logs,
  ACK y constancia de restaurar el proceso original.

## Comprobaciones manuales complementarias

- **M01 móvil:** 320, 390, 768 y 1280 px, horizontal y zoom 200 %; sin scroll
  horizontal y con textos/controles legibles. Los tests DOM no prueban layout.
  Desde IP LAN el control manual está deshabilitado por diseño; no eliminar
  esa restricción para aprobar una captura.
- **M02 sensor inválido:** comando `9`; tras una petición válida ya en curso,
  no salen nuevos PATCH inválidos; se vencen datos, pero SSE/GPIO continúan.
  Volver a `1` y comprobar recuperación.
- **M03 estabilidad:** 15 minutos, varios PATCH y órdenes; comparar heap libre
  y bloque mayor en fases equivalentes. Registrar mínimos, errores, latencias
  y reconexiones, sin inferir fuga solo por el mínimo histórico.

## Cierre

Verificación funcional cerrada: suites aprobadas, F01–F08/M01–M03 con evidencia
revisada, defectos resueltos o aceptados explícitamente con sus límites.
Para **publicar**, completar revisión de reglas desplegadas y migración de
identidades/roles, privilegios Admin y renovación de tokens descritas en
seguridad. El emulador no certifica permisos ni conexiones de producción.
