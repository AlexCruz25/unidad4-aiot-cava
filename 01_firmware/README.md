# Firmware ESP32 — PASOS 3 a 6

El ESP32 físico simula un DHT22, mantiene el control manual del climatizador y
publica las lecturas válidas en Firebase Realtime Database mediante HTTPS PATCH.
Además, recibe órdenes reactivas por SSE desde una conexión HTTPS persistente
independiente y sincroniza GPIO 2 con `extractor_solicitado`. Después de aplicar
cada orden, confirma el estado local en `extractor_confirmado` mediante HTTPS PUT.
La simulación se ejecuta en la placa; no requiere un sensor conectado ni una
librería DHT.

## Configurar y cargar

1. Instalar el paquete **esp32 by Espressif Systems** desde el gestor de placas
   de Arduino IDE, si todavía no está instalado.
2. En `01_firmware/cava_esp32/secrets.h`, reemplazar localmente los valores de
   ejemplo por el nombre y la contraseña de la red Wi-Fi. Usar una red de
   **2,4 GHz** compatible con el ESP32 WROOM-32. No compartir la contraseña por
   el monitor serie ni incorporarla al archivo `.ino`.
3. Si se obtuvo el proyecto desde Git, crear primero `secrets.h` copiando
   `secrets.h.example` en la misma carpeta. La plantilla pública contiene:

   ```cpp
   #pragma once
   #define WIFI_SSID "NOMBRE_DE_TU_WIFI"
   #define WIFI_PASSWORD "CONTRASENA_DE_TU_WIFI"
   ```

4. Abrir `cava_esp32/cava_esp32.ino`. La carpeta y el sketch comparten el nombre
   para que Arduino IDE lo reconozca correctamente.
5. Seleccionar **Herramientas → Placa → esp32 → ESP32 Dev Module** y el puerto
   del conversor CH340 de la placa conectada por USB. Mantener las opciones
   predeterminadas compatibles con el módulo.
6. Compilar con **Verificar** y cargar con **Subir**. Si Arduino IDE muestra
   `Connecting...` y no inicia la carga, mantener presionado **BOOT** hasta que
   comience la escritura y luego soltarlo.
7. Abrir el monitor serie a **115200 baudios**. Se admiten comandos sin salto de
   línea, con LF, con CR o con CRLF. Los comandos también admiten minúsculas.

Las librerías `WiFi`, `WiFiClientSecure` y `HTTPClient`, y FreeRTOS, vienen con
Arduino Core para ESP32. No se necesitan ArduinoJson ni credenciales de Firebase
Admin. El parser JSON de SSE utiliza **cJSON**, incluido en el core ESP32
(compilación verificada con **3.3.11**); no hay bibliotecas adicionales que
instalar en Arduino IDE. Con los valores de ejemplo, el firmware avisa que falta configurar Wi-Fi
y conserva el funcionamiento local.

`secrets.h` está ignorado por `.gitignore`; `secrets.h.example` permanece público.
Comprobar antes de un commit:

```bash
git check-ignore -v 01_firmware/cava_esp32/secrets.h
git ls-files -- 01_firmware/cava_esp32/secrets.h
```

El primer comando debe identificar la regla `secrets.h`; el segundo no debe
mostrar nada. Un `git add` normal omite el archivo. No usar `git add -f` sobre él.

## Hardware y escenarios

- ESP32 WROOM-32 de 30 pines, USB-C con CH340.
- `MODO_SIMULACION` permanece en `true`.
- GPIO 4 reservado para el futuro DHT22; no se configura ni se lee.
- GPIO 2 configurado como salida, inicialmente en `LOW`. Representa el
  climatizador mediante el LED integrado, si está conectado a ese pin.

| Comando | Acción | Temperatura | Humedad |
| --- | --- | --- | --- |
| `1` | Ambiente normal (predeterminado) | 16.0 °C | 70.0 % |
| `2` | Temperatura alta | 24.0 °C | 70.0 % |
| `3` | Humedad baja | 17.0 °C | 55.0 % |
| `9` | Error de sensor | `NAN` | `NAN` |
| `E` | Encender climatizador: GPIO 2 en `HIGH` | — | — |
| `A` | Apagar climatizador: GPIO 2 en `LOW` | — | — |
| `M` | Mostrar menú | — | — |

La selección del escenario se aplica inmediatamente y se confirma por serie.
La telemetría local continúa cada **2500 ms**. El actuador se controla con `E`
y `A`, sin depender del escenario ni de la conexión a Internet. Estos comandos
no cambian `extractor_solicitado` en Firebase: una nueva orden SSE, incluido el
estado inicial tras reconectar, vuelve a sincronizar la salida con Firebase.
Son controles locales de prueba: sí actualizan `extractor_confirmado` mediante
ACK, por lo que ambos booleanos pueden diferir hasta la siguiente orden remota.

## Wi-Fi, hora y TLS

La conexión Wi-Fi se inicia sin esperar dentro de un bucle. Si no conecta, se
reintenta cada **10000 ms** mediante `millis()`. Al perder una conexión se informa
`[WIFI] Conexion perdida` y se inicia otro intento. Al conectarse se muestra:

```text
[WIFI] Conectado correctamente
[WIFI] IP: <direccion asignada por la red>
```

La hora UTC se prepara con `configTime()` y los servidores `time.google.com`,
`pool.ntp.org` y `time.cloudflare.com`. SNTP trabaja en segundo plano; el programa
consulta `time()` sin esperar por la sincronización. Si falta una hora válida,
se reintenta configurar NTP cada **60000 ms** y se omiten los envíos HTTPS.
La red debe permitir DNS, NTP (UDP 123) y HTTPS (TCP 443).

`firebase_ca.h` contiene los certificados públicos **GTS Root R1 y GTS Root R4**,
extraídos del almacén de CA confiables de Ubuntu. `setCACert()` habilita la
verificación de la cadena del servidor; la conexión verifica también el nombre
del host y la vigencia del certificado. No se desactiva la verificación TLS.
Si Google cambia su cadena de confianza, actualizar las CA con certificados
verificados desde el [repositorio de Google Trust Services](https://pki.goog/repository/)
y volver a cargar el firmware. Las CA públicas no son contraseñas ni claves
privadas.

## Telemetría a Firebase mediante PATCH

La ruta utilizada para las lecturas ambientales es:

```text
https://unidad4-aiot-cava-default-rtdb.firebaseio.com/bodega/zona_crianza/ambiente.json
```

Cada **5000 ms**, un reloj independiente basado en `millis()` programa un PATCH
con `Content-Type: application/json` y este contenido para el escenario `1`:

```json
{
  "temperatura": 16.00,
  "humedad": 70.00,
  "timestamp": {
    ".sv": "timestamp"
  }
}
```

Firebase reemplaza el objeto `.sv` por la hora de su servidor en milisegundos.
La hora NTP del ESP32 se utiliza para TLS; no genera este timestamp.
El método PATCH actualiza esos campos sin reemplazar todo el nodo.
Ver la [documentación REST de Firebase](https://firebase.google.com/docs/database/rest/save-data).

Antes de programar un envío y nuevamente antes de construir el JSON se validan
temperatura y humedad con `isnan()`. En el escenario `9` aparece
`[ERROR] Lectura invalida del DHT22 simulado` y no se envían valores inválidos.
Una petición con una muestra válida ya iniciada puede terminar después de
seleccionar `9`. Los nuevos envíos se recuperan al seleccionar `1`, `2` o `3`.

HTTPS se ejecuta en una tarea FreeRTOS con una copia de la muestra. Desde el
PASO 6 esta misma tarea serializa PATCH y PUT, con prioridad para ACK cuando
está listo para enviar. El bucle principal mantiene los comandos serie, GPIO 2,
Wi-Fi y las lecturas locales.
La conexión TCP y la espera HTTP tienen límites de 3000 ms; el handshake TLS
tiene un límite de 4 segundos. Si un envío sigue en curso al vencer el próximo
intervalo, o hay un ACK listo, se omite ese turno: no se acumulan peticiones ni
se reenvían muestras antiguas. También se omiten turnos sin Wi-Fi o sin hora válida. El próximo
intento se realiza al vencer otro intervalo de 5000 ms.

## Comprobar en la placa y Firebase

1. Configurar `secrets.h`, compilar, cargar y abrir el monitor a 115200.
2. Verificar el encabezado, el menú y el escenario `1`. Cada 2500 ms debe verse:

   ```text
   [AMBIENTE] Temperatura: 16.00 C | Humedad: 70.00 %
   ```

3. Esperar la conexión Wi-Fi, la IP y `[NTP] Hora valida; verificacion TLS habilitada`.
4. Para esta práctica, los permisos temporales de desarrollo de Realtime
   Database deben permitir escribir en `/bodega/zona_crianza/ambiente`.
   El firmware no modifica reglas ni utiliza credenciales privadas de Admin.
5. Buscar los mensajes de cada solicitud:

   ```text
   [PATCH] Enviando telemetria...
   [PATCH] HTTP 200 - Datos enviados correctamente
   ```

6. En **Firebase Console → Realtime Database → Datos**, abrir
   `bodega/zona_crianza/ambiente`. Comprobar los valores y que `timestamp` sea
   un número que avance aproximadamente cada 5 segundos con la red disponible.
   Seleccionar `2` y `3` y comprobar también 24/70 y 17/55 respectivamente.
7. Seleccionar `9`: deben aparecer errores locales y cancelaciones de envío.
   Tras finalizar una posible petición válida en curso, el timestamp debe dejar
   de actualizarse. Volver a `1` y comprobar la recuperación.
8. Enviar `E`, `A` y `M`, también mientras se realizan solicitudes HTTPS.
   Comprobar los mensajes `ON`/`OFF`, el LED si existe y el menú.
9. Apagar temporalmente el punto de acceso Wi-Fi: comprobar el mensaje de pérdida,
   los reintentos y que los comandos locales respondan. Al restaurarlo, verificar
   una nueva IP y la recuperación de los envíos.

| Resultado | Comprobación |
| --- | --- |
| `HTTP 200` | PATCH aceptado; comprobar también los datos en la consola. |
| `HTTP 401` o `403` | Revisar permisos temporales de escritura y su vencimiento. |
| Otro código HTTP | Se imprime el código real; revisar ruta, disponibilidad y reglas. |
| Código de red negativo | Revisar Internet, DNS, señal Wi-Fi y tiempos de espera. |
| Mensaje `[TLS]` | Revisar hora NTP y CA; se muestra el código y detalle disponibles. |
| Esperando hora NTP | Verificar acceso a UDP 123 y a los servidores configurados. |

La compilación y las pruebas de lógica en una computadora no acreditan recepción
real en Firebase. La comprobación de extremo a extremo requiere cargar el firmware
configurado en el ESP32 y observar el HTTP exitoso y el nodo actualizado.

## PASO 5: órdenes reactivas mediante SSE

El ESP32 abre un GET HTTPS con `Accept: text/event-stream` hacia:

```text
https://unidad4-aiot-cava-default-rtdb.firebaseio.com/bodega/zona_crianza/control/extractor_solicitado.json
```

La conexión permanece abierta. Firebase transmite el estado inicial y luego los
cambios del nodo, según su [protocolo REST de streaming](https://firebase.google.com/docs/database/rest/retrieve-data#streaming_from_the_rest_api).
No se consulta periódicamente el booleano. Solo se hace otro GET al abrir o
recuperar el stream, o al seguir una redirección HTTP 307.

`firebase_sse.cpp` mantiene una única tarea y un cliente `WiFiClientSecure`
exclusivos. La tarea de escrituras conserva el intervalo PATCH de 5000 ms y
ahora atiende también los PUT. La apertura TLS y los reintentos de SSE no se
ejecutan en `loop()`.
Las órdenes pasan al bucle principal mediante una cola que conserva el último
booleano recibido; los avisos tienen una cola separada y acotada.

El estado recibido se interpreta con cJSON, no buscando palabras en el texto:

```text
event: put
data: {"path":"/","data":true}

```

Se admiten `put` y `patch` con `path` exactamente `/` y `data` de tipo booleano.
`false` apaga GPIO 2 y `true` lo enciende. Se rechazan `null`, números, cadenas,
objetos, rutas distintas, campos duplicados y JSON inválido; se informa el error
y se conserva la salida actual. El estado inicial recibido al conectar también
se aplica. Si coincide con el estado local, se confirma por serie sin volver a
escribir innecesariamente el pin; desde el PASO 6 también registra un ACK nuevo.

El parser acumula líneas hasta la línea vacía que termina un evento. Admite
LF, CRLF, CR, varias líneas `data:` y fragmentación en cualquier byte. También
decodifica `Transfer-Encoding: chunked`, aunque un evento ocupe varios chunks.
Los comentarios y `keep-alive` no accionan GPIO 2. Los límites son:

- Línea SSE: 511 bytes; datos acumulados de un evento: 1023 bytes.
- Nombre de evento: 23 bytes; profundidad JSON máxima: 8 niveles.
- Cabeceras HTTP: 4096 bytes en total, con línea de hasta 1023 bytes.
- URL: 767 bytes; máximo de 3 redirecciones.

Un evento excedido se descarta completo y el parser se recupera en la siguiente
línea vacía. Las redirecciones respetan `Location` absoluta o relativa y admiten
únicamente HTTPS en puerto 443. Cada destino vuelve a validar CA, hostname y
vigencia usando la misma configuración segura del PASO 4. No se imprimen URLs
redirigidas, parámetros de autorización ni el contenido de eventos de error.

## Probar SSE desde Arduino IDE y Firebase

1. Mantener las credenciales locales de `secrets.h`, seleccionar **ESP32 Dev
   Module**, verificar y subir el sketch. Los nuevos `.cpp` y `.h` deben estar
   junto a `cava_esp32.ino`; Arduino IDE los compila automáticamente.
2. Abrir el monitor serie a **115200 baudios**. Esperar Wi-Fi, hora NTP y:

   ```text
   [SSE] Conectando con Firebase...
   [SSE] HTTP 200 - Streaming establecido
   ```

   Puede aparecer antes un HTTP 307. Debe seguirse hasta establecer el stream.
   Los permisos temporales de desarrollo deben permitir **leer** el nodo de
   control, además de escribir el nodo ambiental del PASO 4 y
   `extractor_confirmado` para el PASO 6.
3. En **Firebase Console → Realtime Database → Datos**, abrir
   `bodega/zona_crianza/control/extractor_solicitado`. Si falta, crear esa clave
   como **booleano** con valor `false`. No escribir la cadena `"false"`.
4. Cambiar el booleano a `true`. Observar:

   ```text
   [SSE] Orden recibida: ENCENDER
   [ACTUADOR] GPIO 2 = ON
   ```

   Cambiarlo a `false` y comprobar `APAGAR`, `OFF` y el LED integrado si la placa
   lo conecta a GPIO 2. En su defecto, comprobar eléctricamente el nivel del pin.
5. Dejar `true` en Firebase y reiniciar el ESP32: el estado inicial recibido
   debe volver a encenderlo. Repetir con `false`. Repetir un estado igual al
   local no debe producir conmutaciones adicionales.
6. Durante estas pruebas deben continuar los `[AMBIENTE]` cada 2500 ms y los
   PATCH con HTTP 200 cada 5000 ms aproximadamente. Comprobar también el avance
   de `ambiente/timestamp` y probar `1`, `2`, `3`, `9`, `E`, `A` y `M`.
   El escenario `9` suspende los envíos ambientales inválidos, pero SSE y GPIO 2
   deben continuar operativos.
7. Para comprobar que no hay polling, dejar el nodo sin cambios: el stream sano
   debe permanecer abierto, sin nuevos mensajes `Conectando` ni GET repetidos.
   Cambiar el booleano entre dos publicaciones ambientales: la orden no debe
   esperar al próximo PATCH. En el código, el GET está únicamente en la apertura
   del stream de `firebase_sse.cpp`; `loop()` no consulta el nodo remoto.

## Desconexiones y recursos de SSE

- Si se pierde Wi-Fi o una hora válida, la tarea cierra su cliente SSE y conserva
  el estado actual del actuador. Los comandos locales siguen disponibles.
- Un cierre del servidor, un cuerpo HTTP inválido o 90 segundos sin actividad
  cierran el stream y programan otro intento mediante `millis()`.
- El reintento normal comienza a los 5 segundos. Los fallos al abrir la conexión
  aumentan progresivamente la espera hasta 60 segundos.
- `cancel`, `auth_revoked` y HTTP 401/403 usan una espera de **60 segundos**.
  Revisar permisos/autorización; no hay reconexiones agresivas ni polling alternativo.
- Al recuperar la conexión, Firebase entrega otra vez el estado inicial, que
  vuelve a sincronizar GPIO 2. No se reconstruye un historial de órdenes perdidas.
- Se liberan los recursos TLS al cerrar. No se crean tareas nuevas por evento
  ni por reconexión. La tarea SSE reserva 12288 bytes de pila; la tarea de
  escrituras PATCH/PUT mantiene sus 8192 bytes. Las colas y los buffers tienen
  límites fijos.

Para probar la recuperación, apagar y restaurar el punto de acceso Wi-Fi.
Comprobar los mensajes de pérdida/reintento, un nuevo streaming HTTP 200, la
sincronización inicial y la recuperación de los PATCH. También puede probarse
temporalmente el permiso de lectura del nodo para observar `cancel` o un error
HTTP de autorización y verificar la espera de 60 segundos.

Al establecer SSE se informa `[SSE] Heap libre: ... | Minimo: ...`. Esas cifras
deben revisarse en el ESP32 real, también después de varios PATCH y reconexiones:
las dos sesiones TLS y las pilas de tareas consumen memoria dinámica que no
aparece en la cifra de RAM estática del compilador. Este consumo y la estabilidad
física no se pueden acreditar con pruebas en PC.

Las pruebas de protocolo están en `tests/test_sse.cpp`: cubren eventos
fragmentados, `put`/`patch`, JSON inválido, límites, chunked y redirecciones.
No requieren credenciales ni abren conexiones.

## PASO 6: Acknowledge del actuador mediante PUT

Acknowledge (ACK) es la confirmación de que el firmware aplicó una orden al GPIO.
Refleja el estado aplicado por el programa; no mide eléctricamente el extractor.

| Nodo bajo `/bodega/zona_crianza` | Significado | Operación del ESP32 |
| --- | --- | --- |
| `control/extractor_solicitado` | Estado pedido desde Firebase | Recibe booleanos por SSE; no escribe este nodo. |
| `extractor_confirmado` | Último estado aplicado que Firebase aceptó | Escribe un booleano mediante HTTPS PUT. |
| `ambiente` | Temperatura, humedad y timestamp | Conserva HTTPS PATCH cada 5000 ms, sujeto a disponibilidad. |

El endpoint de confirmación existente es:

```text
https://unidad4-aiot-cava-default-rtdb.firebaseio.com/bodega/zona_crianza/extractor_confirmado.json
```

Se envía `Content-Type: application/json`. El cuerpo contiene únicamente `true`
o `false`, sin comillas JSON ni un objeto envolvente. Firebase permite guardar
booleanos con PUT en una ruta concreta; ver su
[documentación de escritura REST](https://firebase.google.com/docs/database/rest/save-data#writing_data_with_put).
No se cambia la estructura de la base ni se escriben nodos padres.

El orden de ejecución es: validar la orden SSE como booleano, aplicar GPIO 2,
actualizar el estado local, registrar la confirmación pendiente, programar PUT
y verificar su resultado. El pin cambia antes de cualquier operación HTTPS y
el control local funciona incluso sin Internet. Cuando la orden coincide con
la salida actual no se repite la conmutación, pero sí se registra la confirmación.

`firebase_ack.h/.cpp` conserva el último estado aplicado, una versión local de
64 bits y el temporizador de reintento. El `.ino` coordina GPIO, las colas y una
sola tarea HTTPS de escrituras; reutiliza CA y límites de tiempo del PATCH.
Las versiones viajan solo entre tareas, no se agregan a Firebase. Si se aplica
otra orden durante un PUT, su respuesta solo puede resolver la versión enviada:
el objetivo nuevo permanece pendiente. Puede observarse transitoriamente el
valor anterior en Firebase mientras finaliza la petición; el siguiente PUT
publica el último estado aplicado. No se acumula un historial de estados viejos.

SSE conserva su propio cliente TLS y su tarea, con diagnósticos de red/memoria. La tarea de
escrituras crea un cliente distinto y lo cierra al terminar cada PATCH o PUT;
jamás usa ni cierra el cliente SSE. Hay como máximo dos conexiones del firmware:
el stream y una escritura. Si ya hay un PATCH en curso se espera su resultado
sin bloquear `loop()`; al quedar libre la tarea se atiende primero el ACK listo.
Mientras un ACK espera su intervalo de reintento pueden continuar los PATCH.
Los turnos PATCH ocupados se omiten, como en el PASO 4: no se garantiza un PATCH
exitoso cada 5 segundos durante fallos o muchas órdenes seguidas.

Solo **HTTP 200** resuelve satisfactoriamente una confirmación. Ante un error,
el GPIO conserva su estado y el ACK permanece en RAM:

- Error de red/TLS, HTTP inesperado o imposibilidad de iniciar HTTPS: reintento
  a los **5000 ms** de procesar el fallo, si hay Wi-Fi y hora válida.
- HTTP **401/403**: muestra el código y pide revisar reglas de seguridad o
  autenticación en `extractor_confirmado`; reintenta a los **60000 ms**.
- Una nueva orden aplicada reemplaza el objetivo y permite enviar ese nuevo
  estado en cuanto la tarea esté libre, sin esperar el reintento anterior.

Las esperas se calculan con `millis()` y resta sin signo. No hay `delay()` ni
solicitudes HTTPS dentro de `loop()`. Se conservan los límites TCP/HTTP de
3000 ms y TLS de 4 segundos en la tarea de escrituras. Las colas tienen un
elemento; la tarea espera suspendida cuando no hay trabajo.

En el arranque GPIO 2 comienza en `LOW`. El primer booleano SSE registra un ACK
incluso si es `false`, para corregir un confirmado remoto antiguo. Cada reconexión
SSE repite esa sincronización inicial. Si `loop()` detecta pérdida de Wi-Fi,
también deja pendiente el estado aplicado para publicarlo al volver la red.
Una orden inicial posterior puede sustituirlo. Un reinicio no conserva pendientes
en Flash: vuelve al arranque seguro y a la sincronización del stream.

## Probar ACK en Arduino IDE y Firebase

1. Mantener `secrets.h` sin cambios. Abrir `cava_esp32/cava_esp32.ino` con todos
   sus `.cpp` y `.h`, incluido `firebase_ack`. Seleccionar **ESP32 Dev Module**,
   Core **3.3.11**, el puerto CH340, **Verificar** y **Subir**. Abrir el monitor
   serie a **115200 baudios** y esperar Wi-Fi, NTP y streaming HTTP 200.
2. En Firebase Console → Realtime Database → Datos, abrir los dos nodos del
   actuador de la tabla anterior. Los permisos actuales deben permitir leer la
   orden y escribir `extractor_confirmado`. El firmware no cambia reglas ni autenticación.
3. Cambiar `control/extractor_solicitado` de `false` a **booleano `true`**.
   Comprobar el LED azul encendido y esta secuencia, que puede intercalarse con
   otros mensajes:

   ```text
   [SSE] Orden recibida: ENCENDER
   [ACTUADOR] GPIO 2 = ON
   [ACK] Enviando confirmacion: true
   [ACK] HTTP 200 - Estado confirmado en Firebase
   ```

   Verificar `extractor_confirmado = true` como booleano, sin comillas.
4. Cambiar la orden a **booleano `false`**. Comprobar el LED apagado:

   ```text
   [SSE] Orden recibida: APAGAR
   [ACTUADOR] GPIO 2 = OFF
   [ACK] Enviando confirmacion: false
   [ACK] HTTP 200 - Estado confirmado en Firebase
   ```

   Verificar `extractor_confirmado = false`. Tras cada éxito también se muestran
   el valor enviado y el heap libre/mínimo.
5. Probar sincronización inicial: con la placa apagada, dejar solicitado `false`
   y confirmado `true`; encenderla. Debe permanecer apagado el LED y corregirse
   confirmado a `false` con PUT. Repetir con solicitado `true` y confirmado
   `false`: el LED debe arrancar apagado y encenderse al recibir SSE.
6. Probar `E` y `A`: deben aplicar GPIO y confirmar su estado. Son pruebas locales;
   no cambian `extractor_solicitado`. Para retomar el control remoto, cambiar ese
   booleano o reconectar SSE. Repetir con escenario `9`: se omiten PATCH por
   `NAN`, pero órdenes, consola y ACK siguen operativos.
7. Apagar temporalmente el punto de acceso Wi-Fi, enviar `E`/`A` y restaurarlo.
   El control local debe responder sin red. Tras recuperar Wi-Fi y SSE, verificar
   que confirmado converja al último estado aplicado; la nueva orden inicial
   remota puede reemplazar la prueba local. El fallo no debe conmutar el GPIO.
8. Si se recibe HTTP 401/403, comprobar el error `[ACK]`, la espera de 60 s y que
   siga respondiendo el LED. Conservar las reglas y credenciales actuales durante
   este diagnóstico. Una respuesta HTTP acredita que se alcanzó Firebase; es un
   caso distinto del fallo de conexión `-1`.
9. Alternar la orden mientras hay una escritura en curso. Al estabilizarla,
   confirmar que LED y `extractor_confirmado` coincidan con el último estado
   aplicado. Comprobar que los mensajes `[PATCH] HTTP 200` y `ambiente/timestamp`
   continúen actualizándose con lecturas válidas. Un PUT no debe provocar un
   nuevo `[SSE] Conectando...` en un stream sano.

`[ACK]` identifica PUT del actuador; `[PATCH]` identifica telemetría. `[SSE]`
identifica recepción de órdenes. El HTTP 200 del stream o de un PATCH no acredita
un ACK: deben verse el **HTTP 200 de `[ACK]`** y el booleano actualizado.
El valor confirmado puede quedar antiguo durante una desconexión o un PUT fallido.

## Verificación de compilación y pruebas del PASO 6

Se compiló y enlazó el sketch con sus cuatro módulos `.cpp`, Arduino Core ESP32
**3.3.11** y el compilador Xtensa instalado, sin advertencias en el código del
proyecto. También se generó la imagen ESP32 con esptool, sin cargarla en la placa.

| Recurso | Uso medido | Referencia ESP32 Dev Module |
| --- | --- | --- |
| Flash según las secciones de la receta Arduino | 1067400 bytes (81,4 %) | Partición de aplicación predeterminada: 1310720 bytes |
| RAM estática | 49064 bytes (15,0 %) | Máximo informado por la placa: 327680 bytes |
| Imagen `.bin` generada | 1067552 bytes | Incluye encabezados y alineación de la imagen |

La RAM estática no incluye el heap de Wi-Fi, TLS, las colas ni las pilas de tareas.
La comprobación de esos picos requiere observar el heap mínimo en la placa real.
Pasaron pruebas en PC de protocolo SSE, redirecciones, reconexión temporizada,
versiones ACK, errores HTTP y conservación de las funciones de los PASOS 3 a 5.
La integración con red simulada mantuvo un solo GET SSE durante cuatro PUT y
dos PATCH en 12 segundos; comprobó booleanos reales en el cuerpo, prioridad ACK,
respuestas antiguas, comandos locales y recuperación. No se contactó Firebase
para estas pruebas ni se cargó el firmware en la placa.

El PASO 5 ya fue comprobado físicamente por el usuario. La compilación y estas
pruebas **no acreditan todavía el funcionamiento físico del ACK del PASO 6**.

La prueba de versiones y reintentos es reproducible sin Arduino ni credenciales,
desde `01_firmware`:

```bash
g++ -std=c++17 -Wall -Wextra -Werror -Icava_esp32 tests/test_ack.cpp cava_esp32/firebase_ack.cpp -o /tmp/cava-test-ack
/tmp/cava-test-ack
```

Comprueba sincronización aun con un estado igual, órdenes sucesivas durante una
confirmación, errores de red/HTTP, espera de 5 s o 60 s, reemplazo del objetivo
y desbordamiento de `millis()`. Solo HTTP 200 elimina el pendiente actual.

## Diagnóstico del fallo HTTPS observado después del PASO 6

La comparación se hizo contra el PASO 5 (`743348f`); el PASO 6 estaba en cambios
locales sin commit y se conservó. No se identificó una causa raíz demostrable
con los mensajes disponibles. Esta versión agrega instrumentación para medirla
en el ESP32 físico; **no acredita que el problema esté resuelto**.

La revisión del firmware y del código instalado del Core **3.3.11** encontró:

- El stream SSE usa una conexión TLS persistente exclusiva. PATCH y ACK usan
  una sola tarea de escrituras y un cliente nuevo por solicitud; no se crean
  tres conexiones simultáneas por agregar ACK. El máximo sigue siendo dos.
- El orden de declaración ya era correcto en el PASO 5 y en el PASO 6:
  `WiFiClientSecure cliente` antes de `HTTPClient http`. C++ destruye primero
  `http`, mientras `cliente` sigue vivo. No se encontró una referencia a un
  cliente destruido ni un objeto HTTPClient global reutilizado.
- En este core, `end()` puede conservar el puntero al cliente si la conexión
  ya falló. Por eso se conserva ese orden y se delimita explícitamente el
  ámbito de ambos objetos. Se ejecutan `http.end()` y `cliente.stop()` incluso
  si falla `begin()`, y se mide otra vez **después de ambos destructores**.
  Es una mejora de limpieza/diagnóstico, no una causa demostrada del fallo.
- El mismo cierre de PATCH y la misma conexión SSE existían antes de ACK.
  El cambio de estado ACK usa almacenamiento fijo, colas acotadas y copias;
  no agrega un cliente TLS ni una tarea por orden.
- `HTTPClient` convierte un fallo de `connect()` en `-1` y lo describe como
  `connection refused`. El `-1` del cliente seguro también puede originarse
  en socket, conexión TCP o timeout, antes de verificar certificados. Esos
  textos **no prueban un rechazo TCP del servidor ni un fallo de la CA**.
  El timeout del handshake TLS de 4 s también devuelve `-1` en ese core;
  se informa la duración para diferenciarlo de otros fallos sin asumir la causa.
  Ver [HTTPClient 3.3.11](https://github.com/espressif/arduino-esp32/blob/3.3.11/libraries/HTTPClient/src/HTTPClient.cpp)
  y [ssl_client 3.3.11](https://github.com/espressif/arduino-esp32/blob/3.3.11/libraries/NetworkClientSecure/src/ssl_client.cpp).

SSE sigue redirecciones **307** HTTPS con validación de CA/hostname en cada salto,
como requiere el [protocolo de Firebase](https://firebase.google.com/docs/database/rest/retrieve-data#section-rest-streaming).
Las escrituras conservan el comportamiento anterior sin redirecciones automáticas:
ahora se informa el código 3xx y si hay `Location`, sin imprimir su contenido ni
convertir PATCH/PUT en GET. Una redirección produce una respuesta HTTP positiva,
no explica por sí sola el `-1`. Los registros DNS muestran el host inicial de
las escrituras y el host de cada salto SSE, que pueden ser distintos.

### Registros agregados

`diagnostico_red.h/.cpp` toma mediciones con las API del Core/ESP-IDF, sin
reservar buffers grandes ni crear tareas de diagnóstico. Los siguientes son
**formatos de salida**, no valores medidos en una placa:

```text
[DIAG] SSE=activo ACK=activo PATCH=activo | TLS con CA
[PATCH] [RED] wifi=3 IP=... GW=... RSSI=... dBm DNS=.../...
[PATCH] [NTP] UTC=... valida=si ultima_sync_epoch=...
[PATCH] [DNS] host=... resultado=1 IP=... tiempo=... ms
[PATCH] [HEAP] t=... antes-objetos | libre=... minimo=... mayor=... pila_min=... bytes
[PATCH] [HEAP] t=... antes-TLS | libre=... minimo=... mayor=... pila_min=... bytes
[PATCH] [HTTPS] codigo=... tiempo=... ms
[PATCH] [HEAP] t=... tras-peticion | libre=... minimo=... mayor=... pila_min=... bytes
[PATCH] [HEAP] t=... tras-cierre | libre=... minimo=... mayor=... pila_min=... bytes
[PATCH] [HEAP] t=... tras-destruccion | libre=... minimo=... mayor=... pila_min=... bytes
```

ACK emite las mismas fases con `[ACK]`. SSE informa `antes-TLS`, `tras-TLS`,
`stream-activo`, `antes-cierre` y `tras-cierre`, además de duración TLS, DNS,
red y hora. El stream sano queda abierto; no se lo cierra para enviar escrituras.
Las desconexiones STA informan también el código de motivo.

- `libre`, `minimo` y `mayor` miden RAM **interna direccionable por byte**
  (`MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT`), relevante para las asignaciones TLS.
  No suman PSRAM ni bloques utilizables solo con accesos de 32 bits. El registro
  previo de ACK exitoso que usa `ESP.getFreeHeap()` cuenta memoria interna con
  otro filtro; para comparar fases usar los nuevos registros `[HEAP]`.
- `minimo` es histórico desde el arranque: **no tiene que subir al cerrar TLS**.
  `libre` y `mayor` deberían estabilizarse después de liberar cada escritura,
  comparando con SSE en el mismo estado. Una caída sostenida requiere investigar
  una fuga; mucho heap libre con un bloque mayor decreciente sugiere fragmentación.
  Ninguno de esos síntomas está demostrado aún sin registros de la placa.
- `pila_min` es el mínimo de pila libre de la tarea que emite el registro, en
  bytes según ESP-IDF. Permite detectar falta de margen sin aumentar las pilas
  a ciegas y consumir más heap.
- `wifi=3` corresponde a `WL_CONNECTED`; comprobar también IP, gateway y RSSI.
  Estar asociado al AP no garantiza acceso a Internet. DNS `resultado=1`
  acredita una resolución en ese momento, no una conexión TCP/TLS exitosa.
  La consulta adicional se hace solo en las tareas de red, nunca en `loop()`;
  el cliente sigue conectando por hostname y puede usar la caché del resolvedor.
- `valida=si` conserva el umbral de fecha para habilitar TLS; comprobar UTC
  real. `ultima_sync_epoch=0` significa que el callback no observó todavía una
  respuesta SNTP en este arranque. Un valor distinto de cero acredita que SNTP
  notificó una sincronización; puede ser anterior a una reconexión Wi-Fi.

Los diagnósticos agregan salida serie, una consulta DNS por intento y un pequeño
costo de memoria/tiempo. Las mediciones antes/después no capturan todos los picos
internos del handshake; el mínimo histórico ayuda a verlos. No se cambian los
timeouts TCP/HTTP de 3000 ms ni el límite TLS de 4 s sin evidencia de la placa.

### Aislar SSE y ACK sin cambiar secrets.h ni Firebase

Las opciones están en `cava_esp32/diagnostico_red.h` y valen **0 por defecto**.
También admiten `-D` para no editar archivos al alternar pruebas. Solo se permite
desactivar un componente por vez:

| Prueba | `CAVA_DIAG_SIN_SSE` | `CAVA_DIAG_SIN_ACK` | Funciones activas |
| --- | --- | --- | --- |
| Versión completa | 0 | 0 | SSE + PATCH + ACK |
| Aislar SSE | 1 | 0 | PATCH + ACK; órdenes locales E/A |
| Aislar ACK | 0 | 1 | SSE + PATCH; GPIO responde sin PUT |

En Arduino IDE, cambiar solo el valor predeterminado de la opción correspondiente,
verificar y cargar. En la prueba sin SSE, enviar **E y A** por el monitor serie
para generar PUT: no llegan órdenes desde Firebase porque no se crea la tarea
del stream. El PATCH conserva su turno cada 5000 ms en las tres variantes.

Con `arduino-cli` disponible en PATH, desde la raíz del proyecto:

```bash
# Versión completa, ambas opciones en 0 en el archivo.
arduino-cli compile --fqbn esp32:esp32:esp32 --warnings all --build-path /tmp/cava-build-completo 01_firmware/cava_esp32

# Sin SSE, con PATCH y ACK.
arduino-cli compile --fqbn esp32:esp32:esp32 --warnings all --build-path /tmp/cava-build-sin-sse --build-property compiler.cpp.extra_flags=-DCAVA_DIAG_SIN_SSE=1 01_firmware/cava_esp32

# Sin ACK, con SSE y PATCH.
arduino-cli compile --fqbn esp32:esp32:esp32 --warnings all --build-path /tmp/cava-build-sin-ack --build-property compiler.cpp.extra_flags=-DCAVA_DIAG_SIN_ACK=1 01_firmware/cava_esp32
```

Estas órdenes compilan; la carga se realiza después por el puerto de la placa.
No se efectuó ninguna carga durante esta revisión. Se usó el Core 3.3.11 local.
La compilación completa deja 278616 bytes del máximo de RAM estática informado
por Arduino; **eso no es el heap libre real durante Wi-Fi/TLS**.

Las tres compilaciones terminaron sin advertencias con `--warnings all`:

| Variante | Flash (bytes) | RAM estática (bytes) |
| --- | --- | --- |
| Completa | 1067400 | 49064 |
| Sin SSE | 1048376 | 49008 |
| Sin ACK | 1067220 | 49064 |

También pasaron las pruebas existentes `tests/test_ack.cpp` y
`tests/test_sse.cpp` en PC. Estas verifican estados/protocolo; no reproducen
los handshakes concurrentes ni el heap del ESP32.

Para cada variante, reiniciar la placa y registrar desde el arranque al menos
2 minutos con la misma red y escenario `1`. Mantener períodos sin cambiar
órdenes para observar varios PATCH entre PUT. Verificar los HTTP 200 de cada
operación y los nodos de Firebase, además del LED. Probar después `9` para
`isnan()` y recuperación de Wi-Fi. Comparar siempre `tras-destruccion` con el
stream en un estado equivalente.

- Si solo funciona sin SSE, investigar recursos de la conexión persistente,
  margen TLS y destino redirigido. Esto no prueba que se comparta un cliente.
- Si solo funciona sin ACK, comparar memoria y tiempos al añadir escrituras,
  frecuencia de órdenes y códigos HTTP específicos del PUT.
- Si fallan ambas variantes, revisar primero DNS, IP/gateway, hora y errores
  de socket antes de atribuir el problema a la coexistencia SSE/ACK.
- Si ambas variantes funcionan y la completa falla, el problema depende de
  su coexistencia o temporización; revisar mínimos y mayor bloque en ese caso.

Si persiste `-1` sin detalle, seleccionar **Herramientas → Core Debug Level → Info**
y recompilar/cargar (o usar `--fqbn esp32:esp32:esp32:DebugLevel=info`). Este nivel
del core permite distinguir el timeout TCP de 3000 ms y errores de socket que
el código genérico no discrimina. Conservar también los logs desde antes de
la apertura SSE; un stream sano puede seguir conectado mientras falla otra
conexión a un host diferente.

Al terminar, restaurar **ambas opciones a 0**, recompilar y cargar la versión
completa. El primer registro debe decir `SSE=activo ACK=activo PATCH=activo`.
La confirmación final exige comprobar simultáneamente SSE real, GPIO 2,
PATCH periódicos y PUT en el ESP32 físico con validación TLS activa.
