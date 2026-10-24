// Compilar junto a cava_esp32/firebase_ack.cpp, incluyendo -Icava_esp32.
#include "firebase_ack.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>
#include <stdint.h>

int main() {
  EstadoAck ack;
  ConfirmacionActuador enviada;
  assert(!ack.preparar(0, enviada));  // Espera una orden aplicada, no publica al arrancar.
  ack.registrar(false);
  assert(ack.preparar(0, enviada) && !enviada.encender);
  ack.resolver(enviada, 200, 1);
  assert(!ack.preparar(1, enviada));

  // La instantánea inicial de cada conexión se confirma aunque GPIO ya coincida.
  const uint64_t inicial = enviada.version;
  ack.registrar(false);
  assert(ack.preparar(2, enviada) && enviada.version != inicial);
  ack.resolver(enviada, 200, 3);

  ack.registrar(true);
  assert(ack.preparar(4, enviada) && enviada.encender);
  const auto antigua = enviada;
  ack.registrar(false);
  ack.registrar(true);  // También protege true -> false -> true durante un PUT.
  ack.resolver(antigua, 200, 5);
  assert(ack.preparar(5, enviada) && enviada.encender);
  assert(enviada.version != antigua.version);
  ack.resolver(antigua, 403, 5);  // Un fallo antiguo tampoco retrasa la orden nueva.
  assert(ack.preparar(5, enviada));
  ack.resolver(enviada, 200, 6);
  assert(!ack.preparar(6, enviada));

  for (int error : {-1, 0, 204, 400, 401, 403, 500}) {
    ack.registrar(false);
    assert(ack.preparar(100, enviada));
    ack.resolver(enviada, error, 100);
    const uint32_t espera = (error == 401 || error == 403) ? 60000U : 5000U;
    assert(!ack.preparar(100 + espera - 1, enviada));
    assert(ack.preparar(100 + espera, enviada) && !enviada.encender);
    ack.resolver(enviada, 200, 100 + espera);
    assert(!ack.preparar(100 + espera, enviada));
  }

  ack.registrar(false);
  assert(ack.preparar(100, enviada));
  ack.resolver(enviada, -1, 100);
  ack.registrar(true);  // Nueva orden durante la espera: objetivo nuevo inmediato.
  assert(ack.preparar(101, enviada) && enviada.encender);

  const uint32_t antesDelDesborde = UINT32_MAX - 1000;
  ack.resolver(enviada, -1, antesDelDesborde);
  assert(!ack.preparar(3998, enviada));
  assert(ack.preparar(3999, enviada));
  ack.resolver(enviada, 200, 4000);
  assert(!ack.preparar(4000, enviada));
  puts("OK: sincronizacion, versiones, fallos HTTP, reintentos y desborde de millis()");
}
