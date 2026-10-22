/*
 * Proyecto: Sistema AIoT para Cava de Crianza
 * Unidad: Trabajo Práctico Integrador - Unidad 4
 * Componente: Firmware ESP32
 * Hardware: ESP32 WROOM-32, 30 pines, USB-C con CH340
 * Sensor: DHT22 SIMULADO; GPIO 4 reservado para el sensor físico
 * Actuador/LED: GPIO 2
 *
 * PASO 3: simulación local ejecutada en el ESP32 físico.
 * - Escenarios de temperatura y humedad seleccionables por serie.
 * - Validación de lecturas con isnan().
 * - Temporización no bloqueante con millis(), cada 2500 ms.
 * - Control manual del climatizador mediante GPIO 2.
 *
 * Futuras funciones:
 * - Lectura del DHT22 físico.
 * - Envío de telemetría mediante HTTPS PATCH cada 5 segundos.
 * - Recepción de eventos SSE desde Firebase.
 * - Acknowledge mediante HTTPS PUT.
 *
 * Conectividad pendiente para las siguientes etapas.
 */

#include <Arduino.h>
#include <math.h>

#define MODO_SIMULACION true

// GPIO 4 no se configura ni se utiliza mientras no haya un DHT22 conectado.
const uint8_t DHT_PIN = 4;
const uint8_t ACTUATOR_PIN = 2;
const unsigned long INTERVALO_LECTURA = 2500UL;

uint8_t escenarioActual = 1;
float temperatura = NAN;
float humedad = NAN;
unsigned long ultimaLectura = 0UL;

void procesarComandosSerie();
void seleccionarEscenario(uint8_t escenario);
void obtenerDatosSimulados();
bool validarLecturas(float temperatura, float humedad);
void mostrarTelemetria();
void controlarActuador(bool encender);
void mostrarMenu();

void setup() {
  // El LED integrado representa el climatizador si está conectado a GPIO 2.
  pinMode(ACTUATOR_PIN, OUTPUT);
  digitalWrite(ACTUATOR_PIN, LOW);

  Serial.begin(115200);
  Serial.println("Hardware: ESP32 WROOM-32");
  Serial.println("Sensor: DHT22 SIMULADO");
  Serial.println("Actuador: GPIO 2");
  mostrarMenu();
  seleccionarEscenario(1);
  ultimaLectura = millis();
}

void loop() {
  // Los comandos se atienden en cada vuelta, sin esperar la próxima lectura.
  procesarComandosSerie();

  const unsigned long ahora = millis();
  // La resta sin signo conserva el intervalo al desbordarse millis().
  if (ahora - ultimaLectura >= INTERVALO_LECTURA) {
    ultimaLectura = ahora;

    if (MODO_SIMULACION) {
      obtenerDatosSimulados();
      // Una lectura inválida no llega a la telemetría ni a otro procesamiento.
      if (!validarLecturas(temperatura, humedad)) {
        return;
      }
      mostrarTelemetria();
    }
  }
}

void procesarComandosSerie() {
  // Cada carácter es un comando: no se espera un fin de línea ni un timeout.
  while (Serial.available() > 0) {
    const char comando = static_cast<char>(Serial.read());

    switch (comando) {
      case '1':
      case '2':
      case '3':
      case '9':
        seleccionarEscenario(static_cast<uint8_t>(comando - '0'));
        break;
      case 'E':
      case 'e':
        controlarActuador(true);
        break;
      case 'A':
      case 'a':
        controlarActuador(false);
        break;
      case 'M':
      case 'm':
        mostrarMenu();
        break;
      case '\r':
      case '\n':
      case ' ':
      case '\t':
        // Admite sin salto de línea, LF y CRLF en el monitor serie.
        break;
      default:
        Serial.println("[COMANDO] No reconocido. Ingrese M para mostrar el menu.");
        break;
    }
  }
}

void seleccionarEscenario(uint8_t escenario) {
  const char* descripcion;

  switch (escenario) {
    case 1:
      descripcion = "AMBIENTE NORMAL";
      break;
    case 2:
      descripcion = "TEMPERATURA ALTA";
      break;
    case 3:
      descripcion = "HUMEDAD BAJA";
      break;
    case 9:
      descripcion = "ERROR DE SENSOR";
      break;
    default:
      return;
  }

  escenarioActual = escenario;
  Serial.print("[ESCENARIO] ");
  Serial.print(escenarioActual);
  Serial.print(" - ");
  Serial.println(descripcion);
}

void obtenerDatosSimulados() {
  // Los datos se generan en la placa; no requieren librerías ni sensor DHT.
  switch (escenarioActual) {
    case 1:
      temperatura = 16.0f;
      humedad = 70.0f;
      break;
    case 2:
      temperatura = 24.0f;
      humedad = 70.0f;
      break;
    case 3:
      temperatura = 17.0f;
      humedad = 55.0f;
      break;
    case 9:
    default:
      temperatura = NAN;
      humedad = NAN;
      break;
  }
}

bool validarLecturas(float temperatura, float humedad) {
  if (isnan(temperatura) || isnan(humedad)) {
    Serial.println("[ERROR] Lectura invalida del DHT22 simulado");
    return false;
  }
  return true;
}

void mostrarTelemetria() {
  Serial.print("[AMBIENTE] Temperatura: ");
  Serial.print(temperatura, 2);
  Serial.print(" C | Humedad: ");
  Serial.print(humedad, 2);
  Serial.println(" %");
}

void controlarActuador(bool encender) {
  digitalWrite(ACTUATOR_PIN, encender ? HIGH : LOW);
  Serial.print("[ACTUADOR] GPIO 2 = ");
  Serial.println(encender ? "ON" : "OFF");
}

void mostrarMenu() {
  Serial.println();
  Serial.println("COMANDOS DISPONIBLES:");
  Serial.println("1 - Ambiente normal");
  Serial.println("2 - Temperatura alta");
  Serial.println("3 - Humedad baja");
  Serial.println("9 - Error de sensor");
  Serial.println("E - Encender climatizador");
  Serial.println("A - Apagar climatizador");
  Serial.println("M - Mostrar menu");
  Serial.println();
}
