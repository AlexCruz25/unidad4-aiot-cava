#pragma once

#include <time.h>

// SOLO para aislar fallos en la placa. La versión completa usa ambos en 0.
// Se pueden sobrescribir con -D desde Arduino CLI o cambiar aquí en el IDE.
#ifndef CAVA_DIAG_SIN_SSE
#define CAVA_DIAG_SIN_SSE 0
#endif
#ifndef CAVA_DIAG_SIN_ACK
#define CAVA_DIAG_SIN_ACK 0
#endif

#if (CAVA_DIAG_SIN_SSE != 0 && CAVA_DIAG_SIN_SSE != 1) || \
    (CAVA_DIAG_SIN_ACK != 0 && CAVA_DIAG_SIN_ACK != 1)
#error "Las opciones de diagnostico deben ser 0 o 1"
#endif
#if CAVA_DIAG_SIN_SSE && CAVA_DIAG_SIN_ACK
#error "Aislar un componente por vez: no desactivar SSE y ACK juntos"
#endif

void iniciarDiagnosticoRed();
void diagnosticarHeap(const char* operacion, const char* fase);
void diagnosticarRed(const char* operacion, time_t horaMinima);
// Solo desde tareas de red: hostByName puede esperar al resolvedor, nunca en loop().
void diagnosticarDns(const char* operacion, const char* host);
