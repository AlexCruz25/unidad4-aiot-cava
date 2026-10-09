# Sistema AIoT para Cava de Crianza en Barricas

Proyecto correspondiente al **Trabajo Práctico Integrador de la Unidad 4: Arquitectura AIoT y Sistemas Ciberfísicos**.

El proyecto implementará un sistema ciberfísico distribuido de lazo cerrado para controlar el microclima de una cava de crianza en barricas. Integrará la medición de temperatura y humedad relativa, el almacenamiento y la visualización de datos, la supervisión con inteligencia artificial y el envío de órdenes a un actuador.

El lazo se cerrará mediante una confirmación del ESP32 (acknowledge), que permitirá registrar la ejecución de las órdenes y mostrar su estado en el dashboard web.

Actualmente, el proyecto cuenta con su estructura inicial, documentación y archivos de configuración de ejemplo. La lógica funcional se desarrollará en etapas posteriores.

## Tecnologías

- ESP32 DevKit V1
- DHT22
- Arduino / C++
- Firebase Realtime Database
- HTML5
- JavaScript Vanilla
- FastAPI
- Python
- Google Gemini API
- Server-Sent Events
- Firebase onValue

## Estructura del proyecto

- **01_firmware:** contendrá el firmware del ESP32 para leer el DHT22, comunicarse con Firebase, controlar el actuador y confirmar la ejecución de órdenes.
- **02_frontend:** contendrá el dashboard web para visualizar las mediciones, las órdenes y las confirmaciones del sistema.
- **03_supervisor_aiot:** contendrá el supervisor desarrollado en Python con FastAPI y su integración con Firebase y Google Gemini API.
- **docs:** reunirá la documentación de la arquitectura y del funcionamiento previsto del sistema.

## Parámetros ambientales

### Rango óptimo

- Temperatura: 12 °C a 18 °C.
- Humedad relativa: 65 % a 80 %.

### Contingencia

- Temperatura superior a 22 °C.
- Humedad inferior a 60 %.

Estos valores definirán las condiciones ambientales de referencia y los umbrales de contingencia del proyecto.
