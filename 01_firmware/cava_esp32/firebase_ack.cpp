#include "firebase_ack.h"

void EstadoAck::registrar(bool encender) {
  objetivo_.encender = encender;
  ++objetivo_.version;
  pendiente_ = true;
  esperandoReintento_ = false;
}

bool EstadoAck::preparar(uint32_t ahora, ConfirmacionActuador& confirmacion) const {
  if (!pendiente_ ||
      (esperandoReintento_ && static_cast<uint32_t>(ahora - ultimoFallo_) < espera_)) {
    return false;
  }
  confirmacion = objetivo_;
  return true;
}

void EstadoAck::resolver(const ConfirmacionActuador& enviada, int codigoHttp, uint32_t ahora) {
  // Ni el éxito ni el fallo de una versión vieja alteran el objetivo actual.
  if (enviada.version != objetivo_.version) return;
  if (codigoHttp == 200) {
    pendiente_ = false;
    esperandoReintento_ = false;
    return;
  }
  pendiente_ = true;
  esperandoReintento_ = true;
  ultimoFallo_ = ahora;
  espera_ = (codigoHttp == 401 || codigoHttp == 403) ? 60000U : 5000U;
}
