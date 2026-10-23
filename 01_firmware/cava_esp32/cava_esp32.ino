/*
 * Proyecto: Sistema AIoT para Cava de Crianza
 * Unidad: Trabajo Práctico Integrador - Unidad 4
 * Componente: Firmware ESP32
 * Hardware: ESP32 WROOM-32, 30 pines, USB-C con CH340
 * Sensor: DHT22 SIMULADO; GPIO 4 reservado para el sensor físico
 * Actuador/LED: GPIO 2
 *
 * PASOS 3, 4 y 5: simulación, telemetría y órdenes reactivas en el ESP32.
 * - Escenarios de temperatura y humedad seleccionables por serie.
 * - Validación de lecturas con isnan().
 * - Temporización no bloqueante con millis(), cada 2500 ms.
 * - Control manual del climatizador mediante GPIO 2.
 * - Wi-Fi con reintentos temporizados y sincronización de hora por NTP.
 * - HTTPS PATCH a Firebase cada 5000 ms, con validación TLS por CA.
 * - Streaming SSE persistente con cliente TLS exclusivo para órdenes.
 *
 * Futuras funciones:
 * - Lectura del DHT22 físico.
 * - Acknowledge mediante HTTPS PUT.
 *
 * La confirmación remota queda para el PASO 6.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <math.h>
#include <string.h>
#include <time.h>

#include "secrets.h"
#include "firebase_ca.h"
#include "firebase_sse.h"

#define MODO_SIMULACION true

// GPIO 4 no se configura ni se utiliza mientras no haya un DHT22 conectado.
const uint8_t DHT_PIN = 4;
const uint8_t ACTUATOR_PIN = 2;
const unsigned long INTERVALO_LECTURA = 2500UL;
const unsigned long INTERVALO_ENVIO = 5000UL;
const unsigned long INTERVALO_REINTENTO_WIFI = 10000UL;
const unsigned long INTERVALO_REINTENTO_NTP = 60000UL;
const int32_t TIMEOUT_CONEXION_MS = 3000;
const uint16_t TIMEOUT_HTTP_MS = 3000;
const unsigned long TIMEOUT_TLS_SEGUNDOS = 4UL;
// Impide verificar certificados con el reloj de arranque (1970).
const time_t HORA_MINIMA_VALIDA = 1704067200;  // 2024-01-01 UTC.
const char FIREBASE_URL[] =
    "https://unidad4-aiot-cava-default-rtdb.firebaseio.com"
    "/bodega/zona_crianza/ambiente.json";
const char FIREBASE_SSE_URL[] =
    "https://unidad4-aiot-cava-default-rtdb.firebaseio.com"
    "/bodega/zona_crianza/control/extractor_solicitado.json";

// Las colas copian los datos; la tarea HTTPS no accede a las lecturas globales.
struct LecturaAmbiental {
  float temperatura;
  float humedad;
};

struct ResultadoEnvio {
  int codigoHttp;
  int codigoTls;
  char detalle[160];
};

uint8_t escenarioActual = 1;
float temperatura = NAN;
float humedad = NAN;
unsigned long ultimaLectura = 0UL;
unsigned long ultimoEnvio = 0UL;
unsigned long ultimoIntentoWiFi = 0UL;
unsigned long ultimoIntentoNtp = 0UL;
bool wifiConfigurada = false;
bool wifiConectado = false;
bool intentoWiFiIniciado = false;
bool ntpIniciado = false;
bool horaConfirmada = false;
bool envioEnCurso = false;
bool actuadorEncendido = false;
QueueHandle_t colaLecturas = nullptr;
QueueHandle_t colaResultados = nullptr;

void procesarComandosSerie();
void seleccionarEscenario(uint8_t escenario);
void obtenerDatosSimulados();
bool validarLecturas(float temperatura, float humedad);
void mostrarTelemetria();
void controlarActuador(bool encender);
void mostrarMenu();
void iniciarConectividad();
void gestionarWiFi(unsigned long ahora);
void sincronizarHora(unsigned long ahora);
void iniciarTareaFirebase();
void programarEnvio();
String construirJson(const LecturaAmbiental& lectura);
ResultadoEnvio enviarTelemetria(const LecturaAmbiental& lectura);
void tareaFirebase(void* parametro);
void procesarResultadoEnvio();
void procesarEventosSse();

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
  iniciarConectividad();
  iniciarTareaFirebase();
  const ConfiguracionSse configuracionSse = {
      FIREBASE_SSE_URL, FIREBASE_ROOT_CA, HORA_MINIMA_VALIDA,
      TIMEOUT_CONEXION_MS, TIMEOUT_HTTP_MS, TIMEOUT_TLS_SEGUNDOS};
  if (!iniciarSse(configuracionSse)) {
    Serial.println("[SSE] Sin memoria para iniciar streaming; control local y PATCH activos");
  }
  ultimaLectura = millis();
  ultimoEnvio = ultimaLectura;
}

void loop() {
  // Los comandos se atienden en cada vuelta, sin esperar la próxima lectura.
  procesarComandosSerie();

  const unsigned long ahora = millis();
  gestionarWiFi(ahora);
  sincronizarHora(ahora);
  procesarResultadoEnvio();
  procesarEventosSse();
  // La resta sin signo conserva el intervalo al desbordarse millis().
  if (ahora - ultimaLectura >= INTERVALO_LECTURA) {
    ultimaLectura = ahora;

    if (MODO_SIMULACION) {
      obtenerDatosSimulados();
      // Una lectura inválida no llega a la telemetría ni a otro procesamiento.
      if (validarLecturas(temperatura, humedad)) {
        mostrarTelemetria();
      }
    }
  }

  // Un reloj independiente mantiene los envíos separados de las lecturas.
  if (ahora - ultimoEnvio >= INTERVALO_ENVIO) {
    ultimoEnvio = ahora;
    programarEnvio();
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
  // Actualiza la muestra inmediatamente: el escenario 9 invalida también el
  // próximo envío, aunque todavía no venza el intervalo de lectura local.
  obtenerDatosSimulados();
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
  if (actuadorEncendido != encender) {
    digitalWrite(ACTUATOR_PIN, encender ? HIGH : LOW);
    actuadorEncendido = encender;
  }
  Serial.print("[ACTUADOR] GPIO 2 = ");
  Serial.println(encender ? "ON" : "OFF");
}

void procesarEventosSse() {
  char aviso[144];
  for (unsigned i = 0; i < 8 && recibirAvisoSse(aviso, sizeof(aviso)); ++i) {
    Serial.println(aviso);
  }
  bool encender;
  if (recibirOrdenSse(encender)) {
    Serial.println(encender ? "[SSE] Orden recibida: ENCENDER" : "[SSE] Orden recibida: APAGAR");
    // El estado inicial y cada evento válido pasan por el mismo control local.
    controlarActuador(encender);
  }
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

void iniciarConectividad() {
  wifiConfigurada = strlen(WIFI_SSID) > 0 &&
                    strcmp(WIFI_SSID, "NOMBRE_DE_TU_WIFI") != 0 &&
                    strcmp(WIFI_PASSWORD, "CONTRASENA_DE_TU_WIFI") != 0;
  if (!wifiConfigurada) {
    Serial.println("[WIFI] Configure SSID y password en secrets.h y vuelva a cargar.");
    return;
  }

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  // Los reintentos los controla gestionarWiFi() mediante millis().
  WiFi.setAutoReconnect(false);
}

void gestionarWiFi(unsigned long ahora) {
  if (!wifiConfigurada) {
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiConectado) {
      Serial.println("[WIFI] Conectado correctamente");
      Serial.print("[WIFI] IP: ");
      Serial.println(WiFi.localIP());
    }
    wifiConectado = true;
    return;
  }

  if (wifiConectado) {
    Serial.println("[WIFI] Conexion perdida");
    wifiConectado = false;
    intentoWiFiIniciado = false;
  }

  if (!intentoWiFiIniciado ||
      ahora - ultimoIntentoWiFi >= INTERVALO_REINTENTO_WIFI) {
    ultimoIntentoWiFi = ahora;
    intentoWiFiIniciado = true;
    Serial.println("[WIFI] Intentando conexion (reintento cada 10 s)...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

void sincronizarHora(unsigned long ahora) {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  const time_t horaActual = time(nullptr);
  if (horaActual >= HORA_MINIMA_VALIDA) {
    if (!horaConfirmada) {
      Serial.println("[NTP] Hora valida; verificacion TLS habilitada");
      horaConfirmada = true;
    }
    return;
  }

  horaConfirmada = false;
  if (!ntpIniciado || ahora - ultimoIntentoNtp >= INTERVALO_REINTENTO_NTP) {
    ultimoIntentoNtp = ahora;
    ntpIniciado = true;
    Serial.println("[NTP] Sincronizando hora (reintento cada 60 s)...");
    // configTime inicia SNTP en segundo plano. No esperamos en un bucle ni
    // usamos getLocalTime(), que puede esperar varios segundos por defecto.
    configTime(0, 0, "time.google.com", "pool.ntp.org", "time.cloudflare.com");
  }
}

void iniciarTareaFirebase() {
  colaLecturas = xQueueCreate(1, sizeof(LecturaAmbiental));
  colaResultados = xQueueCreate(1, sizeof(ResultadoEnvio));
  if (colaLecturas != nullptr && colaResultados != nullptr &&
      xTaskCreate(tareaFirebase, "firebase", 8192, nullptr, 1, nullptr) == pdPASS) {
    return;
  }

  if (colaLecturas != nullptr) {
    vQueueDelete(colaLecturas);
    colaLecturas = nullptr;
  }
  if (colaResultados != nullptr) {
    vQueueDelete(colaResultados);
    colaResultados = nullptr;
  }
  Serial.println("[FIREBASE] Sin memoria para iniciar HTTPS; control local activo");
}

void programarEnvio() {
  if (!validarLecturas(temperatura, humedad)) {
    Serial.println("[FIREBASE] Envio cancelado: lectura invalida");
    return;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[FIREBASE] Envio omitido: Wi-Fi sin conexion");
    return;
  }
  if (time(nullptr) < HORA_MINIMA_VALIDA) {
    Serial.println("[FIREBASE] Envio omitido: esperando hora NTP para TLS");
    return;
  }
  if (colaLecturas == nullptr) {
    return;
  }
  if (envioEnCurso) {
    Serial.println("[FIREBASE] Envio omitido: solicitud anterior en curso");
    return;
  }

  const LecturaAmbiental lectura = {temperatura, humedad};
  if (xQueueSend(colaLecturas, &lectura, 0) == pdTRUE) {
    envioEnCurso = true;
    Serial.println("[FIREBASE] Enviando telemetria...");
  }
}

String construirJson(const LecturaAmbiental& lectura) {
  String json;
  json.reserve(96);
  json = "{\"temperatura\":";
  json += String(lectura.temperatura, 2);
  json += ",\"humedad\":";
  json += String(lectura.humedad, 2);
  // El servidor Firebase reemplaza .sv por su timestamp en milisegundos.
  json += ",\"timestamp\":{\".sv\":\"timestamp\"}}";
  return json;
}

ResultadoEnvio enviarTelemetria(const LecturaAmbiental& lectura) {
  ResultadoEnvio resultado = {};
  // Se valida también la copia recibida por la tarea, antes de generar el JSON.
  if (!validarLecturas(lectura.temperatura, lectura.humedad)) {
    snprintf(resultado.detalle, sizeof(resultado.detalle), "Lectura invalida; no enviada");
    return resultado;
  }
  if (WiFi.status() != WL_CONNECTED || time(nullptr) < HORA_MINIMA_VALIDA) {
    snprintf(resultado.detalle, sizeof(resultado.detalle), "Sin Wi-Fi o sin hora valida para TLS");
    return resultado;
  }

  WiFiClientSecure cliente;
  cliente.setCACert(FIREBASE_ROOT_CA);
  cliente.setHandshakeTimeout(TIMEOUT_TLS_SEGUNDOS);
  HTTPClient http;
  http.setConnectTimeout(TIMEOUT_CONEXION_MS);
  http.setTimeout(TIMEOUT_HTTP_MS);
  http.setReuse(false);

  if (!http.begin(cliente, FIREBASE_URL)) {
    snprintf(resultado.detalle, sizeof(resultado.detalle), "No se pudo iniciar HTTPClient con HTTPS");
    return resultado;
  }
  http.addHeader("Content-Type", "application/json");
  resultado.codigoHttp = http.sendRequest("PATCH", construirJson(lectura));
  if (resultado.codigoHttp <= 0) {
    resultado.codigoTls = cliente.lastError(resultado.detalle, sizeof(resultado.detalle));
    resultado.detalle[sizeof(resultado.detalle) - 1] = '\0';
  }
  http.end();
  cliente.stop();
  return resultado;
}

void tareaFirebase(void* parametro) {
  (void)parametro;
  LecturaAmbiental lectura;
  for (;;) {
    // La espera suspende solo esta tarea. loop() sigue atendiendo la consola,
    // el actuador, las lecturas, Wi-Fi y NTP durante la operación HTTPS.
    if (xQueueReceive(colaLecturas, &lectura, portMAX_DELAY) == pdTRUE) {
      const ResultadoEnvio resultado = enviarTelemetria(lectura);
      xQueueSend(colaResultados, &resultado, portMAX_DELAY);
    }
  }
}

void procesarResultadoEnvio() {
  ResultadoEnvio resultado;
  if (colaResultados == nullptr ||
      xQueueReceive(colaResultados, &resultado, 0) != pdTRUE) {
    return;
  }
  envioEnCurso = false;

  if (resultado.codigoHttp > 0) {
    if (resultado.codigoHttp >= 200 && resultado.codigoHttp < 300) {
      Serial.printf("[FIREBASE] HTTP %d - Datos enviados correctamente\n", resultado.codigoHttp);
    } else {
      Serial.printf("[FIREBASE] HTTP %d - Error al enviar datos\n", resultado.codigoHttp);
      if (resultado.codigoHttp == 401 || resultado.codigoHttp == 403) {
        Serial.println("[FIREBASE] Revise permisos de escritura de desarrollo en la ruta ambiente");
      }
    }
  } else if (resultado.codigoHttp < 0) {
    Serial.printf("[FIREBASE] Error de red/HTTPS %d: %s\n", resultado.codigoHttp,
                  HTTPClient::errorToString(resultado.codigoHttp).c_str());
    if (resultado.codigoTls != 0) {
      Serial.printf("[TLS] Error %d: %s\n", resultado.codigoTls, resultado.detalle);
      Serial.println("[TLS] Revise hora NTP, CA, DNS y acceso a Internet");
    }
  } else {
    Serial.printf("[FIREBASE] %s\n", resultado.detalle);
  }
}
