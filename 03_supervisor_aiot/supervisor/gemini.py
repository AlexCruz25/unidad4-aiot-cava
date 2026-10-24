import asyncio
import json
import re

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from .config import Settings
from .models import Decision, GeminiAssessment, Measurement


class GeminiFailure(Exception):
    """Diagnóstico controlado: nunca conserva mensajes/respuestas del proveedor."""

    def __init__(self, reason: str, *, exception_type: str = "GeminiFailure", http_code: int | None = None):
        super().__init__(reason)
        self.exception_type = exception_type
        self.http_code = http_code
        self.cause, self.advice = DIAGNOSTICS.get(reason, DIAGNOSTICS["error_implementacion_python"])


DIAGNOSTICS = {
    "sin_api_key": ("No hay una API key configurada.", "Completar GEMINI_API_KEY en 03_supervisor_aiot/.env."),
    "autenticacion": ("La API rechazó la autenticación.", "Revisar vigencia y configuración de GEMINI_API_KEY en AI Studio."),
    "permisos": ("La API denegó el acceso al servicio o recurso.", "Revisar permisos, restricciones de la key y servicio habilitado en el proyecto."),
    "cuota_429": ("La API informó cuota o límite de solicitudes agotado.", "Revisar cuota, límites y facturación del proyecto; respetar el backoff configurado."),
    "modelo_no_disponible_para_esta_key": ("El modelo configurado no figura con generateContent para esta key.", "Revisar --list-models y GEMINI_MODEL; conservar auto si corresponde."),
    "sin_modelo_flash_estable_configurar_GEMINI_MODEL": ("No se encontró un modelo Flash estable con generateContent.", "Revisar --list-models y la disponibilidad de modelos para el proyecto."),
    "modelo_no_disponible": ("La API no encontró el modelo o endpoint solicitado.", "Revisar --list-models, disponibilidad del modelo y versión de la API."),
    "schema_api_rechazado": ("La API rechazó un campo del schema de respuesta; no es un error de autenticación.", "Usar response_json_schema con GeminiAssessment.model_json_schema(); revisar la serialización del SDK."),
    "salida_estructurada_no_compatible": ("La API indicó que la salida JSON/schema no es compatible con este modelo.", "Verificar soporte estructurado del modelo antes de elegir otro Flash-Lite disponible con --list-models."),
    "parametros_solicitud_invalidos": ("La API rechazó los parámetros de la solicitud (HTTP 400).", "Revisar configuración generate_content, schema y compatibilidad con la versión de la API."),
    "servicio_gemini_no_disponible": ("El servicio Gemini devolvió un error del servidor.", "Revisar disponibilidad del servicio; respetar los tiempos de recuperación configurados."),
    "error_api": ("La API devolvió un error HTTP no clasificado.", "Revisar estado del servicio, parámetros y configuración del proyecto según el código HTTP."),
    "timeout": ("La operación superó el tiempo de espera.", "Revisar conectividad y GEMINI_TIMEOUT_SECONDS; no reintentar en un bucle."),
    "conectividad": ("Falló el transporte de red, DNS o TLS.", "Revisar acceso HTTPS a generativelanguage.googleapis.com, DNS, proxy y certificados."),
    "respuesta_estructurada_invalida": ("La respuesta no cumple el JSON/Pydantic estricto del supervisor.", "Revisar los tres campos, booleanos estrictos y longitud de impacto_enologico; conservar la validación."),
    "respuesta_truncada": ("La generación terminó por límite de tokens.", "Revisar max_output_tokens y la extensión solicitada; no aceptar JSON incompleto."),
    "respuesta_vacia_o_bloqueada": ("Gemini no devolvió texto utilizable o bloqueó la respuesta.", "Revisar el prompt y los filtros de seguridad del modelo."),
    "configuracion_invalida": ("No se pudo cargar o validar la configuración local.", "Revisar nombres y formatos en .env y variables exportadas; no publicar sus valores."),
    "comprobacion_firebase_fallida": ("Falló la comprobación explícita de Firebase.", "Revisar credenciales y permisos Firebase; la prueba de Gemini no requiere --check-firebase."),
    "error_implementacion_python": ("Falló la preparación o ejecución local Python/SDK.", "Revisar la implementación y las versiones de requirements.txt; ejecutar pytest sin consumir API."),
}


def diagnose_failure(error: Exception, *, phase: str = "solicitud") -> GeminiFailure:
    """Inspecciona mensajes solo para clasificar; nunca los copia al diagnóstico."""
    if isinstance(error, GeminiFailure):
        return error
    code = error.code if isinstance(error, errors.APIError) and isinstance(error.code, int) else None
    if phase == "configuracion":
        reason = "configuracion_invalida"
    elif phase == "firebase":
        reason = "comprobacion_firebase_fallida"
    elif isinstance(error, (TimeoutError, httpx.TimeoutException)):
        reason = "timeout"
    elif isinstance(error, errors.APIError):
        message = (error.message or "").lower()
        # La API también informa claves inválidas mediante HTTP 400.
        details = str(error.details).lower()
        schema = any(term in message for term in (
            "response_schema", "responseschema", "response_json_schema", "responsejsonschema",
            "response_mime_type", "responsemimetype", "structured output", "json mode",
        ))
        if code == 401 or any(term in details for term in ("api_key_invalid", "api_key_expired")) or any(
            term in message for term in ("api key not valid", "api key expired", "invalid api key")
        ):
            reason = "autenticacion"
        elif code == 403:
            reason = "permisos"
        elif code == 429:
            reason = "cuota_429"
        elif code == 404:
            reason = "modelo_no_disponible"
        elif code == 400 and schema and any(term in message for term in ("not supported", "unsupported", "not compatible")):
            reason = "salida_estructurada_no_compatible"
        elif code == 400 and schema:
            reason = "schema_api_rechazado"
        elif code == 400:
            reason = "parametros_solicitud_invalidos"
        elif code is not None and code >= 500:
            reason = "servicio_gemini_no_disponible"
        else:
            reason = "error_api"
    elif isinstance(error, ValidationError) and phase == "respuesta":
        reason = "respuesta_estructurada_invalida"
    elif isinstance(error, (httpx.RequestError, OSError)):
        reason = "conectividad"
    else:
        reason = "error_implementacion_python"
    return GeminiFailure(reason, exception_type=type(error).__name__, http_code=code)


def select_model(models: list, configured: str) -> str:
    names = [m.name.removeprefix("models/") for m in models
             if m.name and "generateContent" in (m.supported_actions or [])]
    if configured != "auto":
        name = configured.removeprefix("models/")
        if name not in names:
            raise GeminiFailure("modelo_no_disponible_para_esta_key")
        return name
    candidates = [name for name in names if "flash" in name and not any(
        tag in name for tag in ("image", "tts", "live", "preview", "experimental", "-exp")
    )]
    if not candidates:
        raise GeminiFailure("sin_modelo_flash_estable_configurar_GEMINI_MODEL")
    return max(candidates, key=lambda name: ("flash-lite" in name, tuple(map(int, re.findall(r"\d+", name)))))


class GeminiAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = None
        self.model: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.gemini_api_key)

    def get_client(self):
        if not self.configured:
            raise GeminiFailure("sin_api_key")
        if self.client is None:
            self.client = genai.Client(
                api_key=self.settings.gemini_api_key.get_secret_value(),
                http_options=types.HttpOptions(
                    timeout=int(self.settings.gemini_timeout_seconds * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self.client

    async def list_models(self) -> list:
        try:
            async with asyncio.timeout(self.settings.gemini_timeout_seconds):
                pager = await self.get_client().aio.models.list(config={"page_size": 100})
                return [model async for model in pager]
        except Exception as error:
            raise diagnose_failure(error) from None

    async def resolve_model(self) -> str:
        if self.model is None:
            self.model = select_model(await self.list_models(), self.settings.gemini_model)
        return self.model

    async def analyze(self, sample: Measurement, decision: Decision) -> GeminiAssessment:
        phase = "solicitud"
        try:
            async with asyncio.timeout(self.settings.gemini_timeout_seconds):
                await self.resolve_model()
                response = await self.get_client().aio.models.generate_content(
                    model=self.model,
                    contents=json.dumps({
                        "temperatura_c": sample.temperatura, "humedad_porcentaje": sample.humedad,
                        "reglas_python": decision.model_dump(),
                    }, ensure_ascii=False),
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "Sos un asistente de análisis enológico de una cava de crianza de vino en barricas. "
                            "Explicá en español, brevemente y con cautela, el posible efecto de temperatura y humedad "
                            "sobre crianza, conservación y barricas. No diagnostiques daños confirmados a partir de una muestra. "
                            "Ideal: 12 a 18 °C y 65 a 80 %. Mitigar si T>22 °C o HR<60 %. "
                            "Respetá la histéresis y la decisión Python recibida. Devolvé únicamente los tres campos del schema. "
                            "No ejecutes código, herramientas, órdenes ni operaciones Firebase."
                        ),
                        # response_schema convierte extra=forbid a additional_properties,
                        # rechazado por este endpoint. JSON Schema conserva additionalProperties.
                        response_mime_type="application/json",
                        response_json_schema=GeminiAssessment.model_json_schema(),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                        max_output_tokens=600, temperature=0.2,
                    ),
                )
                candidates = getattr(response, "candidates", None)
                if candidates and candidates[0].finish_reason == types.FinishReason.MAX_TOKENS:
                    raise GeminiFailure("respuesta_truncada")
                if not response.text:
                    raise GeminiFailure("respuesta_vacia_o_bloqueada")
                phase = "respuesta"
                return GeminiAssessment.model_validate_json(response.text)
        except GeminiFailure:
            raise
        except Exception as error:
            raise diagnose_failure(error, phase=phase) from None

    async def close(self) -> None:
        if self.client is not None:
            client, self.client = self.client, None
            try:
                await client.aio.aclose()
            finally:
                await asyncio.to_thread(client.close)
