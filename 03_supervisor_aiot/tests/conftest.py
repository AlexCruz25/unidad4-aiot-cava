from copy import deepcopy
from datetime import datetime, timedelta, timezone
import asyncio

import pytest

from supervisor.config import Settings
from supervisor.firebase import ConcurrentControlChange, control_update
from supervisor.models import GeminiAssessment
from supervisor.runtime import Supervisor


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
        self.ticks = 1000.0

    def now(self):
        return self.value

    def monotonic(self):
        return self.ticks

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)
        self.ticks += seconds


class Registration:
    alive = True
    def close(self):
        self.alive = False


class FakeFirebase:
    configured = True
    def __init__(self, clock):
        self.clock = clock
        self.zone = {
            "ambiente": {},
            "control": {"extractor_solicitado": False, "origen": "manual", "otro": "conservar"},
            "extractor_confirmado": False,
            "supervisor": {"campo_ajeno": "conservar"},
        }
        self.sample(16, 70)
        self.actions, self.publications, self.registrations = [], [], []
        self.fail_read = False
        self.concurrent = None
        self.closed = False
        self.callback = None
        self.listen_calls = 0

    def sample(self, temperature, humidity):
        self.zone["ambiente"] = {"temperatura": temperature, "humedad": humidity,
                                 "timestamp": self.clock.now().timestamp() * 1000}

    def open(self):
        pass

    def read_zone(self):
        if self.fail_read:
            raise OSError("red caída")
        return deepcopy(self.zone)

    def apply_control(self, expected, target, sample):
        if self.concurrent is not None:
            self.zone["control"] = self.concurrent
            self.concurrent = None
        result = control_update(self.zone["control"], expected, target)
        self.actions.append(target)
        self.zone["control"] = result
        return True

    def publish_supervisor(self, payload):
        self.publications.append(deepcopy(payload))
        self.zone["supervisor"].update(payload)

    def listen(self, callback):
        self.listen_calls += 1
        self.callback = callback
        registration = Registration()
        self.registrations.append(registration)
        return registration

    @staticmethod
    def listener_alive(registration):
        return registration.alive

    def close(self):
        self.closed = True


class FakeGemini:
    model = "gemini-prueba-aislada"
    def __init__(self, configured=True):
        self.configured = configured
        self.calls = 0
        self.error = None
        self.gate = None
        self.closed = False

    async def analyze(self, sample, decision):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.error:
            raise self.error
        # Recomendación deliberadamente contradictoria con condiciones críticas.
        return GeminiAssessment(alerta_calidad=False, forzar_climatizacion=False,
                                impacto_enologico="Explicación simulada solo para pruebas aisladas; no usar en producción.")

    async def close(self):
        self.closed = True


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}")
    settings = Settings(firebase_credentials_path=credentials, local_api_token="x" * 32,
                        supervisor_lock_file=tmp_path / "supervisor.lock")
    repo, analyzer = FakeFirebase(clock), FakeGemini()
    runtime = Supervisor(settings, repo, analyzer, now=clock.now, monotonic=clock.monotonic)
    return clock, settings, repo, analyzer, runtime


async def finish_ai(runtime):
    if runtime.ai_task is not None:
        await runtime.ai_task


async def wait_listener(runtime):
    for _ in range(100):
        if runtime.listener is not None:
            return
        await asyncio.sleep(.005)
    raise AssertionError("No se abrió el listener de prueba")
