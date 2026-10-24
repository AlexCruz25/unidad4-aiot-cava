#pragma once

#include <stdint.h>

struct ConfirmacionActuador {
  bool encender = false;
  uint64_t version = 0;
};

// Solo loop() modifica este estado. La tarea HTTPS recibe copias por cola.
class EstadoAck {
 public:
  void registrar(bool encender);
  bool preparar(uint32_t ahora, ConfirmacionActuador& confirmacion) const;
  void resolver(const ConfirmacionActuador& enviada, int codigoHttp, uint32_t ahora);

 private:
  ConfirmacionActuador objetivo_;
  bool pendiente_ = false;
  bool esperandoReintento_ = false;
  uint32_t ultimoFallo_ = 0;
  uint32_t espera_ = 5000;
};
