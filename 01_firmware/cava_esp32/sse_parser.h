#pragma once

/*
 * PASO 5: parsers incrementales sin dependencias de red ni buffers crecientes.
 * HTTP y SSE pueden llegar fragmentados en cualquier byte.
 */
#include <stddef.h>
#include <stdint.h>

namespace cava {

constexpr size_t MAX_URL_SSE = 768;

struct DestinoHttps {
  char host[128];
  char recurso[MAX_URL_SSE];
};

bool interpretarUrlHttps(const char* url, DestinoHttps& destino);
bool resolverLocation(const char* origen, const char* location, char* salida, size_t capacidad);

class CabecerasSse {
 public:
  void reiniciar();
  bool consumir(char byte);  // false indica formato inválido o límite excedido.
  bool completas() const { return completas_; }
  int codigo() const { return codigo_; }
  bool esStreaming() const { return streaming_; }
  bool esChunked() const { return chunked_; }
  const char* location() const { return location_; }

 private:
  char linea_[1024] = {};
  char location_[MAX_URL_SSE] = {};
  size_t usados_ = 0;
  size_t total_ = 0;
  int codigo_ = 0;
  bool primera_ = true;
  bool completas_ = false;
  bool streaming_ = false;
  bool chunked_ = false;
  bool tieneLocation_ = false;
  bool finalizarLinea();
};

enum class ByteHttp { SinDato, Dato, Fin, Error };

class CuerpoSse {
 public:
  void reiniciar(bool chunked);
  ByteHttp consumir(char byte, char& dato);

 private:
  enum class Estado { Tamano, Datos, Retorno, Salto, Fin };
  bool chunked_ = false;
  Estado estado_ = Estado::Tamano;
  char linea_[64] = {};
  size_t usados_ = 0;
  uint32_t pendientes_ = 0;
};

enum class TipoSse { Ninguno, Orden, KeepAlive, Cancel, AuthRevoked, Error };

struct EventoSse {
  TipoSse tipo = TipoSse::Ninguno;
  bool encender = false;
  const char* detalle = nullptr;  // Solo literales de diagnóstico, nunca el JSON.
};

class ParserSse {
 public:
  void reiniciar();
  EventoSse consumir(char byte);

 private:
  char linea_[512] = {};
  char evento_[24] = {};
  char datos_[1024] = {};
  size_t usadosLinea_ = 0;
  size_t usadosDatos_ = 0;
  bool tieneDatos_ = false;
  bool descartar_ = false;
  bool lineaExcedida_ = false;
  bool retorno_ = false;
  EventoSse finalizarLinea();
  EventoSse interpretarEvento();
};

}  // namespace cava
