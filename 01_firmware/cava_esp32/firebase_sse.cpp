#include "firebase_sse.h"
#include "sse_parser.h"
#include "diagnostico_red.h"

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <stdarg.h>
#include <string.h>

namespace {

constexpr unsigned long REINTENTO_SSE_MS = 5000UL;
constexpr unsigned long REINTENTO_MAXIMO_MS = 60000UL;
constexpr unsigned long INACTIVIDAD_SSE_MS = 90000UL;
constexpr size_t BYTES_POR_VUELTA = 2048;
constexpr uint32_t PILA_SSE_BYTES = 12288;

struct AvisoSse { char texto[144]; };
struct ConexionSse {
  bool establecida = false;
  bool permisoDenegado = false;
  bool chunked = false;
};

ConfiguracionSse config;
QueueHandle_t colaOrdenes = nullptr;
QueueHandle_t colaAvisos = nullptr;
TaskHandle_t tarea = nullptr;

void avisar(const char* formato, ...) {
  AvisoSse aviso = {};
  va_list argumentos;
  va_start(argumentos, formato);
  vsnprintf(aviso.texto, sizeof(aviso.texto), formato, argumentos);
  va_end(argumentos);
  // Los avisos pueden descartarse si la consola no alcanza. Las órdenes usan
  // otra cola, con el último booleano completo, y no dependen de los avisos.
  xQueueSend(colaAvisos, &aviso, 0);
}

bool redPreparada() {
  return WiFi.status() == WL_CONNECTED && time(nullptr) >= config.horaMinima;
}

void cerrarStream(WiFiClientSecure& cliente) {
  diagnosticarHeap("SSE", "antes-cierre");
  cliente.stop();
  diagnosticarHeap("SSE", "tras-cierre");
}

ConexionSse abrirStream(WiFiClientSecure& cliente) {
  char url[cava::MAX_URL_SSE];
  if (strlen(config.url) >= sizeof(url)) return {};
  strcpy(url, config.url);

  // Cada salto vuelve a verificar CA, hostname y fechas para el nuevo destino.
  // Solo se permiten HTTPS y puerto 443. Location nunca se imprime: podría
  // contener parámetros de autorización en una futura etapa.
  for (unsigned redirecciones = 0; redirecciones <= 3; ++redirecciones) {
    cava::DestinoHttps destino;
    if (!redPreparada() || !cava::interpretarUrlHttps(url, destino)) {
      avisar("[SSE] Red/hora no disponible o destino HTTPS invalido");
      return {};
    }
    cliente.stop();
    cliente.setCACert(config.ca);
    cliente.setHandshakeTimeout(config.timeoutTlsSegundos);
    cliente.setTimeout(config.timeoutHttpMs);
    diagnosticarRed("SSE", config.horaMinima);
    diagnosticarDns("SSE", destino.host);
    diagnosticarHeap("SSE", "antes-TLS");
    const unsigned long inicioTls = millis();
    const bool conectadoTls = cliente.connect(destino.host, 443, config.timeoutConexionMs);
    // lastError pertenece a este intento y se lee antes de otros diagnósticos.
    char detalle[80] = {};
    const int error = conectadoTls ? 0 : cliente.lastError(detalle, sizeof(detalle));
    detalle[sizeof(detalle) - 1] = '\0';
    Serial.printf("[SSE] [TLS] conectado=%s tiempo=%lu ms\n",
                  conectadoTls ? "si" : "no", millis() - inicioTls);
    diagnosticarHeap("SSE", "tras-TLS");
    if (!conectadoTls) {
      avisar("[SSE] Error de conexion/TLS %d: %s", error, detalle);
      diagnosticarRed("SSE", config.horaMinima);
      return {};
    }

    char peticion[1100];
    const int longitud = snprintf(peticion, sizeof(peticion),
        "GET %s HTTP/1.1\r\nHost: %s\r\nAccept: text/event-stream\r\n"
        "Accept-Encoding: identity\r\nConnection: keep-alive\r\n\r\n",
        destino.recurso, destino.host);
    if (longitud < 0 || static_cast<size_t>(longitud) >= sizeof(peticion) ||
        cliente.write(reinterpret_cast<const uint8_t*>(peticion), longitud) != static_cast<size_t>(longitud)) {
      avisar("[SSE] No se pudo escribir la peticion GET de streaming");
      return {};
    }

    cava::CabecerasSse cabeceras;
    const unsigned long inicio = millis();
    while (!cabeceras.completas()) {
      if (!redPreparada() || millis() - inicio >= config.timeoutHttpMs) {
        avisar("[SSE] Tiempo de espera de cabeceras agotado o Wi-Fi desconectado");
        return {};
      }
      if (cliente.available() > 0) {
        const int byte = cliente.read();
        if (byte >= 0 && !cabeceras.consumir(static_cast<char>(byte))) {
          avisar("[SSE] Cabeceras HTTP invalidas o demasiado grandes");
          return {};
        }
      } else if (!cliente.connected()) {
        avisar("[SSE] Conexion cerrada antes de completar las cabeceras");
        return {};
      } else {
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(5));
      }
    }

    if (cabeceras.codigo() == 307) {
      char siguiente[cava::MAX_URL_SSE];
      if (redirecciones == 3 || !cava::resolverLocation(url, cabeceras.location(), siguiente, sizeof(siguiente))) {
        avisar("[SSE] HTTP 307 - Location insegura/invalida o limite de 3 redirecciones");
        return {};
      }
      avisar("[SSE] HTTP 307 - Siguiendo redireccion HTTPS con validacion TLS");
      cerrarStream(cliente);
      strcpy(url, siguiente);
      continue;
    }
    if (cabeceras.codigo() != 200 || !cabeceras.esStreaming()) {
      avisar("[SSE] HTTP %d - No se establecio text/event-stream", cabeceras.codigo());
      return {false, cabeceras.codigo() == 401 || cabeceras.codigo() == 403, false};
    }
    return {true, false, cabeceras.esChunked()};
  }
  return {};
}

void escucharFirebase(void* parametro) {
  (void)parametro;
  // Este cliente no se comparte con HTTPClient ni con la tarea PATCH.
  WiFiClientSecure clienteSse;
  cava::ParserSse parser;
  cava::CuerpoSse cuerpo;
  bool conectado = false;
  bool intentoRealizado = false;
  unsigned long ultimoCierre = 0;
  unsigned long espera = REINTENTO_SSE_MS;
  unsigned long siguienteEspera = REINTENTO_SSE_MS;
  unsigned long ultimaActividad = 0;

  for (;;) {
    // Espera acotada de FreeRTOS: cede CPU sin bloquear loop().
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(20));
    const unsigned long ahora = millis();
    if (!redPreparada()) {
      if (conectado) {
        cerrarStream(clienteSse);
        conectado = false;
        ultimoCierre = ahora;
        espera = REINTENTO_SSE_MS;
        avisar("[SSE] Conexion perdida. Reintentando... (sin Wi-Fi u hora valida)");
      }
      continue;
    }

    if (!conectado) {
      if (intentoRealizado && ahora - ultimoCierre < espera) continue;
      intentoRealizado = true;
      avisar("[SSE] Conectando con Firebase...");
      const ConexionSse conexion = abrirStream(clienteSse);
      if (!conexion.establecida) {
        cerrarStream(clienteSse);
        ultimoCierre = millis();
        espera = conexion.permisoDenegado ? REINTENTO_MAXIMO_MS : siguienteEspera;
        siguienteEspera = siguienteEspera < REINTENTO_MAXIMO_MS / 2 ? siguienteEspera * 2 : REINTENTO_MAXIMO_MS;
        avisar("[SSE] Reintento en %lu s", espera / 1000UL);
        continue;
      }
      conectado = true;
      siguienteEspera = REINTENTO_SSE_MS;
      parser.reiniciar();
      cuerpo.reiniciar(conexion.chunked);
      ultimaActividad = millis();
      avisar("[SSE] HTTP 200 - Streaming establecido");
      diagnosticarHeap("SSE", "stream-activo");
    }

    bool cerrar = false;
    espera = REINTENTO_SSE_MS;
    size_t leidos = 0;
    while (leidos++ < BYTES_POR_VUELTA && clienteSse.available() > 0) {
      const int byte = clienteSse.read();
      if (byte < 0) break;
      ultimaActividad = millis();
      char dato = '\0';
      const cava::ByteHttp resultado = cuerpo.consumir(static_cast<char>(byte), dato);
      if (resultado == cava::ByteHttp::Error || resultado == cava::ByteHttp::Fin) {
        avisar("[SSE] Conexion perdida. Reintentando... (fin o error del cuerpo HTTP)");
        cerrar = true;
        break;
      }
      if (resultado != cava::ByteHttp::Dato) continue;

      const cava::EventoSse evento = parser.consumir(dato);
      if (evento.tipo == cava::TipoSse::Orden) {
        // Si hay cambios muy rápidos, loop() consume el último estado pedido.
        xQueueOverwrite(colaOrdenes, &evento.encender);
      } else if (evento.tipo == cava::TipoSse::Error) {
        avisar("[SSE] %s", evento.detalle);
      } else if (evento.tipo == cava::TipoSse::Cancel || evento.tipo == cava::TipoSse::AuthRevoked) {
        avisar("[SSE] %s - Revise permiso de lectura/autorizacion; reintento en 60 s",
               evento.tipo == cava::TipoSse::Cancel ? "cancel" : "auth_revoked");
        espera = REINTENTO_MAXIMO_MS;
        cerrar = true;
        break;
      }
      // keep-alive y comentarios solo mantienen viva la conexión, sin órdenes.
    }

    if (!cerrar && (!clienteSse.connected() && clienteSse.available() == 0)) {
      avisar("[SSE] Conexion perdida. Reintentando... (servidor desconectado)");
      cerrar = true;
    }
    if (!cerrar && millis() - ultimaActividad >= INACTIVIDAD_SSE_MS) {
      avisar("[SSE] Conexion perdida. Reintentando... (90 s sin actividad)");
      cerrar = true;
    }
    if (cerrar) {
      cerrarStream(clienteSse);
      conectado = false;
      ultimoCierre = millis();
    }
  }
}

}  // namespace

bool iniciarSse(const ConfiguracionSse& configuracion) {
  if (tarea != nullptr) return true;
  config = configuracion;
  colaOrdenes = xQueueCreate(1, sizeof(bool));
  colaAvisos = xQueueCreate(8, sizeof(AvisoSse));
  if (colaOrdenes && colaAvisos &&
      xTaskCreate(escucharFirebase, "firebase_sse", PILA_SSE_BYTES, nullptr, 1, &tarea) == pdPASS) return true;
  if (colaOrdenes) vQueueDelete(colaOrdenes);
  if (colaAvisos) vQueueDelete(colaAvisos);
  colaOrdenes = colaAvisos = nullptr;
  tarea = nullptr;
  return false;
}

bool recibirOrdenSse(bool& encender) {
  return colaOrdenes && xQueueReceive(colaOrdenes, &encender, 0) == pdTRUE;
}

bool recibirAvisoSse(char* texto, size_t capacidad) {
  AvisoSse aviso;
  if (!texto || capacidad == 0 || !colaAvisos || xQueueReceive(colaAvisos, &aviso, 0) != pdTRUE) return false;
  strncpy(texto, aviso.texto, capacidad - 1);
  texto[capacidad - 1] = '\0';
  return true;
}
