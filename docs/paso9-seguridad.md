# Paso 9 · Seguridad y propuesta de migración

Revisión local: **24/10/2026**. Esta es una propuesta probada con identidades
simuladas en Realtime Database Emulator. **No son las reglas desplegadas**;
no se modificaron ni se publicaron reglas, credenciales o datos reales.

## Hallazgos y alcance real

| ID | Evidencia del proyecto | Riesgo / estado |
| --- | --- | --- |
| S01 | No hay copia de reglas de producción ni configuración de despliegue en el repositorio al iniciar la revisión | Lectura/escritura pública **no verificadas**. No se presume seguridad ni se inventa una regla actual |
| S02 | Firmware REST/SSE sin token Auth; Dashboard inicializa Database sin inicio de sesión | No identifica ni autoriza actores por usuario/dispositivo. Si esos accesos funcionan sin token en producción, sugieren permisos anónimos en las rutas usadas; es una inferencia que debe contrastarse con las reglas reales |
| S03 | `writeControl` comprueba localhost en JavaScript | Reduce errores de uso en la interfaz, pero se puede omitir con un cliente propio; no es una barrera de servidor |
| S04 | `FirebaseRepository.open()` usa certificado Admin sin `databaseAuthVariableOverride` | Credencial privilegiada; las reglas propuestas no restringen por sí solas ese cliente actual |
| S05 | Índice/copia de trabajo rastreados sin claves PEM o JSON de servicio detectados; sin rutas privadas históricas detectadas | No se detectaron secretos versionados dentro del alcance de la auditoría. No equivale a un escaneo exhaustivo de todos los secretos y blobs históricos |
| S06 | ACK es solo booleano; versión de orden solo interna del ESP32 | No acredita antigüedad, identidad de una orden concreta ni funcionamiento eléctrico. Igualdad con un valor viejo puede parecer sincronización |
| S07 | SSE valida HTTPS/CA y acepta redirecciones HTTPS, pero no tiene identidad renovable ni lista de destinos de tokens | Antes de agregar Auth se deben diseñar renovación, expiración, tamaño de buffers y redirecciones sin filtración |
| S08 | Endpoint local comparaba tokens `str` con `compare_digest` | Token no ASCII causaba TypeError/500; **corregido y cubierto con regresión**, ahora 403 |
| S09 | Node 20.19.5 usado para las herramientas locales de pruebas | Rama EOL; migrar herramientas/CI a una LTS con soporte y repetir suites. El frontend entregado es estático y no usa un servidor Node |

La configuración web Firebase (`apiKey`, project ID, URL) no es una cuenta
administrativa ni autoriza por sí sola una operación. El control corresponde a
Auth y reglas; no se deben ocultar reglas abiertas detrás de una API key web.
Ver [claves de API en Firebase](https://firebase.google.com/docs/projects/api-keys).
La revisión no encontró PEM privada/cuenta Admin en el Dashboard. El firmware
incluye Wi-Fi mediante `secrets.h`, no imprime la contraseña ni contiene una
cuenta Admin; una credencial Wi-Fi compilada sigue siendo sensible ante acceso
físico a la memoria del dispositivo.

Firebase Admin opera con acceso privilegiado por defecto. Puede configurarse
una identidad limitada mediante `databaseAuthVariableOverride`, pero quien robe
la credencial administrativa puede quitar ese override. No es una reducción
irreversible del poder de la clave. Ver
[Admin con privilegios limitados](https://firebase.google.com/docs/database/admin/start#authenticate-with-limited-privileges).
El test de administración del emulador comprueba explícitamente el bypass;
los demás tests prueban identidades sujetas a reglas, no el certificado actual.

Node 20 figura EOL y Node 24 LTS en el
[calendario oficial](https://nodejs.org/en/about/previous-releases), consultado
en esta revisión. Se mantuvo el entorno existente para verificarlo; para nuevas
instalaciones se recomienda Node 24 LTS y repetir la matriz. Fijar versiones de
dependencias da reproducibilidad, no acredita ausencia de vulnerabilidades ni
reemplaza mantener herramientas actualizadas.

## Permisos necesarios y roles propuestos

Todas las rutas son relativas a `/bodega/zona_crianza`. Los identificadores
siguientes son nombres de diseño, **no credenciales creadas**.

| Actor | Identidad propuesta | Lecturas | Escrituras |
| --- | --- | --- | --- |
| ESP32 | UID `esp32-cava-01`, claims `role=device`, `zone=zona_crianza` | Solo `control/extractor_solicitado` para SSE | PATCH `ambiente`; PUT `extractor_confirmado` |
| Dashboard operador | Usuario Auth habilitado, claims `role=operator`, `zone=zona_crianza` | Ambiente, control/origen, ACK, resultados del supervisor | Update atómico de control con origen manual |
| Dashboard visor | Usuario Auth, claims `role=viewer`, misma zona | Igual lectura del operador | Ninguna |
| Supervisor limitado | UID `supervisor-cava`, claims `role=supervisor`, misma zona | Zona completa por contrato actual de `read_zone()`; incluida lectura necesaria para transacciones | Transacción control con origen supervisor; update de resultados |
| Sin sesión / sin rol / otra zona / UID de dispositivo ajeno | Ninguna autorización | Denegadas | Denegadas |

El permiso de lectura del supervisor se da en la zona y hereda hacia sus hijos
porque el adaptador actual lee el objeto completo. No se concede lectura de
raíz ni otras zonas. Reducirlo a hijos requeriría cambiar primero ese adaptador;
no se simuló una compatibilidad inexistente. El navegador sí escucha rutas hijas
y no necesita lectura de la zona padre.

Solo un entorno administrativo confiable asignaría claims y aprovisionaría
identidades; el usuario/dispositivo no decide su propio rol. El ejemplo contempla
un único ESP32 autorizado para esta zona. Más dispositivos requieren asignación
explícita por zona y revisión de concurrencia, no compartir un UID y una contraseña.

## Propuesta ejecutable, aislada de producción

Archivos:

- [Reglas propuestas](../tests/firebase/database.proposed.rules.json).
- [Configuración solo de emulador](../tests/firebase/firebase.emulator.json).
- [Tests con usuarios simulados](../tests/firebase/rules.test.mjs).
- [Ejecutor con entorno reducido](../scripts/test_firebase.py).
- Dependencias fijadas y lock en `tests/firebase/package.json`/`package-lock.json`.

El proyecto es **demo-cava-paso9**; RTDB escucha solo en **127.0.0.1:9019**,
hub 4419 y logging 4519, sin UI. No se carga `firebase-config.js`, `.env`, el
certificado ni `secrets.h`. El wrapper no hereda variables de claves, tokens o
`DEBUG`; usa directorios temporales propios para configuración y descargas.
Los tests exigen ese host/proyecto y limpian únicamente la base demo.
Los proyectos `demo-` no tienen recursos reales:
[guía oficial de conexión al emulador](https://firebase.google.com/docs/emulator-suite/connect_rtdb).

Desde la raíz, con Node 20, CLI 14.20.0 y Java 17 disponibles:

```bash
npm --prefix tests/firebase ci --ignore-scripts --no-audit --no-fund --cache /tmp/cava-paso9-npm-cache
python3 scripts/test_firebase.py
```

No se necesita `firebase login`. La primera ejecución descarga el JAR público
si no está en la caché temporal. No reemplazar el ID demo por el del proyecto
real. No ejecutar `firebase deploy`. Los avisos `permission_denied` de los
casos negativos son esperados; el aprobado se determina por las aserciones,
no por ausencia de mensajes. El registro local está en
`/tmp/cava-paso9-emulador-salida.log` y solo contiene datos/identidades simulados.

Las pruebas usan `authenticatedContext()` y `unauthenticatedContext()` de
`@firebase/rules-unit-testing`, según la
[API oficial de pruebas](https://firebase.google.com/docs/reference/emulator-suite/rules-unit-testing/rules-unit-testing.rulestestenvironment).
Validan evaluación de reglas con claims simulados; **no** implementan ni prueban
login real, emisión/renovación/revocación de tokens, REST/SSE autenticado del
ESP32 o IAM del certificado Admin.

La propuesta deniega por defecto. Valida tipos y campos obligatorios, rango
físico del sensor (-40 a 80 °C; 0 a 100 %), timestamp en ms reciente, ACK booleano,
origen de control coherente con el rol y formato de publicación del supervisor.
Acepta timestamp de servidor y el contrato de update/transacción existente.
No cambia umbrales críticos ni reglas de histéresis.

El texto publicado por supervisor admite hasta 2048 caracteres para incluir
prefijo de procedencia y nota de prevalencia de reglas, además de los 20–900
caracteres del resultado Pydantic. Su fecha se valida como ISO UTC; la expresión
no verifica toda la semántica del calendario. Se rechazan borrados, campos extra
y una operación multipath que incluya un destino prohibido. Antes de migrar,
inventariar hijos ajenos/legados: el código actual los conserva y una validación
cerrada puede rechazarlos. No borrar datos reales para hacer pasar estas pruebas.

## Migración sin interrumpir los clientes actuales

1. **Obtener evidencia de las reglas desplegadas.** El responsable debe exportar
   la pestaña Rules, fecha y revisión; identificar concesiones `.read`/`.write`
   públicas, reglas heredadas y vencimientos. Conservar una copia revisable sin
   secretos. Evaluar datos existentes en el emulador, con información anonimizada.
2. **Definir usuarios, roles y dispositivo.** Habilitar el proveedor Auth elegido,
   sin registro público de operadores ni autoasignación de claims. Separar visor,
   operador y dispositivo. Diseñar revocación de usuarios y baja de una placa.
3. **Migrar Dashboard primero en emulador.** Incorporar sesión Auth, esperar su
   estado antes de suscribir/escribir, mostrar permisos denegados y cerrar
   listeners al salir. Mantener rutas, update atómico y ACK exclusivo del ESP32.
   Probar logout, sesión vencida y operador/visor en escritorio y móvil.
4. **Diseñar autenticación del ESP32 sin Admin.** Usar una identidad por dispositivo,
   aprovisionamiento fuera de Git y almacenamiento protegido. Una opción es un
   broker confiable que emite un custom token después de autenticar la placa;
   Firebase Auth lo intercambia por ID/refresh token. El firmware nunca recibe
   la clave que firma esos tokens. Otra opción debe conservar identidad individual,
   revocación y autorización por ruta, sin una credencial compartida administrativa.
5. **Implementar y ensayar renovación REST/SSE.** La API REST documenta ID token
   en `auth=<ID_TOKEN>`; no confundir custom token con ID token ni usar un secreto
   legado de base. Probar refresh, expiración, `auth_revoked`, 401/403 y recuperación
   de SSE sin polling. ID tokens son de corta vida; conservar NTP y TLS.
   Ver [autenticación REST](https://firebase.google.com/docs/database/rest/auth) y
   [sesiones y renovación](https://firebase.google.com/docs/auth/admin/manage-sessions).
6. **Revisar límites del firmware antes de anexar un token.** La URL actual admite
   767 bytes y el buffer de GET 1100; medir el token real y el heap con dos TLS.
   Acotar buffers/colas y destinos de redirección autorizados para no reenviar
   credenciales a cualquier host HTTPS. Nunca imprimir URL completa, ID token,
   refresh token o cabeceras de autorización. Repetir PATCH/SSE/ACK, reconexiones
   y diagnósticos de memoria en emulador y en la placa antes del cambio real.
7. **Reducir y proteger el servicio.** Mantener FastAPI en loopback, un worker,
   token local y sin confianza en proxy headers. Para una primera reducción
   defensiva puede configurarse el override de identidad del Admin y probarse
   contra el emulador; no está aplicado en esta revisión. Para un límite más
   fuerte, evaluar una identidad no administrativa/gateway con reglas o IAM
   adecuado. Proteger/rotar credenciales, limitar quién puede crear claves o
   asignar claims y preferir credenciales de entorno administrado cuando exista.
8. **Ensayo completo y cambio controlado.** Con Auth de todos los componentes
   validado, repetir la matriz y ocho escenarios, preparar revisión/backup y un
   horario de cambio. Publicar reglas solo mediante una acción explícita del
   responsable. No aplicar la propuesta ahora: los clientes actuales sin sesión
   quedarían bloqueados. Un rollback no debe consistir en escritura pública
   permanente; conservar una configuración anterior revisada y acceso acotado.

A futuro, un ID de orden y ACK con fecha/ID de dispositivo mejorarían trazabilidad.
Eso altera el contrato y requiere una migración coordinada, no cambiar el
booleano actual durante esta validación.

## Protección de secretos y cierre antes de publicar

`.env`, `.venv/`, `secrets.h`, el directorio privado del supervisor y sus JSON,
PEM/KEY están ignorados. Se agregó también el nombre `firebase-admin.json`
fuera de ese directorio, conservando los cambios locales previos en `.gitignore`.
No se imprimieron ni modificaron archivos privados. Verificar desde la raíz:

```bash
python3 scripts/audit_private_files.py
git check-ignore -v 03_supervisor_aiot/.env 03_supervisor_aiot/.venv/ 01_firmware/cava_esp32/secrets.h 03_supervisor_aiot/credentials/firebase-admin.json
git ls-files -- 03_supervisor_aiot/.env 01_firmware/cava_esp32/secrets.h firebase-admin.json
```

El auditor detecta rutas privadas, PEM privada y JSON de cuenta de servicio en
índice/trabajo y archivos nuevos no ignorados; revisa nombres históricos, no todos
sus blobs. No detecta toda clave arbitraria ni acredita ausencia de filtraciones
externas. Ante una credencial expuesta, revocar/rotar y revisar el historial;
quitarla de una captura o agregarla a `.gitignore` no invalida una copia existente.

Antes de publicar: resolver S01–S04/S07/S09, revisar secretos y permisos reales,
registrar las pruebas físicas, completar identidad/renovación/revocación y
confirmar límites del servicio privilegiado. No considerar este sistema seguro
para exposición pública solo porque los tests de la propuesta pasan.
