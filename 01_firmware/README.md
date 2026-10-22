# Firmware ESP32 — PASO 3

Abrir `cava_esp32/cava_esp32.ino` en Arduino IDE. La carpeta y el sketch
comparten el nombre `cava_esp32` para que el IDE lo reconozca correctamente.

- Hardware: ESP32 WROOM-32 de 30 pines, USB-C con conversor CH340.
- Core: Arduino para ESP32. Seleccionar la placa compatible con el módulo
  (por ejemplo, **ESP32 Dev Module**) y su puerto serie.
- Monitor serie: **115200 baudios**. Los comandos funcionan sin salto de línea,
  con nueva línea (LF) o con retorno de carro y nueva línea (CRLF).
- `MODO_SIMULACION` está en `true`. Los datos se generan dentro del ESP32;
  no se necesita conectar un DHT22 ni instalar sus librerías.
- GPIO 4 queda reservado para el futuro DHT22 físico y no se configura.
- GPIO 2 se configura como salida y arranca en `LOW`. Representa el
  climatizador mediante el LED integrado, si la placa lo conecta a ese pin.

| Comando | Acción | Temperatura | Humedad |
| --- | --- | --- | --- |
| `1` | Ambiente normal (predeterminado) | 16.0 °C | 70.0 % |
| `2` | Temperatura alta | 24.0 °C | 70.0 % |
| `3` | Humedad baja | 17.0 °C | 55.0 % |
| `9` | Error de sensor | `NAN` | `NAN` |
| `E` | Encender climatizador: GPIO 2 en `HIGH` | — | — |
| `A` | Apagar climatizador: GPIO 2 en `LOW` | — | — |
| `M` | Mostrar menú | — | — |

Los comandos se aplican sin reiniciar la placa y confirman la acción por serie.
La selección del escenario es inmediata; su lectura se informa en el próximo
intervalo de 2500 ms. La temporización usa `millis()` y resta de tiempos
`unsigned long`. El control del actuador es manual en esta etapa.

Antes de mostrar la telemetría se validan temperatura y humedad con `isnan()`.
El escenario `9` muestra `[ERROR] Lectura invalida del DHT22 simulado` en cada
intervalo, sin publicar los valores inválidos. Para recuperarse, seleccionar
`1`, `2` o `3`.

Esta etapa solo implementa simulación, consola serie y control local de GPIO 2.
La lectura del sensor físico y la conectividad quedan para etapas posteriores.

## Comprobación en la placa

1. Compilar y cargar el sketch con Arduino IDE; abrir el monitor a 115200.
2. Verificar el encabezado, el menú y la confirmación del escenario `1`.
3. Observar cada 2500 ms:
   `[AMBIENTE] Temperatura: 16.00 C | Humedad: 70.00 %`.
4. Enviar `2`, `3` y `9`; comprobar sus confirmaciones y la siguiente lectura.
   En `9` debe aparecer el error, sin una línea de telemetría ambiental.
5. Enviar `1` y verificar la recuperación de la lectura normal.
6. Enviar `E` y `A`; verificar los mensajes `ON`/`OFF` y el LED, si existe.
7. Repetir con y sin salto de línea; enviar `M` para volver a mostrar el menú.
