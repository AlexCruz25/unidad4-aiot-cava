from datetime import timedelta

import pytest
from pydantic import ValidationError

from supervisor.models import ControlState, Measurement
from supervisor.rules import EnvironmentalRules


@pytest.mark.parametrize("temperature,humidity,state,action,count", [
    (16, 70, "normal", None, 0), (24, 70, "critico", True, 1),
    (17, 55, "critico", True, 1), (24, 55, "critico", True, 2),
    (22, 70, "fuera_ideal", None, 0), (16, 60, "fuera_ideal", None, 0),
    (22, 60, "fuera_ideal", None, 0),
    (12, 65, "normal", None, 0), (18, 80, "normal", None, 0),
])
def test_environmental_thresholds(setup, temperature, humidity, state, action, count):
    clock, settings, *_ = setup
    sample = Measurement(temperatura=temperature, humedad=humidity, timestamp=clock.now())
    result = EnvironmentalRules(settings).evaluate(sample, ControlState(extractor_solicitado=False), clock.now())
    assert (result.estado, result.accion, len(result.anomalias)) == (state, action, count)


def test_recovery_needs_continuous_new_samples_and_honors_manual_on(setup):
    clock, settings, *_ = setup
    rules = EnvironmentalRules(settings)
    control = ControlState(extractor_solicitado=True, origen="supervisor")
    def evaluate():
        return rules.evaluate(Measurement(temperatura=16, humedad=70, timestamp=clock.now()), control, clock.now())
    assert evaluate().accion is None
    for _ in range(11):
        clock.advance(5)
        assert evaluate().accion is None
    clock.advance(5)
    assert evaluate().accion is False
    control.origen = "manual"
    assert evaluate().accion is None
    assert rules.recovery_start is None


def test_hysteresis_holds_outside_ideal_and_resets_on_gap(setup):
    clock, settings, *_ = setup
    rules = EnvironmentalRules(settings)
    control = ControlState(extractor_solicitado=True, origen="supervisor")
    sample = Measurement(temperatura=20, humedad=70, timestamp=clock.now())
    result = rules.evaluate(sample, control, clock.now())
    assert result.accion is None and result.forzar_climatizacion
    sample.temperatura = 16
    rules.evaluate(sample, control, clock.now())
    clock.advance(16)
    sample.timestamp = clock.now()
    assert rules.evaluate(sample, control, clock.now()).segundos_estables == 0
    for _ in range(4):
        clock.advance(2)
        assert rules.evaluate(sample, control, clock.now()).segundos_estables == 0


@pytest.mark.parametrize("temperature,humidity", [(20, 70), (16, 62)])
def test_recovery_restarts_after_a_new_nonideal_measurement(setup, temperature, humidity):
    clock, settings, *_ = setup
    rules = EnvironmentalRules(settings)
    control = ControlState(extractor_solicitado=True, origen="supervisor")
    def evaluate(t=16, h=70):
        return rules.evaluate(Measurement(temperatura=t, humedad=h, timestamp=clock.now()), control, clock.now())
    evaluate()
    for _ in range(11):
        clock.advance(5)
        assert evaluate().accion is None
    clock.advance(5)
    assert evaluate(temperature, humidity).accion is None
    assert rules.recovery_start is None
    clock.advance(5)
    assert evaluate().segundos_estables == 0
    for _ in range(11):
        clock.advance(5)
        assert evaluate().accion is None
    clock.advance(5)
    assert evaluate().accion is False


@pytest.mark.parametrize("field,value", [
    ("temperatura", None), ("temperatura", True), ("temperatura", "24"),
    ("temperatura", float("nan")), ("temperatura", float("inf")),
    ("temperatura", -41), ("temperatura", 81),
    ("humedad", False), ("humedad", -1), ("humedad", 101),
    ("timestamp", None), ("timestamp", True), ("timestamp", 0),
    ("timestamp", float("nan")), ("timestamp", "Sin evaluacion"),
])
def test_invalid_measurements(field, value, setup):
    clock, *_ = setup
    raw = {"temperatura": 16, "humedad": 70, "timestamp": clock.now()}
    raw[field] = value
    with pytest.raises(ValidationError):
        Measurement.model_validate(raw)


def test_epoch_units_and_iso_and_freshness(setup):
    clock, settings, *_ = setup
    for timestamp in [clock.now().timestamp(), clock.now().timestamp() * 1000, clock.now().isoformat()]:
        assert Measurement(temperatura=16, humedad=70, timestamp=timestamp).timestamp == clock.now()
    sample = Measurement(temperatura=16, humedad=70, timestamp=clock.now() - timedelta(seconds=21))
    rules = EnvironmentalRules(settings)
    with pytest.raises(ValueError):
        rules.evaluate(sample, ControlState(extractor_solicitado=False), clock.now())
    sample.timestamp = clock.now() + timedelta(seconds=6)
    with pytest.raises(ValueError):
        rules.evaluate(sample, ControlState(extractor_solicitado=False), clock.now())
