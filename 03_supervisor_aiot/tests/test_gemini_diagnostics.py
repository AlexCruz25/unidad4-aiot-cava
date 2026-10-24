"""Regresiones de serialización y diagnóstico. Transportes locales; sin API real."""
import json

import httpx
import pytest
from google import genai
from google.genai import errors, types
from pydantic import SecretStr

from supervisor.config import Settings
from supervisor.gemini import GeminiAnalyzer, GeminiFailure, diagnose_failure
from supervisor.models import ControlState, GeminiAssessment, Measurement
from supervisor.rules import EnvironmentalRules


PRIVATE_MESSAGE = "secreto-ficticio-de-prueba https://example.invalid/?key=token-privado"
LEGACY_SCHEMA_ERROR = (
    'Invalid JSON payload received. Unknown name "additional_properties" '
    "at 'generation_config.response_schema': Cannot find field. " + PRIVATE_MESSAGE
)


@pytest.mark.parametrize("code,message,reason", [
    (400, LEGACY_SCHEMA_ERROR, "schema_api_rechazado"),
    (400, "API key not valid. " + PRIVATE_MESSAGE, "autenticacion"),
    (401, PRIVATE_MESSAGE, "autenticacion"),
    (403, PRIVATE_MESSAGE, "permisos"),
    (429, PRIVATE_MESSAGE, "cuota_429"),
    (404, PRIVATE_MESSAGE, "modelo_no_disponible"),
    (400, "JSON mode is not supported for this model. " + PRIVATE_MESSAGE, "salida_estructurada_no_compatible"),
    (400, "Invalid temperature. " + PRIVATE_MESSAGE, "parametros_solicitud_invalidos"),
    (503, PRIVATE_MESSAGE, "servicio_gemini_no_disponible"),
])
def test_http_failures_are_specific_and_never_keep_provider_messages(code, message, reason):
    error = errors.APIError(code, {"error": {"message": message}})
    diagnostic = diagnose_failure(error)
    assert str(diagnostic) == reason
    assert diagnostic.http_code == code
    assert diagnostic.exception_type == "APIError"
    assert diagnostic.cause and diagnostic.advice
    assert "secreto-ficticio" not in str(vars(diagnostic))
    assert "token-privado" not in str(vars(diagnostic))
    assert "https://example.invalid" not in str(vars(diagnostic))


def test_authentication_reason_in_api_details_is_recognized():
    error = errors.ClientError(400, {"error": {"message": PRIVATE_MESSAGE,
        "details": [{"reason": "API_KEY_INVALID"}]}})
    assert str(diagnose_failure(error)) == "autenticacion"


@pytest.mark.parametrize("error,reason", [
    (httpx.ReadTimeout(PRIVATE_MESSAGE), "timeout"),
    (TimeoutError(PRIVATE_MESSAGE), "timeout"),
    (httpx.ConnectError(PRIVATE_MESSAGE), "conectividad"),
    (TypeError(PRIVATE_MESSAGE), "error_implementacion_python"),
    (AssertionError(PRIVATE_MESSAGE), "error_implementacion_python"),
])
def test_local_failures_are_distinguished_without_raw_messages(error, reason):
    diagnostic = diagnose_failure(error)
    assert str(diagnostic) == reason
    assert diagnostic.exception_type == type(error).__name__
    assert diagnostic.http_code is None
    assert "secreto-ficticio" not in str(vars(diagnostic))


async def test_real_sdk_transmits_json_schema_to_mock_http_endpoint(setup):
    """Ejercita google-genai instalado, incluyendo el cuerpo HTTP que fallaba."""
    clock, settings, *_ = setup
    settings.gemini_api_key = SecretStr("clave-ficticia-nunca-enviada-a-la-red")
    assessment = GeminiAssessment(alerta_calidad=False, forzar_climatizacion=False,
        impacto_enologico="Condiciones adecuadas para una crianza estable; una muestra no confirma daños.")
    requests = []

    def endpoint(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        body = json.loads(request.content)
        requests.append(body)
        config = body["generationConfig"]
        # El endpoint simulado reproduce el rechazo que se observó en la API real.
        if "responseSchema" in config:
            return httpx.Response(400, json={"error": {"message": LEGACY_SCHEMA_ERROR}})
        assert config["responseMimeType"] == "application/json"
        assert config["responseJsonSchema"] == GeminiAssessment.model_json_schema()
        assert config["responseJsonSchema"]["additionalProperties"] is False
        assert config["responseJsonSchema"]["properties"]["impacto_enologico"]["minLength"] == 20
        assert "additional_properties" not in json.dumps(body)
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": assessment.model_dump_json()}]}, "finishReason": "STOP"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as transport:
        analyzer = GeminiAnalyzer(settings)
        analyzer.model = "gemini-3.5-flash-lite"
        analyzer.client = genai.Client(api_key=settings.gemini_api_key.get_secret_value(),
            http_options=types.HttpOptions(httpx_async_client=transport,
                retry_options=types.HttpRetryOptions(attempts=1)))
        sample = Measurement(temperatura=16, humedad=70, timestamp=clock.now())
        decision = EnvironmentalRules(settings).evaluate(sample, ControlState(extractor_solicitado=False), clock.now())
        try:
            assert await analyzer.analyze(sample, decision) == assessment
        finally:
            await analyzer.close()
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [
    '{"alerta_calidad":false,"forzar_climatizacion":false,"impacto_enologico":"Texto válido suficientemente largo.","extra":"privado"}',
    '{"alerta_calidad":0,"forzar_climatizacion":false,"impacto_enologico":"Texto válido suficientemente largo."}',
])
async def test_strict_validation_is_preserved_with_json_schema(setup, payload):
    from types import SimpleNamespace
    clock, settings, *_ = setup
    settings.gemini_api_key = SecretStr("clave-ficticia")
    analyzer = GeminiAnalyzer(settings)
    analyzer.model = "modelo-simulado"
    async def generate(**kwargs):
        return SimpleNamespace(text=payload)
    analyzer.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    sample = Measurement(temperatura=16, humedad=70, timestamp=clock.now())
    decision = EnvironmentalRules(settings).evaluate(sample, ControlState(extractor_solicitado=False), clock.now())
    with pytest.raises(GeminiFailure) as caught:
        await analyzer.analyze(sample, decision)
    assert str(caught.value) == "respuesta_estructurada_invalida"
    assert caught.value.exception_type == "ValidationError"
    assert "privado" not in str(vars(caught.value))


@pytest.mark.parametrize("exported", [False, True])
def test_dotenv_explicit_path_works_from_other_cwd_without_frame_search(tmp_path, monkeypatch, exported):
    import supervisor.config as config
    env_dir = tmp_path / "supervisor"
    env_dir.mkdir()
    (env_dir / ".env").write_text("DRY_RUN=true\nGEMINI_MODEL=auto\nGEMINI_API_KEY=clave-del-archivo-ficticio\n")
    elsewhere = tmp_path / "otro-directorio"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(config, "BASE_DIR", env_dir)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    if exported:
        monkeypatch.setenv("GEMINI_API_KEY", "clave-exportada-ficticia")
    def unexpected_search(*args, **kwargs):
        raise AssertionError("No debe buscar frames para encontrar .env")
    monkeypatch.setattr("dotenv.main.find_dotenv", unexpected_search)
    settings = Settings.from_env()
    assert settings.dry_run is True
    assert settings.gemini_model == "auto"
    assert settings.gemini_api_key.get_secret_value() == (
        "clave-exportada-ficticia" if exported else "clave-del-archivo-ficticio")
