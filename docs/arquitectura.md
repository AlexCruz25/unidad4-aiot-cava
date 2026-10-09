# Arquitectura del sistema AIoT

Este documento describe la arquitectura inicial prevista para el sistema de control microclimático de una cava de crianza en barricas. Corresponde al Trabajo Práctico Integrador de la Unidad 4: Arquitectura AIoT y Sistemas Ciberfísicos.

El sistema se organizará como un sistema ciberfísico distribuido de lazo cerrado. Firebase Realtime Database será el punto de intercambio entre el dispositivo físico, el supervisor AIoT y el dashboard web. Los flujos descritos a continuación se implementarán en etapas posteriores.

## Flujo de medición y visualización

```text
DHT22
  ↓
ESP32
  ↓
Firebase Realtime Database
  ↓
Dashboard Web
```

El DHT22 medirá la temperatura y la humedad relativa de la cava. El ESP32 leerá esas mediciones y las enviará a Firebase Realtime Database. El dashboard web recibirá las actualizaciones mediante Firebase onValue y mostrará el estado ambiental.

## Flujo de supervisión, actuación y confirmación

```text
Firebase
  ↓
Supervisor AIoT con FastAPI
  ↓
Gemini
  ↓
Firebase
  ↓
ESP32
  ↓
Actuador GPIO 2
  ↓
Acknowledge
  ↓
Firebase y Dashboard
```

El supervisor AIoT, desarrollado en Python con FastAPI, consultará las mediciones almacenadas en Firebase y enviará el contexto ambiental a Gemini para su análisis. El supervisor procesará la respuesta y registrará la orden de control en Firebase.

El ESP32 recibirá la orden y controlará el actuador asociado al GPIO 2. Después de aplicar la orden, el ESP32 generará una confirmación (acknowledge) y la registrará en Firebase. El dashboard visualizará esa confirmación para permitir el seguimiento de la orden.

La confirmación indicará que el ESP32 aplicó la orden; las mediciones posteriores del DHT22 permitirán observar su efecto sobre el microclima y continuar el ciclo de control.
