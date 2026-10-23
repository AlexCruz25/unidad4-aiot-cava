#include "sse_parser.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <cJSON.h>

namespace cava {
namespace {

bool copiar(const char* texto, char* salida, size_t capacidad) {
  const size_t longitud = strlen(texto);
  if (longitud >= capacidad) return false;
  memcpy(salida, texto, longitud + 1);
  return true;
}

char* recortar(char* texto) {
  while (*texto == ' ' || *texto == '\t') ++texto;
  size_t longitud = strlen(texto);
  while (longitud && (texto[longitud - 1] == ' ' || texto[longitud - 1] == '\t')) {
    texto[--longitud] = '\0';
  }
  return texto;
}

bool profundidadValida(const char* json) {
  unsigned profundidad = 0;
  bool cadena = false;
  bool escape = false;
  for (const char* cursor = json; *cursor; ++cursor) {
    const char c = *cursor;
    if (cadena) {
      if (escape) escape = false;
      else if (c == '\\') escape = true;
      else if (c == '"') cadena = false;
    } else if (c == '"') {
      cadena = true;
    } else if (c == '{' || c == '[') {
      if (++profundidad > 8) return false;
    } else if ((c == '}' || c == ']') && profundidad) {
      --profundidad;
    }
  }
  return true;  // La sintaxis completa la comprueba cJSON.
}

}  // namespace

bool interpretarUrlHttps(const char* url, DestinoHttps& destino) {
  if (!url || strlen(url) >= MAX_URL_SSE || strncasecmp(url, "https://", 8) != 0) return false;
  for (const char* p = url; *p; ++p) {
    if (static_cast<unsigned char>(*p) <= 32 || *p == '\\' || *p == '#') return false;
  }
  const char* autoridad = url + 8;
  const char* fin = autoridad + strcspn(autoridad, "/?");
  const char* puerto = static_cast<const char*>(memchr(autoridad, ':', fin - autoridad));
  const size_t longitudHost = (puerto ? puerto : fin) - autoridad;
  if (longitudHost == 0 || longitudHost >= sizeof(destino.host)) return false;
  if (puerto && (fin - puerto != 4 || strncmp(puerto, ":443", 4) != 0)) return false;
  for (size_t i = 0; i < longitudHost; ++i) {
    const unsigned char c = autoridad[i];
    if (!isalnum(c) && c != '.' && c != '-') return false;
  }
  memcpy(destino.host, autoridad, longitudHost);
  destino.host[longitudHost] = '\0';
  if (*fin == '/') return copiar(fin, destino.recurso, sizeof(destino.recurso));
  const int escritos = snprintf(destino.recurso, sizeof(destino.recurso), "/%s", fin);
  return escritos > 0 && static_cast<size_t>(escritos) < sizeof(destino.recurso);
}

bool resolverLocation(const char* origen, const char* location, char* salida, size_t capacidad) {
  if (!location || !*location || strlen(location) >= MAX_URL_SSE) return false;
  DestinoHttps base;
  if (!interpretarUrlHttps(origen, base)) return false;
  int escritos;
  if (strncasecmp(location, "https://", 8) == 0) {
    if (!copiar(location, salida, capacidad)) return false;
  } else if (strncmp(location, "//", 2) == 0) {
    escritos = snprintf(salida, capacidad, "https:%s", location);
    if (escritos < 0 || static_cast<size_t>(escritos) >= capacidad) return false;
  } else {
    // No se admite una degradación a HTTP ni otro esquema en Location.
    if (strchr(location, ':')) return false;
    char* consulta = strchr(base.recurso, '?');
    if (consulta) *consulta = '\0';
    if (location[0] == '/') base.recurso[0] = '\0';
    else if (location[0] != '?') {
      char* barra = strrchr(base.recurso, '/');
      if (barra) barra[1] = '\0';
    }
    escritos = snprintf(salida, capacidad, "https://%s%s%s", base.host, base.recurso, location);
    if (escritos < 0 || static_cast<size_t>(escritos) >= capacidad) return false;
  }
  DestinoHttps comprobado;
  return interpretarUrlHttps(salida, comprobado);
}

void CabecerasSse::reiniciar() { *this = CabecerasSse{}; }

bool CabecerasSse::consumir(char byte) {
  if (completas_) return false;
  if (++total_ > 4096 || byte == '\0') return false;
  if (byte == '\n') {
    if (usados_ && linea_[usados_ - 1] == '\r') --usados_;
    linea_[usados_] = '\0';
    const bool valido = finalizarLinea();
    usados_ = 0;
    return valido;
  }
  if (usados_ + 1 >= sizeof(linea_)) return false;
  linea_[usados_++] = byte;
  return true;
}

bool CabecerasSse::finalizarLinea() {
  if (primera_) {
    primera_ = false;
    if (strlen(linea_) < 12 ||
        (strncmp(linea_, "HTTP/1.1 ", 9) != 0 && strncmp(linea_, "HTTP/1.0 ", 9) != 0)) return false;
    for (size_t i = 9; i < 12; ++i) if (linea_[i] < '0' || linea_[i] > '9') return false;
    if (linea_[12] != '\0' && linea_[12] != ' ') return false;
    codigo_ = (linea_[9] - '0') * 100 + (linea_[10] - '0') * 10 + linea_[11] - '0';
    return true;
  }
  if (!*linea_) {
    completas_ = true;
    return true;
  }
  char* separador = strchr(linea_, ':');
  if (!separador) return false;
  *separador = '\0';
  const char* valor = recortar(separador + 1);
  if (strcasecmp(linea_, "Location") == 0) {
    if (tieneLocation_ || !copiar(valor, location_, sizeof(location_))) return false;
    tieneLocation_ = true;
  } else if (strcasecmp(linea_, "Content-Type") == 0) {
    streaming_ = strncasecmp(valor, "text/event-stream", 17) == 0 &&
                 (valor[17] == '\0' || valor[17] == ';' || valor[17] == ' ');
  } else if (strcasecmp(linea_, "Transfer-Encoding") == 0) {
    if (strcasecmp(valor, "chunked") == 0) chunked_ = true;
    else if (strcasecmp(valor, "identity") != 0) return false;
  } else if (strcasecmp(linea_, "Content-Encoding") == 0) {
    if (strcasecmp(valor, "identity") != 0) return false;
  }
  return true;
}

void CuerpoSse::reiniciar(bool chunked) {
  *this = CuerpoSse{};
  chunked_ = chunked;
}

ByteHttp CuerpoSse::consumir(char byte, char& dato) {
  if (!chunked_) {
    dato = byte;
    return ByteHttp::Dato;
  }
  if (estado_ == Estado::Fin) return ByteHttp::Fin;
  if (estado_ == Estado::Datos) {
    dato = byte;
    if (--pendientes_ == 0) estado_ = Estado::Retorno;
    return ByteHttp::Dato;
  }
  if (estado_ == Estado::Retorno) {
    if (byte != '\r') return ByteHttp::Error;
    estado_ = Estado::Salto;
  } else if (estado_ == Estado::Salto) {
    if (byte != '\n') return ByteHttp::Error;
    estado_ = Estado::Tamano;
  } else if (byte == '\n') {
    if (usados_ == 0 || linea_[usados_ - 1] != '\r') return ByteHttp::Error;
    linea_[--usados_] = '\0';
    size_t digitos = 0;
    pendientes_ = 0;
    for (; digitos < usados_ && linea_[digitos] != ';'; ++digitos) {
      const unsigned char c = linea_[digitos];
      const int valor = c >= '0' && c <= '9' ? c - '0' :
                        c >= 'a' && c <= 'f' ? c - 'a' + 10 :
                        c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
      if (valor < 0 || digitos >= 8 || pendientes_ > 0x0fffffffUL) return ByteHttp::Error;
      pendientes_ = pendientes_ * 16 + valor;
    }
    if (!digitos) return ByteHttp::Error;
    usados_ = 0;
    if (pendientes_ == 0) {
      estado_ = Estado::Fin;  // No hacen falta los trailers para cerrar el stream.
      return ByteHttp::Fin;
    }
    estado_ = Estado::Datos;
  } else {
    if (usados_ + 1 >= sizeof(linea_)) return ByteHttp::Error;
    linea_[usados_++] = byte;
  }
  return ByteHttp::SinDato;
}

void ParserSse::reiniciar() { *this = ParserSse{}; }

EventoSse ParserSse::consumir(char byte) {
  if (byte == '\n' && retorno_) {
    retorno_ = false;
    return {};
  }
  retorno_ = byte == '\r';
  if (byte == '\n' || byte == '\r') return finalizarLinea();
  if (byte == '\0' || usadosLinea_ + 1 >= sizeof(linea_)) {
    descartar_ = lineaExcedida_ = true;
  } else if (!lineaExcedida_) {
    linea_[usadosLinea_++] = byte;
  }
  return {};
}

EventoSse ParserSse::finalizarLinea() {
  linea_[usadosLinea_] = '\0';
  const bool vacia = usadosLinea_ == 0 && !lineaExcedida_;
  usadosLinea_ = 0;
  lineaExcedida_ = false;
  if (vacia) {
    EventoSse resultado = descartar_ ? EventoSse{TipoSse::Error, false, "Evento SSE excedido o invalido; descartado"}
                                   : interpretarEvento();
    evento_[0] = datos_[0] = '\0';
    usadosDatos_ = 0;
    tieneDatos_ = descartar_ = false;
    return resultado;
  }
  if (descartar_ || linea_[0] == ':') return {};
  char* separador = strchr(linea_, ':');
  char* valor = linea_ + strlen(linea_);
  if (separador) {
    *separador = '\0';
    valor = separador + 1;
    if (*valor == ' ') ++valor;
  }
  if (strcmp(linea_, "event") == 0) {
    if (!copiar(valor, evento_, sizeof(evento_))) descartar_ = true;
  } else if (strcmp(linea_, "data") == 0) {
    const size_t longitud = strlen(valor);
    const size_t separacion = tieneDatos_ ? 1 : 0;
    if (usadosDatos_ + separacion + longitud >= sizeof(datos_)) {
      descartar_ = true;
    } else {
      if (separacion) datos_[usadosDatos_++] = '\n';
      memcpy(datos_ + usadosDatos_, valor, longitud + 1);
      usadosDatos_ += longitud;
      tieneDatos_ = true;
    }
  }
  return {};
}

EventoSse ParserSse::interpretarEvento() {
  if (!*evento_) return {};
  if (strcmp(evento_, "keep-alive") == 0) return {TipoSse::KeepAlive};
  if (strcmp(evento_, "cancel") == 0) return {TipoSse::Cancel};
  if (strcmp(evento_, "auth_revoked") == 0) return {TipoSse::AuthRevoked};
  if (strcmp(evento_, "put") != 0 && strcmp(evento_, "patch") != 0) return {};
  if (!tieneDatos_ || !profundidadValida(datos_) || strstr(datos_, "\\u0000")) {
    return {TipoSse::Error, false, "JSON SSE ausente o fuera de limites"};
  }
  cJSON* raiz = cJSON_ParseWithLengthOpts(datos_, usadosDatos_ + 1, nullptr, 1);
  const cJSON* path = cJSON_GetObjectItemCaseSensitive(raiz, "path");
  const cJSON* dato = cJSON_GetObjectItemCaseSensitive(raiz, "data");
  const bool valido = cJSON_IsObject(raiz) && cJSON_GetArraySize(raiz) == 2 &&
                      cJSON_IsString(path) && strcmp(path->valuestring, "/") == 0 && cJSON_IsBool(dato);
  const bool encender = valido && cJSON_IsTrue(dato);
  cJSON_Delete(raiz);
  if (!valido) return {TipoSse::Error, false, "Orden invalida: se exige path / y data booleano"};
  return {TipoSse::Orden, encender};
}

}  // namespace cava
