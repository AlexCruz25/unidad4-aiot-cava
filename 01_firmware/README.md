# Firmware ESP32 — PASOS 3, 4 y 5

El ESP32 físico simula un DHT22, mantiene el control manual del climatizador y
publica las lecturas válidas en Firebase Realtime Database mediante HTTPS PATCH.
Además, recibe órdenes reactivas por SSE desde una conexión HTTPS persistente
independiente y sincroniza GPIO 2 con `extractor_solicitado`.
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

## Envíos a Firebase

La ruta utilizada es exclusivamente:

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

HTTPS se ejecuta en una tarea FreeRTOS con una copia de la muestra. El bucle
principal mantiene los comandos serie, GPIO 2, Wi-Fi y las lecturas locales.
La conexión TCP y la espera HTTP tienen límites de 3000 ms; el handshake TLS
tiene un límite de 4 segundos. Si un envío sigue en curso al vencer el próximo
intervalo, se omite ese turno: no se acumulan peticiones ni se reenvían muestras
antiguas. También se omiten turnos sin Wi-Fi o sin hora válida. El próximo
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
   [FIREBASE] Enviando telemetria...
   [FIREBASE] HTTP 200 - Datos enviados correctamente
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
exclusivos. El cliente PATCH existente conserva su tarea y su intervalo de
5000 ms. La apertura TLS y los reintentos de SSE no se ejecutan en `loop()`.
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
escribir innecesariamente el pin.

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
   control, además de escribir el nodo ambiental del PASO 4.
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
  ni por reconexión. La tarea SSE reserva 12288 bytes de pila; la tarea PATCH
  existente mantiene sus 8192 bytes. Las colas y los buffers tienen límites fijos.

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
No requieren credenciales ni abren conexiones. La confirmación remota mediante
`extractor_confirmado` y HTTPS PUT corresponde al **PASO 6** y no se implementa aquí.

## Verificación de compilación del PASO 5

Se compiló y enlazó el sketch con sus dos módulos SSE, Arduino Core ESP32
**3.3.11** y el compilador Xtensa instalado, sin advertencias en el código del
proyecto. También se generó la imagen ESP32 con esptool, sin cargarla en la placa.

| Recurso | Uso medido | Referencia ESP32 Dev Module |
| --- | --- | --- |
| Flash según las secciones de la receta Arduino | 1048352 bytes (80,0 %) | Partición de aplicación predeterminada: 1310720 bytes |
| RAM estática | 48592 bytes (14,8 %) | Máximo informado por la placa: 327680 bytes |
| Imagen `.bin` generada | 1048496 bytes | Incluye encabezados y alineación de la imagen |

La RAM estática no incluye el heap de Wi-Fi, TLS, las colas ni las pilas de tareas.
La comprobación de esos picos requiere observar el heap mínimo en la placa real.
Pasaron pruebas en PC de protocolo, redirecciones, reconexión temporizada y
conservación de las funciones de los PASOS 3 y 4, con red simulada. Esto no acredita
que el PASO 5 ya haya recibido órdenes desde Firebase en el ESP32 físico.
