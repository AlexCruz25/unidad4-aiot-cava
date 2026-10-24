from types import SimpleNamespace

import pytest
from google.genai import errors

from supervisor.config import Settings
from supervisor.check_config import check
from supervisor.models import GeminiAssessment


async def test_config_command_is_read_only_and_redacts_secrets(monkeypatch, capsys):
    # No cargar un .env real aunque el usuario ya lo haya configurado.
    settings = Settings(gemini_api_key="secreto-ficticio-de-prueba", local_api_token="token-ficticio-de-prueba-123456")
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings))
    result = await check(SimpleNamespace(check_firebase=False, list_models=False, probe_gemini=False))
    output = capsys.readouterr().out
    assert result == 0
    assert "DRY_RUN=True" in output
    assert "google-genai=" in output
    assert "secreto-ficticio-de-prueba" not in output
    assert "token-ficticio-de-prueba" not in output


def isolated_gemini(monkeypatch, *, failure=None, close_failure=None):
    settings = Settings(gemini_api_key="secreto-ficticio-de-prueba", local_api_token="token-ficticio-de-prueba-123456")
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings))
    calls = []
    class Analyzer:
        model = None
        async def resolve_model(self):
            self.model = "gemini-3.5-flash-lite"
            return self.model
        async def analyze(self, sample, decision):
            calls.append("generate")
            if failure is not None:
                raise failure
            return GeminiAssessment(alerta_calidad=False, forzar_climatizacion=False,
                impacto_enologico="Condiciones estables, adecuadas para la crianza en barricas.")
        async def close(self):
            calls.append("close")
            if close_failure is not None:
                raise close_failure
    monkeypatch.setattr("supervisor.check_config.GeminiAnalyzer", lambda settings: Analyzer())
    def forbidden_firebase(settings):
        pytest.fail("La prueba Gemini no debe inicializar Firebase")
    monkeypatch.setattr("supervisor.check_config.FirebaseRepository", forbidden_firebase)
    return calls


async def test_gemini_probe_reports_generation_schema_fields_and_model(monkeypatch, capsys):
    calls = isolated_gemini(monkeypatch)
    assert await check(SimpleNamespace(check_firebase=False, list_models=False, probe_gemini=True)) == 0
    output = capsys.readouterr().out
    assert "Modelo utilizado: gemini-3.5-flash-lite" in output
    assert "Generación estructurada: exitosa" in output
    assert "Validación JSON/Pydantic: exitosa" in output
    assert "Campos verificados: alerta_calidad (bool), forzar_climatizacion (bool), impacto_enologico" in output
    assert calls == ["generate", "close"]


async def test_gemini_probe_reports_original_400_schema_error_without_secret(monkeypatch, capsys):
    error = errors.ClientError(400, {"error": {"message":
        'Unknown name "additional_properties" at generation_config.response_schema. '
        'secreto-ficticio-de-prueba https://example.invalid/?key=token-ficticio-de-prueba'}})
    calls = isolated_gemini(monkeypatch, failure=error)
    assert await check(SimpleNamespace(check_firebase=False, list_models=False, probe_gemini=True)) == 1
    output = capsys.readouterr().out
    assert "Tipo de excepción: ClientError" in output
    assert "Código HTTP: 400" in output
    assert "schema_api_rechazado" in output
    assert "response_json_schema" in output
    assert "secreto-ficticio" not in output
    assert "token-ficticio" not in output
    assert "https://example.invalid" not in output
    assert calls == ["generate", "close"]


async def test_close_errors_do_not_expose_private_messages(monkeypatch, capsys):
    isolated_gemini(monkeypatch, close_failure=OSError("secreto-ficticio-de-prueba"))
    assert await check(SimpleNamespace(check_firebase=False, list_models=False, probe_gemini=True)) == 1
    output = capsys.readouterr().out
    assert "cierre_gemini" in output
    assert "OSError" in output
    assert "secreto-ficticio" not in output


async def test_invalid_config_does_not_expose_validation_input(monkeypatch, capsys):
    def invalid(cls):
        return Settings(gemini_timeout_seconds="secreto-ficticio-de-prueba")
    monkeypatch.setattr(Settings, "from_env", classmethod(invalid))
    assert await check(SimpleNamespace(check_firebase=False, list_models=False, probe_gemini=True)) == 1
    output = capsys.readouterr().out
    assert "configuracion_invalida" in output
    assert "ValidationError" in output
    assert "secreto-ficticio" not in output
