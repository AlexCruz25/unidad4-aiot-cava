/*
 * Proyecto: Sistema AIoT para Cava de Crianza
 * Unidad: Trabajo Práctico Integrador - Unidad 4
 * Componente: Firmware ESP32
 * Hardware: ESP32 WROOM-32, 30 pines, USB-C con CH340
 * Sensor: DHT22 SIMULADO; GPIO 4 reservado para el sensor físico
 * Actuador/LED: GPIO 2
 *
 * PASOS 3 a 6: simulación, telemetría, órdenes SSE y Acknowledge.
 * - Escenarios de temperatura y humedad seleccionables por serie.
 * - Validación de lecturas con isnan().
 * - Temporización no bloqueante con millis(), cada 2500 ms.
 * - Control manual del climatizador mediante GPIO 2.
 * - Wi-Fi con reintentos temporizados y sincronización de hora por NTP.
 * - HTTPS PATCH a Firebase cada 5000 ms, con validación TLS por CA.
 * - Streaming SSE persistente con cliente TLS exclusivo para órdenes.
 * - HTTPS PUT del estado aplicado; prioridad ACK en la tarea de escrituras.
 *
 * Futuras funciones:
 * - Lectura del DHT22 físico.
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
#include "firebase_ack.h"
#include "diagnostico_red.h"

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
const char FIREBASE_HOST[] = "unidad4-aiot-cava-default-rtdb.firebaseio.com";
const char FIREBASE_URL[] =
    "https://unidad4-aiot-cava-default-rtdb.firebaseio.com"
    "/bodega/zona_crianza/ambiente.json";
const char FIREBASE_SSE_URL[] =
    "https://unidad4-aiot-cava-default-rtdb.firebaseio.com"
    "/bodega/zona_crianza/control/extractor_solicitado.json";
const char FIREBASE_ACK_URL[] =
    "https://unidad4-aiot-cava-default-rtdb.firebaseio.com"
    "/bodega/zona_crianza/extractor_confirmado.json";

// Las colas copian los datos; la tarea HTTPS no accede a las lecturas globales.
struct LecturaAmbiental {
  float temperatura;
  float humedad;
};

enum class TipoEscritura { Telemetria, Ack };

struct SolicitudEscritura {
  TipoEscritura tipo = TipoEscritura::Telemetria;
  LecturaAmbiental lectura = {};
  ConfirmacionActuador confirmacion;
};

struct ResultadoEnvio {
  TipoEscritura tipo;
  ConfirmacionActuador confirmacion;
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
EstadoAck estadoAck;
QueueHandle_t colaEscrituras = nullptr;
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
void programarConfirmacion(unsigned long ahora);
String construirJson(const LecturaAmbiental& lectura);
ResultadoEnvio enviarEscritura(const SolicitudEscritura& solicitud);
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
  Serial.printf("[DIAG] SSE=%s ACK=%s PATCH=activo | TLS con CA\n",
                CAVA_DIAG_SIN_SSE ? "DESACTIVADO" : "activo",
                CAVA_DIAG_SIN_ACK ? "DESACTIVADO" : "activo");
  iniciarDiagnosticoRed();
  mostrarMenu();
  seleccionarEscenario(1);
  iniciarConectividad();
  iniciarTareaFirebase();
#if !CAVA_DIAG_SIN_SSE
  const ConfiguracionSse configuracionSse = {
      FIREBASE_SSE_URL, FIREBASE_ROOT_CA, HORA_MINIMA_VALIDA,
      TIMEOUT_CONEXION_MS, TIMEOUT_HTTP_MS, TIMEOUT_TLS_SEGUNDOS};
  if (!iniciarSse(configuracionSse)) {
    Serial.println("[SSE] Sin memoria para iniciar streaming; control local y PATCH activos");
  }
#endif
  diagnosticarHeap("INICIO", "tareas-creadas");
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
  // Una sola solicitud de escritura en curso. ACK se programa antes de PATCH.
  // Tomar la hora después de procesar resultados: un fallo puede acabar de
  // iniciar su espera, y una marca anterior aparentaría un desborde de millis().
  programarConfirmacion(millis());
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
  // Siempre después del GPIO y del estado local, incluso si el valor coincide:
  // el estado inicial de SSE puede encontrar una confirmación remota antigua.
  estadoAck.registrar(actuadorEncendido);
}

void procesarEventosSse() {
#if !CAVA_DIAG_SIN_SSE
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
#endif
}

void mostrarMenu() {
  Serial.println();
  Serial.println("COMANDOS DISPONIBLES:");
  Serial.println("1 - Ambiente normal");
  Serial.println("2 - Temperatura alta");
  Serial.println("3 - Humedad baja");
  Serial.println("9 - Error de sensor");
  Serial.println("E - Encender climatizador (prueba local + ACK)");
  Serial.println("A - Apagar climatizador (prueba local + ACK)");
  Serial.println("E/A no cambian extractor_solicitado; una nueva orden SSE prevalece.");
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
    // Se conserva el GPIO y se volverá a publicar al recuperar conectividad.
    // El estado inicial del nuevo stream registrará también su propia versión.
    estadoAck.registrar(actuadorEncendido);
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
  colaEscrituras = xQueueCreate(1, sizeof(SolicitudEscritura));
  colaResultados = xQueueCreate(1, sizeof(ResultadoEnvio));
  if (colaEscrituras != nullptr && colaResultados != nullptr &&
      xTaskCreate(tareaFirebase, "firebase", 8192, nullptr, 1, nullptr) == pdPASS) {
    return;
  }

  if (colaEscrituras != nullptr) {
    vQueueDelete(colaEscrituras);
    colaEscrituras = nullptr;
  }
  if (colaResultados != nullptr) {
    vQueueDelete(colaResultados);
    colaResultados = nullptr;
  }
  Serial.println("[FIREBASE] Sin memoria para iniciar HTTPS; control local activo");
}

void programarConfirmacion(unsigned long ahora) {
  if (CAVA_DIAG_SIN_ACK) return;
  if (envioEnCurso || colaEscrituras == nullptr ||
      WiFi.status() != WL_CONNECTED || time(nullptr) < HORA_MINIMA_VALIDA) return;

  SolicitudEscritura solicitud;
  solicitud.tipo = TipoEscritura::Ack;
  if (!estadoAck.preparar(static_cast<uint32_t>(ahora), solicitud.confirmacion)) return;
  if (xQueueSend(colaEscrituras, &solicitud, 0) == pdTRUE) {
    envioEnCurso = true;
    Serial.printf("[ACK] Enviando confirmacion: %s\n",
                  solicitud.confirmacion.encender ? "true" : "false");
  }
}

void programarEnvio() {
  if (!validarLecturas(temperatura, humedad)) {
    Serial.println("[PATCH] Envio cancelado: lectura invalida");
    return;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[PATCH] Envio omitido: Wi-Fi sin conexion");
    return;
  }
  if (time(nullptr) < HORA_MINIMA_VALIDA) {
    Serial.println("[PATCH] Envio omitido: esperando hora NTP para TLS");
    return;
  }
  if (colaEscrituras == nullptr) {
    return;
  }
  if (envioEnCurso) {
    Serial.println("[PATCH] Envio omitido: solicitud anterior en curso (PATCH o ACK)");
    return;
  }

  SolicitudEscritura solicitud;
  solicitud.lectura = {temperatura, humedad};
  if (xQueueSend(colaEscrituras, &solicitud, 0) == pdTRUE) {
    envioEnCurso = true;
    Serial.println("[PATCH] Enviando telemetria...");
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

ResultadoEnvio enviarEscritura(const SolicitudEscritura& solicitud) {
  ResultadoEnvio resultado = {};
  resultado.tipo = solicitud.tipo;
  resultado.confirmacion = solicitud.confirmacion;
  const bool esAck = solicitud.tipo == TipoEscritura::Ack;
  // Se valida también la copia recibida por la tarea, antes de generar el JSON.
  if (!esAck && !validarLecturas(solicitud.lectura.temperatura, solicitud.lectura.humedad)) {
    snprintf(resultado.detalle, sizeof(resultado.detalle), "Lectura invalida; no enviada");
    return resultado;
  }
  if (WiFi.status() != WL_CONNECTED || time(nullptr) < HORA_MINIMA_VALIDA) {
    snprintf(resultado.detalle, sizeof(resultado.detalle), "Sin Wi-Fi o sin hora valida para TLS");
    return resultado;
  }

  const char* operacion = esAck ? "ACK" : "PATCH";
  diagnosticarHeap(operacion, "antes-objetos");
  diagnosticarRed(operacion, HORA_MINIMA_VALIDA);
  diagnosticarDns(operacion, FIREBASE_HOST);
  {
    // Orden deliberado: HTTPClient puede conservar &cliente aun después de
    // end() si falló connect(). Debe destruirse ANTES del cliente TLS.
    WiFiClientSecure cliente;
    cliente.setCACert(FIREBASE_ROOT_CA);
    cliente.setHandshakeTimeout(TIMEOUT_TLS_SEGUNDOS);
    HTTPClient http;
    http.setConnectTimeout(TIMEOUT_CONEXION_MS);
    http.setTimeout(TIMEOUT_HTTP_MS);
    http.setReuse(false);
    // No convertir PATCH/PUT en GET ni seguir destinos sin inspeccionarlos.
    http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
    const char* cabeceras[] = {"Location"};
    http.collectHeaders(cabeceras, 1);

    if (!http.begin(cliente, esAck ? FIREBASE_ACK_URL : FIREBASE_URL)) {
      snprintf(resultado.detalle, sizeof(resultado.detalle), "No se pudo iniciar HTTPClient con HTTPS");
    } else {
      http.addHeader("Content-Type", "application/json");
      // String contiene los bytes true/false SIN comillas: es un booleano JSON.
      const String cuerpo = esAck ? String(solicitud.confirmacion.encender ? "true" : "false")
                                 : construirJson(solicitud.lectura);
      diagnosticarHeap(operacion, "antes-TLS");
      const unsigned long inicio = millis();
      resultado.codigoHttp = http.sendRequest(esAck ? "PUT" : "PATCH", cuerpo);
      if (resultado.codigoHttp <= 0) {
        // Leer el error antes de cualquier diagnóstico o cierre.
        resultado.codigoTls = cliente.lastError(resultado.detalle, sizeof(resultado.detalle));
        resultado.detalle[sizeof(resultado.detalle) - 1] = '\0';
      }
      Serial.printf("[%s] [HTTPS] codigo=%d tiempo=%lu ms\n",
                    operacion, resultado.codigoHttp, millis() - inicio);
      diagnosticarHeap(operacion, "tras-peticion");
      if (resultado.codigoHttp >= 300 && resultado.codigoHttp < 400) {
        Serial.printf("[%s] [HTTP] Redireccion %d Location=%s; no seguida\n", operacion,
                      resultado.codigoHttp, http.hasHeader("Location") ? "presente" : "ausente");
      }
      if (resultado.codigoHttp <= 0) diagnosticarRed(operacion, HORA_MINIMA_VALIDA);
    }
    // También se ejecuta si begin() falla. Nunca afecta al cliente SSE.
    http.end();
    cliente.stop();
    diagnosticarHeap(operacion, "tras-cierre");
  }
  diagnosticarHeap(operacion, "tras-destruccion");
  return resultado;
}

void tareaFirebase(void* parametro) {
  (void)parametro;
  SolicitudEscritura solicitud;
  for (;;) {
    // La espera suspende solo esta tarea. loop() sigue atendiendo la consola,
    // el actuador, las lecturas, Wi-Fi y NTP durante la operación HTTPS.
    if (xQueueReceive(colaEscrituras, &solicitud, portMAX_DELAY) == pdTRUE) {
      const ResultadoEnvio resultado = enviarEscritura(solicitud);
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
  const bool esAck = resultado.tipo == TipoEscritura::Ack;
  const char* prefijo = esAck ? "[ACK]" : "[PATCH]";
  if (esAck) {
    estadoAck.resolver(resultado.confirmacion, resultado.codigoHttp,
                       static_cast<uint32_t>(millis()));
  }

  if (resultado.codigoHttp > 0) {
    if (esAck ? resultado.codigoHttp == 200 :
        (resultado.codigoHttp >= 200 && resultado.codigoHttp < 300)) {
      Serial.printf("%s HTTP %d - %s\n", prefijo, resultado.codigoHttp,
                    esAck ? "Estado confirmado en Firebase" : "Datos enviados correctamente");
      if (esAck) {
        Serial.printf("[ACK] Valor enviado: %s | Heap libre: %u bytes | Minimo: %u bytes\n",
                      resultado.confirmacion.encender ? "true" : "false",
                      static_cast<unsigned>(ESP.getFreeHeap()),
                      static_cast<unsigned>(ESP.getMinFreeHeap()));
      }
    } else {
      Serial.printf("%s HTTP %d - Error al enviar datos\n", prefijo, resultado.codigoHttp);
      if (resultado.codigoHttp == 401 || resultado.codigoHttp == 403) {
        Serial.printf("%s Revise reglas de seguridad o autenticacion en %s\n", prefijo,
                      esAck ? "extractor_confirmado" : "ambiente");
      }
    }
  } else if (resultado.codigoHttp < 0) {
    Serial.printf("%s Error de red/HTTPS %d: %s\n", prefijo, resultado.codigoHttp,
                  HTTPClient::errorToString(resultado.codigoHttp).c_str());
    if (resultado.codigoTls != 0) {
      Serial.printf("%s [TLS] Error %d: %s\n", prefijo, resultado.codigoTls, resultado.detalle);
      Serial.printf("%s [TLS] Revise hora NTP, CA, DNS y acceso a Internet\n", prefijo);
    }
    if (resultado.codigoHttp == HTTPC_ERROR_CONNECTION_REFUSED) {
      Serial.printf("%s [DIAG] -1 indica fallo al conectar; no prueba rechazo de Firebase.\n", prefijo);
    }
  } else {
    Serial.printf("%s %s\n", prefijo, resultado.detalle);
  }
  ConfirmacionActuador pendiente;
  if (esAck && estadoAck.preparar(static_cast<uint32_t>(millis()), pendiente)) {
    Serial.println("[ACK] Hay un estado aplicado mas reciente; confirmacion pendiente prioritaria");
  } else if (esAck && resultado.codigoHttp != 200) {
    Serial.printf("[ACK] Confirmacion pendiente; reintento con Wi-Fi y hora valida en %u s\n",
                  (resultado.codigoHttp == 401 || resultado.codigoHttp == 403) ? 60U : 5U);
  }
}
