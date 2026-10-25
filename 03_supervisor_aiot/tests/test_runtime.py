import asyncio
from copy import deepcopy

from supervisor.gemini import GeminiFailure
from conftest import finish_ai, wait_listener


async def test_dry_run_never_calls_any_writer(setup):
    _, _, repo, _, runtime = setup
    repo.sample(24, 55)
    before = deepcopy(repo.zone)
    result = await runtime.evaluate()
    await finish_ai(runtime)
    assert result.accion_resultado == "dry_run_encender"
    assert repo.actions == repo.publications == []
    assert repo.zone == before
    await runtime.close()


async def test_rules_precede_slow_ai_and_override_its_booleans(setup):
    clock, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    analyzer.gate = asyncio.Event()
    repo.sample(24, 70)
    await asyncio.wait_for(runtime.evaluate(), 1)
    assert repo.actions == [True]
    assert runtime.ai_task is not None
    analyzer.gate.set()
    await finish_ai(runtime)
    payload = repo.publications[-1]
    assert payload["alerta_calidad"] is True
    assert payload["forzar_climatizacion"] is True
    assert "prevalecen" in payload["impacto_enologico"]
    assert repo.zone["extractor_confirmado"] is False
    assert repo.zone["control"]["otro"] == "conservar"
    assert repo.zone["supervisor"]["campo_ajeno"] == "conservar"
    assert payload["ultima_evaluacion"].endswith("Z")
    await runtime.close()


async def test_gemini_error_keeps_critical_protection_and_marks_unavailable(setup):
    _, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    analyzer.error = GeminiFailure("cuota_429")
    repo.sample(24, 55)
    await runtime.evaluate()
    await finish_ai(runtime)
    assert repo.actions == [True]
    assert runtime.last.ia.estado == "no_disponible"
    payload = repo.publications[-1]
    assert payload["forzar_climatizacion"] is True
    assert payload["impacto_enologico"].startswith("Análisis IA no disponible")
    assert "[Gemini" not in payload["impacto_enologico"]
    await runtime.close()


async def test_cache_frequency_and_backoff(setup):
    clock, settings, repo, analyzer, runtime = setup
    repo.sample(24.1, 70)
    await runtime.evaluate()
    await finish_ai(runtime)
    for t in [24.2, 24.3, 24.4]:
        clock.advance(5)
        repo.sample(t, 70)
        await runtime.evaluate()
        await finish_ai(runtime)
    assert analyzer.calls == 1
    repo.sample(24, 55)  # Nueva anomalía, pero se respeta el mínimo global.
    await runtime.evaluate()
    assert analyzer.calls == 1
    clock.advance(61)
    repo.sample(24, 55)
    analyzer.error = GeminiFailure("timeout")
    await runtime.evaluate()
    await finish_ai(runtime)
    assert analyzer.calls == 2
    clock.advance(61)
    repo.sample(24, 55)
    await runtime.evaluate()
    assert analyzer.calls == 2
    clock.advance(60)
    repo.sample(24, 55)
    await runtime.evaluate()
    await finish_ai(runtime)
    assert analyzer.calls == 3
    await runtime.close()


async def test_expired_ai_cache_requires_new_generation_but_not_repeated_calls(setup):
    clock, settings, repo, analyzer, runtime = setup
    repo.sample(24, 70)
    await runtime.evaluate()
    await finish_ai(runtime)
    clock.advance(settings.gemini_cache_seconds - 1)
    repo.sample(24, 70)
    assert (await runtime.evaluate()).ia.estado == "disponible"
    assert analyzer.calls == 1
    clock.advance(2)
    repo.sample(24, 70)
    await runtime.evaluate()
    await finish_ai(runtime)
    assert analyzer.calls == 2
    await runtime.evaluate()
    assert analyzer.calls == 2
    await runtime.close()


async def test_concurrent_evaluations_issue_only_one_critical_order(setup):
    _, settings, repo, analyzer, runtime = setup
    settings.dry_run = False  # Solo repositorio simulado; nunca Firebase real.
    repo.sample(24, 55)
    await asyncio.gather(*(runtime.evaluate() for _ in range(12)))
    await finish_ai(runtime)
    assert repo.actions == [True]
    assert analyzer.calls == 1
    assert repo.zone["extractor_confirmado"] is False
    await runtime.close()


async def test_missing_invalid_old_data_never_act_and_reset_recovery(setup):
    clock, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    for ambient in [None, {}, {"temperatura": True, "humedad": 55, "timestamp": clock.now().timestamp()*1000}]:
        repo.zone["ambiente"] = ambient
        assert await runtime.evaluate() is None
    repo.sample(24, 55)
    clock.advance(21)
    assert await runtime.evaluate() is None
    assert repo.actions == repo.publications == []
    assert analyzer.calls == 0
    assert runtime.rules.recovery_start is None
    await runtime.close()


async def test_manual_change_during_auto_off_aborts_transaction(setup):
    clock, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    analyzer.configured = False
    repo.zone["control"].update(extractor_solicitado=True, origen="supervisor")
    await runtime.evaluate()
    for _ in range(11):
        clock.advance(5)
        repo.sample(16, 70)
        await runtime.evaluate()
    repo.concurrent = {**repo.zone["control"], "origen": "manual"}
    clock.advance(5)
    repo.sample(16, 70)
    result = await runtime.evaluate()
    assert result.accion_resultado == "conflicto_control_no_se_escribio"
    assert repo.actions == []
    assert repo.zone["control"]["extractor_solicitado"] is True
    clock.advance(5)
    repo.sample(16, 70)
    assert (await runtime.evaluate()).decision.accion is None
    await runtime.close()


async def test_manual_off_is_reversed_only_on_next_valid_critical_evaluation(setup):
    clock, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    analyzer.configured = False
    repo.sample(24, 70)
    await runtime.evaluate()
    repo.zone["control"].update(extractor_solicitado=False, origen="manual")
    clock.advance(5)
    repo.sample(24, 70)
    await runtime.evaluate()
    assert repo.actions == [True, True]
    await runtime.close()


async def test_reconnect_events_coalesce_one_listener_no_repeated_writes(setup):
    clock, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    analyzer.configured = False
    repo.sample(24, 70)
    await runtime.start()
    await wait_listener(runtime)
    await runtime.queue.join()
    for _ in range(20):
        repo.callback(object())
    await asyncio.sleep(.02)
    await runtime.queue.join()
    assert repo.listen_calls == 1
    assert repo.actions == [True]
    assert len(repo.publications) == 1
    await runtime.close()
    assert repo.registrations[0].alive is False
    assert analyzer.closed and repo.closed
    assert runtime.worker_task.done() and runtime.listener_task.done()


async def test_old_ai_result_does_not_publish_as_current_state(setup):
    clock, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    analyzer.gate = asyncio.Event()
    repo.sample(24, 70)
    await runtime.evaluate()
    clock.advance(5)
    repo.sample(17, 55)
    await runtime.evaluate()
    old_count = len(repo.publications)
    analyzer.gate.set()
    await finish_ai(runtime)
    assert len(repo.publications) == old_count
    assert runtime.last.muestra.humedad == 55
    assert runtime.last.ia.estado != "disponible"
    await runtime.close()


async def test_firebase_failure_resets_recovery_and_produces_no_commands(setup):
    _, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    repo.fail_read = True
    assert await runtime.evaluate() is None
    assert runtime.status().health.firebase_ultima_lectura_correcta is False
    assert repo.actions == repo.publications == []
    await runtime.close()


async def test_automatic_recovery_writes_off_once_after_stable_ideal(setup):
    clock, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    analyzer.configured = False
    repo.sample(24, 70)
    await runtime.evaluate()
    assert repo.actions == [True]
    for _ in range(13):
        clock.advance(5)
        repo.sample(16, 70)
        await runtime.evaluate()
    assert repo.actions == [True, False]
    assert repo.zone["control"]["origen"] == "supervisor"
    assert repo.zone["extractor_confirmado"] is False
    await runtime.close()


async def test_shutdown_collects_a_listener_still_opening_in_worker_thread(setup):
    import threading
    _, _, repo, analyzer, runtime = setup
    analyzer.configured = False
    entered, release = threading.Event(), threading.Event()
    original = repo.listen
    def delayed(callback):
        entered.set()
        release.wait(2)
        return original(callback)
    repo.listen = delayed
    await runtime.start()
    assert await asyncio.to_thread(entered.wait, 1)
    closing = asyncio.create_task(runtime.close())
    await asyncio.sleep(.01)
    release.set()
    await asyncio.wait_for(closing, 2)
    assert len(repo.registrations) == 1
    assert repo.registrations[0].alive is False


def test_transaction_rejects_numeric_boolean_even_if_python_equality_matches():
    import pytest
    from supervisor.firebase import control_update, ConcurrentControlChange
    expected = {"extractor_solicitado":True,"origen":"supervisor"}
    current = {"extractor_solicitado":1,"origen":"supervisor"}
    with pytest.raises(ConcurrentControlChange):
        control_update(current, expected, False)


async def test_inflight_analysis_cannot_publish_after_new_invalid_telemetry(setup):
    _, settings, repo, analyzer, runtime = setup
    settings.dry_run = False
    analyzer.gate = asyncio.Event()
    repo.sample(24, 70)
    await runtime.evaluate()
    count = len(repo.publications)
    repo.zone["ambiente"] = None
    assert await runtime.evaluate() is None
    analyzer.gate.set()
    await finish_ai(runtime)
    assert len(repo.publications) == count
    assert runtime.problem == "datos_invalidos_antiguos_o_control_invalido"
    await runtime.close()
