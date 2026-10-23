#pragma once

/* PASO 5: una tarea y un cliente TLS exclusivos para el stream de Firebase. */
#include <stddef.h>
#include <stdint.h>
#include <time.h>

struct ConfiguracionSse {
  const char* url;
  const char* ca;
  time_t horaMinima;
  int32_t timeoutConexionMs;
  uint16_t timeoutHttpMs;
  unsigned long timeoutTlsSegundos;
};

bool iniciarSse(const ConfiguracionSse& configuracion);
bool recibirOrdenSse(bool& encender);
bool recibirAvisoSse(char* texto, size_t capacidad);
