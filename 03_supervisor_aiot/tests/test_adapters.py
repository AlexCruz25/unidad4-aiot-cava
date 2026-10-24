import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from pydantic import SecretStr, ValidationError

from supervisor.config import Settings
from supervisor.firebase import FirebaseRepository, ConcurrentControlChange, NothingToChange, control_update
from supervisor.gemini import GeminiAnalyzer, GeminiFailure, select_model
from supervisor.models import ControlState, GeminiAssessment, Measurement
from supervisor.rules import EnvironmentalRules
from supervisor.singleton import InstanceLock


def test_control_transaction_preserves_other_children_and_aborts_manual_conflict():
    before = {"extractor_solicitado":False, "origen":"manual", "ajeno":{"dato":123}}
    changed = control_update(before, deepcopy(before), True)
    assert changed == {**before, "extractor_solicitado":True, "origen":"supervisor"}
    assert before["extractor_solicitado"] is False
    with pytest.raises(ConcurrentControlChange):
        control_update({**before, "origen":"otro"}, before, True)
    with pytest.raises(NothingToChange):
        control_update(before, before, False)


def test_firebase_paths_writes_and_dry_run_guard(setup, monkeypatch):
    clock, settings, *_ = setup
    repo = FirebaseRepository(settings)
    calls = []
    class Reference:
        def __init__(self, path): self.path = path
        def transaction(self, callback):
            calls.append((self.path, callback({"extractor_solicitado":False,"origen":"manual","otro":123})))
        def update(self, payload): calls.append((self.path,payload))
    repo.reference = lambda suffix="": Reference(suffix)
    sample = Measurement(temperatura=24, humedad=70, timestamp=clock.now())
    with pytest.raises(RuntimeError, match="DRY_RUN"):
        repo.apply_control({}, True, sample)
    with pytest.raises(RuntimeError, match="DRY_RUN"):
        repo.publish_supervisor({})
    assert calls == []
    settings.dry_run = False
    monkeypatch.setattr("supervisor.firebase.utc_now", clock.now)
    repo.apply_control({"extractor_solicitado":False,"origen":"manual","otro":123}, True, sample)
    payload = {"alerta_calidad":True,"forzar_climatizacion":True,"impacto_enologico":"Análisis IA no disponible", "ultima_evaluacion":clock.now().isoformat()}
    repo.publish_supervisor(payload)
    assert [call[0] for call in calls] == ["/control", "/supervisor"]
    assert calls[0][1]["otro"] == 123
    assert set(calls[1][1]) == set(payload)


def test_singleton_rejects_second_instance_and_releases(tmp_path):
    path = tmp_path/"instance.lock"
    first, second = InstanceLock(path), InstanceLock(path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="Ya hay"):
            second.acquire()
    finally:
        first.close()
    second.acquire()
    second.close()


def test_model_selection_is_key_specific_and_prefers_stable_flash_lite():
    def model(name, actions=("generateContent",)):
        return SimpleNamespace(name="models/"+name, supported_actions=list(actions))
    models = [model("gemini-2.5-flash-lite"), model("gemini-3.5-flash-lite"),
              model("gemini-9.0-flash-lite-preview"), model("gemini-4.0-flash"),
              model("gemini-20.0-flash-lite-image"), model("gemini-8.0-flash-lite", ())]
    assert select_model(models,"auto") == "gemini-3.5-flash-lite"
    assert select_model(models,"gemini-4.0-flash") == "gemini-4.0-flash"
    with pytest.raises(GeminiFailure): select_model(models,"modelo-inexistente")
    with pytest.raises(GeminiFailure): select_model([],"auto")


@pytest.mark.parametrize("text", [
    "no es JSON", '{"alerta_calidad":"false","forzar_climatizacion":true,"impacto_enologico":"Texto suficientemente largo para la prueba"}',
    '{"alerta_calidad":true,"forzar_climatizacion":true}',
    '{"alerta_calidad":true,"forzar_climatizacion":true,"impacto_enologico":"corto"}',
])
async def test_gemini_invalid_json_is_not_published_as_analysis(setup, text):
    clock, settings, *_ = setup
    settings.gemini_api_key = SecretStr("clave-ficticia-solo-para-el-doble")
    analyzer = GeminiAnalyzer(settings)
    analyzer.model = "modelo-prueba"
    async def generate(**kwargs): return SimpleNamespace(text=text)
    analyzer.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    sample = Measurement(temperatura=24, humedad=70, timestamp=clock.now())
    decision = EnvironmentalRules(settings).evaluate(sample, ControlState(extractor_solicitado=False), clock.now())
    with pytest.raises(GeminiFailure, match="respuesta_estructurada_invalida"):
        await analyzer.analyze(sample, decision)


@pytest.mark.parametrize("failure,reason", [(httpx.ReadTimeout("privado"),"timeout"),
    (errors.ClientError(429, {"error":{"message":"no imprimir este secreto de prueba"}}), "cuota_429")])
async def test_gemini_timeout_and_quota_are_sanitized(setup, failure, reason):
    clock, settings, *_ = setup
    settings.gemini_api_key = SecretStr("clave-ficticia-solo-para-el-doble")
    analyzer = GeminiAnalyzer(settings)
    analyzer.model = "modelo-prueba"
    async def generate(**kwargs): raise failure
    analyzer.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    sample = Measurement(temperatura=24, humedad=70, timestamp=clock.now())
    decision = EnvironmentalRules(settings).evaluate(sample, ControlState(extractor_solicitado=False), clock.now())
    with pytest.raises(GeminiFailure) as caught:
        await analyzer.analyze(sample, decision)
    assert str(caught.value) == reason
    assert caught.value.exception_type == type(failure).__name__
    assert caught.value.http_code == (429 if reason == "cuota_429" else None)


async def test_sdk_uses_pydantic_json_schema_and_no_tools(setup):
    clock, settings, *_ = setup
    settings.gemini_api_key = SecretStr("clave-ficticia-solo-para-el-doble")
    captured = {}
    analyzer = GeminiAnalyzer(settings)
    analyzer.model = "modelo-prueba"
    async def generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text='{"alerta_calidad":true,"forzar_climatizacion":true,"impacto_enologico":"Descripción enológica de prueba, aislada del sistema real."}')
    analyzer.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    sample = Measurement(temperatura=24, humedad=55, timestamp=clock.now())
    decision = EnvironmentalRules(settings).evaluate(sample, ControlState(extractor_solicitado=False), clock.now())
    result = await analyzer.analyze(sample, decision)
    assert result.alerta_calidad is True
    assert captured["config"].response_schema is None
    assert captured["config"].response_json_schema == GeminiAssessment.model_json_schema()
    assert captured["config"].response_mime_type == "application/json"
    assert not captured["config"].tools
    assert captured["config"].automatic_function_calling.disable is True


def test_settings_defaults_paths_and_real_mode_validation(tmp_path):
    settings = Settings()
    assert settings.dry_run is True
    with pytest.raises(ValidationError): Settings(firebase_database_url="https://otra-base.firebaseio.com")
    with pytest.raises(ValidationError): Settings(max_sample_gap_seconds=21)
    settings.dry_run = False
    with pytest.raises(ValueError, match="Modo real bloqueado"): settings.validate_real_mode()


async def test_gemini_closes_both_clients_even_when_async_close_fails(setup):
    _, settings, *_ = setup
    analyzer = GeminiAnalyzer(settings)
    closed = []
    async def aclose():
        closed.append("async")
        raise OSError("cierre fallido de prueba")
    analyzer.client = SimpleNamespace(aio=SimpleNamespace(aclose=aclose), close=lambda:closed.append("sync"))
    with pytest.raises(OSError):
        await analyzer.close()
    assert closed == ["async", "sync"]
    assert analyzer.client is None
