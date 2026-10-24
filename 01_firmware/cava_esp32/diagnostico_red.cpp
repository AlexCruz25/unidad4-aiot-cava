#include "diagnostico_red.h"

#include <Arduino.h>
#include <WiFi.h>
#include <atomic>
#include <esp_heap_caps.h>
#include <esp_sntp.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace {
// El callback SNTP corre en otra tarea. No imprime ni reserva memoria.
std::atomic<uint32_t> ultimaSincronizacion{0};

void registrarSincronizacion(struct timeval* hora) {
  ultimaSincronizacion.store(static_cast<uint32_t>(hora->tv_sec), std::memory_order_relaxed);
}
}  // namespace

void iniciarDiagnosticoRed() {
  esp_sntp_set_time_sync_notification_cb(registrarSincronizacion);
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) {
    Serial.printf("[WIFI] [DIAG] Desconexion STA, motivo=%u\n",
                  static_cast<unsigned>(info.wifi_sta_disconnected.reason));
  }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
}

void diagnosticarHeap(const char* operacion, const char* fase) {
  // TLS necesita memoria direccionable por byte. No contar bloques solo de
  // 32 bits ni PSRAM como si fueran RAM interna utilizable por cualquier malloc.
  constexpr uint32_t capacidades = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
  Serial.printf("[%s] [HEAP] t=%lu %s | libre=%u minimo=%u mayor=%u pila_min=%u bytes\n",
                operacion, millis(), fase,
                static_cast<unsigned>(heap_caps_get_free_size(capacidades)),
                static_cast<unsigned>(heap_caps_get_minimum_free_size(capacidades)),
                static_cast<unsigned>(heap_caps_get_largest_free_block(capacidades)),
                static_cast<unsigned>(uxTaskGetStackHighWaterMark(nullptr)));
}

void diagnosticarRed(const char* operacion, time_t horaMinima) {
  const time_t ahora = time(nullptr);
  struct tm utc;
  char fecha[24] = "no disponible";
  if (gmtime_r(&ahora, &utc)) strftime(fecha, sizeof(fecha), "%Y-%m-%dT%H:%M:%SZ", &utc);
  Serial.printf("[%s] [RED] wifi=%d IP=%s GW=%s RSSI=%ld dBm DNS=%s/%s\n",
                operacion, static_cast<int>(WiFi.status()),
                WiFi.localIP().toString().c_str(), WiFi.gatewayIP().toString().c_str(),
                static_cast<long>(WiFi.RSSI()), WiFi.dnsIP(0).toString().c_str(),
                WiFi.dnsIP(1).toString().c_str());
  Serial.printf("[%s] [NTP] UTC=%s valida=%s ultima_sync_epoch=%lu\n",
                operacion, fecha, ahora >= horaMinima ? "si" : "no",
                static_cast<unsigned long>(ultimaSincronizacion.load(std::memory_order_relaxed)));
}

void diagnosticarDns(const char* operacion, const char* host) {
  IPAddress ip;
  const unsigned long inicio = millis();
  const int resuelto = WiFi.hostByName(host, ip);
  Serial.printf("[%s] [DNS] host=%s resultado=%d IP=%s tiempo=%lu ms\n",
                operacion, host, resuelto, resuelto ? ip.toString().c_str() : "sin resolver",
                millis() - inicio);
  // Es una consulta de diagnóstico. El cliente conecta por hostname para
  // conservar SNI y validación del nombre; puede volver a consultar la caché DNS.
}
