from datetime import datetime

from .config import Settings
from .models import ControlState, Decision, Measurement


class EnvironmentalRules:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.recovery_start: datetime | None = None
        self.last_sample: datetime | None = None

    def reset_recovery(self) -> None:
        self.recovery_start = None
        self.last_sample = None

    def evaluate(self, sample: Measurement, control: ControlState, now: datetime) -> Decision:
        try:
            sample.check_fresh(now, self.settings.max_measurement_age_seconds, self.settings.future_tolerance_seconds)
        except ValueError:
            self.reset_recovery()
            raise
        ideal = 12 <= sample.temperatura <= 18 and 65 <= sample.humedad <= 80
        anomalies = []
        if sample.temperatura > 22:
            anomalies.append("temperatura_superior_22")
        if sample.humedad < 60:
            anomalies.append("humedad_inferior_60")
        if anomalies:
            self.reset_recovery()
            return Decision(estado="critico", anomalias=anomalies, alerta_calidad=True,
                            forzar_climatizacion=True, accion=None if control.extractor_solicitado else True,
                            motivo="Protección crítica: prioridad sobre un apagado manual")
        automatic_on = control.extractor_solicitado and control.origen == "supervisor"
        if automatic_on and ideal:
            # Solo nuevas muestras avanzan la recuperación; repetir POST o una
            # reconexión con el mismo timestamp no equivale a estabilidad nueva.
            if self.last_sample is None or sample.timestamp < self.last_sample or (
                sample.timestamp - self.last_sample
            ).total_seconds() > self.settings.max_sample_gap_seconds:
                self.recovery_start = sample.timestamp
            if self.recovery_start is None:
                self.recovery_start = sample.timestamp
            self.last_sample = sample.timestamp
            stable = max(0.0, (sample.timestamp - self.recovery_start).total_seconds())
            recovered = stable >= self.settings.recovery_stable_seconds
            return Decision(estado="normal" if recovered else "recuperando", anomalias=[],
                            alerta_calidad=False, forzar_climatizacion=not recovered,
                            accion=False if recovered else None, segundos_estables=stable,
                            motivo="Recuperación estable: apagar orden automática" if recovered else "Mantener mitigación durante la recuperación")
        self.reset_recovery()
        return Decision(estado="normal" if ideal else "fuera_ideal", anomalias=[],
                        alerta_calidad=not ideal, forzar_climatizacion=automatic_on,
                        motivo="Respetar encendido manual" if control.extractor_solicitado and not automatic_on
                        else "Mantener mitigación fuera del rango ideal" if automatic_on
                        else "No se requiere una nueva orden automática")


def analysis_key(sample: Measurement, decision: Decision) -> tuple:
    # Cambios de régimen y magnitud; no una key distinta por cada PATCH de 5 s.
    return (decision.estado, tuple(decision.anomalias), int(sample.temperatura // 2),
            int(sample.humedad // 5), decision.forzar_climatizacion)
