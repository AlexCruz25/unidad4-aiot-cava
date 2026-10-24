from datetime import datetime, timezone
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Measurement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    temperatura: float = Field(ge=-40, le=80)
    humedad: float = Field(ge=0, le=100)
    timestamp: datetime

    @field_validator("temperatura", "humedad", mode="before")
    @classmethod
    def physical_number(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("La medición debe ser un número finito, no booleano ni string")
        return value

    @field_validator("timestamp", mode="before")
    @classmethod
    def timestamp_format(cls, value):
        if isinstance(value, bool):
            raise ValueError("Timestamp booleano inválido")
        if isinstance(value, (int, float)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Timestamp inválido")
            try:
                value = datetime.fromtimestamp(value / 1000 if value > 100_000_000_000 else value, timezone.utc)
            except (OverflowError, OSError, ValueError) as error:
                raise ValueError("Timestamp fuera de rango") from error
        elif isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("Timestamp ISO inválido") from error
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("Timestamp ausente o sin zona horaria")
        return value.astimezone(timezone.utc)

    def check_fresh(self, now: datetime, max_age: float, future_tolerance: float) -> None:
        age = (now - self.timestamp).total_seconds()
        if age > max_age:
            raise ValueError("Medición antigua: no emitir una orden nueva")
        if age < -future_tolerance:
            raise ValueError("Medición futura: revisar relojes")


class ControlState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    extractor_solicitado: StrictBool
    origen: StrictStr = "desconocido"


class GeminiAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    alerta_calidad: StrictBool
    forzar_climatizacion: StrictBool
    impacto_enologico: str = Field(min_length=20, max_length=900)

    @field_validator("impacto_enologico")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 20:
            raise ValueError("Explicación demasiado breve")
        return value


class Decision(BaseModel):
    estado: Literal["critico", "recuperando", "fuera_ideal", "normal"]
    anomalias: list[str]
    alerta_calidad: bool
    forzar_climatizacion: bool
    accion: bool | None = None
    motivo: str
    segundos_estables: float = 0


class AIReport(BaseModel):
    estado: Literal["disponible", "no_disponible", "pendiente", "limitado"]
    motivo: str = ""
    modelo: str | None = None
    evaluacion: GeminiAssessment | None = None
    muestra: Measurement | None = None


class Evaluation(BaseModel):
    fecha: datetime
    muestra: Measurement
    control: ControlState
    decision: Decision
    ia: AIReport
    accion_resultado: str
    publicacion: str = "pendiente"


class HealthResponse(BaseModel):
    servidor: str = "activo"
    estado: str
    dry_run: bool
    firebase_configurado: bool
    firebase_ultima_lectura_correcta: bool
    listener_activo: bool
    datos_recientes: bool
    gemini_configurado: bool
    problema: str | None = None


class StatusResponse(BaseModel):
    health: HealthResponse
    ultima_evaluacion: Evaluation | None
    ultima_comunicacion_valida: datetime | None
    ultimo_evento: datetime | None
    ultima_muestra_valida: datetime | None
    llamadas_gemini: int
    modelo_gemini: str | None
    evaluacion_ia_en_curso: bool


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # No se admiten mediciones enviadas por el cliente: se leen de Firebase.
