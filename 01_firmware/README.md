# Firmware ESP32 — PASOS 3 y 4

El ESP32 físico simula un DHT22, mantiene el control manual del climatizador y
publica las lecturas válidas en Firebase Realtime Database mediante HTTPS PATCH.
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
Admin. Con los valores de ejemplo, el firmware avisa que falta configurar Wi-Fi
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
y `A`, sin depender del escenario ni de la conexión a Internet.

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
Este paso mantiene el actuador manual; la recepción de órdenes y su confirmación
remota quedan para etapas posteriores.
