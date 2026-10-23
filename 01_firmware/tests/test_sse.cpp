// Pruebas de protocolo en PC; no abren conexiones ni utilizan secrets.h.
#include "sse_parser.h"
#include <cassert>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

using namespace cava;

std::vector<EventoSse> alimentar(ParserSse& parser, const std::string& texto) {
  std::vector<EventoSse> eventos;
  for (char byte : texto) {
    const auto evento = parser.consumir(byte);
    if (evento.tipo != TipoSse::Ninguno) eventos.push_back(evento);
  }
  return eventos;
}

void exigirError(const std::string& json) {
  ParserSse parser;
  const auto eventos = alimentar(parser, "event: put\ndata: " + json + "\n\n");
  assert(eventos.size() == 1 && eventos[0].tipo == TipoSse::Error);
}

int main() {
  ParserSse parser;
  assert(alimentar(parser, "event: put\ndata: {\"path\":\"/\",\"data\":false}\n").empty());
  auto eventos = alimentar(parser, "\n");
  assert(eventos.size() == 1 && eventos[0].tipo == TipoSse::Orden && !eventos[0].encender);
  eventos = alimentar(parser, "event: put\r\ndata: {\"path\":\"/\",\"data\":true}\r\n\r\n");
  assert(eventos.size() == 1 && eventos[0].tipo == TipoSse::Orden && eventos[0].encender);
  eventos = alimentar(parser, "event: patch\rdata: {\"path\":\"/\",\"data\":false}\r\r");
  assert(eventos.size() == 1 && eventos[0].tipo == TipoSse::Orden && !eventos[0].encender);
  eventos = alimentar(parser, ": comentario\nevent: patch\ndata: {\"path\":\"/\",\ndata: \"data\":true}\n\n");
  assert(eventos.size() == 1 && eventos[0].tipo == TipoSse::Orden && eventos[0].encender);
  std::cout << "OK: put/patch, estado inicial, LF/CR/CRLF, datos multilinea y evento incompleto\n";

  eventos = alimentar(parser, "event: keep-alive\ndata: null\n\nevent: cancel\ndata: null\n\n"
                             "event: auth_revoked\ndata: \"expired\"\n\n");
  assert(eventos.size() == 3);
  assert(eventos[0].tipo == TipoSse::KeepAlive);
  assert(eventos[1].tipo == TipoSse::Cancel);
  assert(eventos[2].tipo == TipoSse::AuthRevoked);
  for (const auto& json : {
      "null", "true", "[]", "{}", "{\"path\":\"/\",\"data\":null}",
      "{\"path\":\"/\",\"data\":1}", "{\"path\":\"/\",\"data\":\"true\"}",
      "{\"path\":\"/\",\"data\":{\"x\":true}}", "{\"data\":true}",
      "{\"path\":\"/otro\",\"data\":true}", "{\"path\":\"/\",\"data\":false,\"extra\":\"true\"}",
      "{\"path\":\"/\",\"data\":false,\"data\":true}",
      "{\"path\":\"/\\u0000otro\",\"data\":true}",
      "{\"path\":\"/\",\"data\":true} basura", "{json roto}"}) exigirError(json);
  exigirError("{\"path\":\"/\",\"data\":" + std::string(20, '[') + "true" + std::string(20, ']') + "}");
  std::cout << "OK: keep-alive/cancel/auth_revoked y rechazo estricto de JSON, null y tipos no booleanos\n";

  eventos = alimentar(parser, "event: put\ndata: " + std::string(2000, 'x') + "\n\n"
                             "event: put\ndata: {\"path\":\"/\",\"data\":true}\n\n");
  assert(eventos.size() == 2 && eventos[0].tipo == TipoSse::Error && eventos[1].tipo == TipoSse::Orden);
  std::string muchosDatos = "event: put\n";
  for (int i = 0; i < 8; ++i) muchosDatos += "data: " + std::string(200, 'x') + "\n";
  eventos = alimentar(parser, muchosDatos + "\n");
  assert(eventos.size() == 1 && eventos[0].tipo == TipoSse::Error);
  std::cout << "OK: límites de línea/evento y recuperación tras descartar un evento excedido\n";

  const std::string sse = "event: put\ndata: {\"path\":\"/\",\"data\":true}\n\n"
                          "event: patch\ndata: {\"path\":\"/\",\"data\":false}\n\n";
  for (size_t tamano : {1U, 2U, 13U, 1024U}) {
    std::string cuerpo;
    for (size_t i = 0; i < sse.size(); i += tamano) {
      const auto parte = sse.substr(i, tamano);
      char cabecera[64];
      snprintf(cabecera, sizeof(cabecera), "%zx;extension=ok\r\n", parte.size());
      cuerpo += cabecera + parte + "\r\n";
    }
    cuerpo += "0\r\n\r\n";
    const std::string respuesta = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\n"
                                  "Transfer-Encoding: chunked\r\n\r\n" + cuerpo;
    CabecerasSse cabeceras;
    CuerpoSse decodificador;
    ParserSse incremental;
    std::vector<EventoSse> recibidos;
    bool terminado = false;
    for (char byte : respuesta) {
      if (!cabeceras.completas()) {
        assert(cabeceras.consumir(byte));
        if (cabeceras.completas()) {
          assert(cabeceras.codigo() == 200 && cabeceras.esStreaming() && cabeceras.esChunked());
          decodificador.reiniciar(true);
        }
      } else if (!terminado) {
        char dato;
        const auto resultado = decodificador.consumir(byte, dato);
        assert(resultado != ByteHttp::Error);
        terminado = resultado == ByteHttp::Fin;
        if (resultado == ByteHttp::Dato) {
          const auto evento = incremental.consumir(dato);
          if (evento.tipo != TipoSse::Ninguno) recibidos.push_back(evento);
        }
      }
    }
    assert(terminado && recibidos.size() == 2 && recibidos[0].encender && !recibidos[1].encender);
  }
  CuerpoSse defectuoso;
  defectuoso.reiniciar(true);
  char dato;
  assert(defectuoso.consumir('Z', dato) == ByteHttp::SinDato);
  assert(defectuoso.consumir('\r', dato) == ByteHttp::SinDato);
  assert(defectuoso.consumir('\n', dato) == ByteHttp::Error);
  std::cout << "OK: respuesta HTTP/SSE fragmentada byte a byte y chunked con eventos entre chunks\n";

  CabecerasSse redireccion;
  for (char byte : std::string("HTTP/1.1 307 Temporary Redirect\r\nLocation: https://s-1.firebaseio.com/control.json?ns=cava\r\n\r\n")) {
    assert(redireccion.consumir(byte));
  }
  assert(redireccion.completas() && redireccion.codigo() == 307);
  const char* origen = "https://cava.firebaseio.com/control/orden.json";
  char url[MAX_URL_SSE];
  assert(resolverLocation(origen, redireccion.location(), url, sizeof(url)));
  assert(std::string(url) == "https://s-1.firebaseio.com/control.json?ns=cava");
  assert(resolverLocation(origen, "/nuevo.json", url, sizeof(url)));
  assert(std::string(url) == "https://cava.firebaseio.com/nuevo.json");
  assert(resolverLocation(origen, "//otro.firebaseio.com/a.json", url, sizeof(url)));
  assert(std::string(url) == "https://otro.firebaseio.com/a.json");
  assert(resolverLocation(origen, "?ns=cava", url, sizeof(url)));
  assert(std::string(url) == "https://cava.firebaseio.com/control/orden.json?ns=cava");
  assert(!resolverLocation(origen, "http://cava.firebaseio.com/a", url, sizeof(url)));
  assert(!resolverLocation(origen, "https://usuario@cava.firebaseio.com/a", url, sizeof(url)));
  assert(!resolverLocation(origen, "https://cava.firebaseio.com:80/a", url, sizeof(url)));
  assert(!resolverLocation(origen, "/a\r\nHost: otro", url, sizeof(url)));
  assert(!resolverLocation(origen, "", url, sizeof(url)));
  DestinoHttps destino;
  assert(interpretarUrlHttps("https://cava.firebaseio.com:443/a.json", destino));
  assert(std::string(destino.host) == "cava.firebaseio.com" && std::string(destino.recurso) == "/a.json");
  CabecerasSse demasiadoGrande;
  bool valido = true;
  for (char byte : "HTTP/1.1 200 OK\r\nX: " + std::string(2000, 'x')) {
    if (!demasiadoGrande.consumir(byte)) { valido = false; break; }
  }
  assert(!valido);
  std::cout << "OK: HTTP 307, Location HTTPS absoluta/relativa y rechazo de destinos inseguros/cabeceras excedidas\n";
}
