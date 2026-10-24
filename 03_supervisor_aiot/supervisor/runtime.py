import asyncio
from collections import OrderedDict
from contextlib import suppress
from copy import deepcopy
import logging
import time

from .config import Settings
from .firebase import ConcurrentControlChange
from .gemini import GeminiFailure
from .models import AIReport, ControlState, Evaluation, HealthResponse, Measurement, StatusResponse, utc_now
from .rules import EnvironmentalRules, analysis_key
from .singleton import InstanceLock

log = logging.getLogger("cava.supervisor")


class Supervisor:
    def __init__(self, settings: Settings, repository, analyzer, *, now=utc_now, monotonic=time.monotonic):
        self.settings, self.repository, self.analyzer = settings, repository, analyzer
        self.now, self.monotonic = now, monotonic
        self.rules = EnvironmentalRules(settings)
        self.instance_lock = InstanceLock(settings.supervisor_lock_file)
        self.lock = asyncio.Lock()
        self.queue = asyncio.Queue(maxsize=1)
        self.last: Evaluation | None = None
        self.last_communication = None
        self.last_sample = None
        self.last_event = None
        self.firebase_ok = False
        self.problem = None
        self.listener = None
        self.worker_task = None
        self.listener_task = None
        self.ai_task = None
        self.closing = False
        self.calls = 0
        self.cache = OrderedDict()
        self.next_ai_attempt = 0.0
        self.ai_failures = 0
        self.ai_error = None
        self.last_published_signature = None
        self.last_published_time = 0.0

    def set_problem(self, value):
        if value and value != self.problem:
            log.warning("Supervisión degradada: %s", value)
        self.problem = value

    async def start(self):
        self.settings.validate_real_mode()
        self.instance_lock.acquire()
        try:
            await asyncio.to_thread(self.repository.open)
        except Exception:
            self.set_problem("firebase_no_configurado_o_credenciales_invalidas")
            if not self.settings.dry_run:
                self.instance_lock.close()
                raise RuntimeError("Modo real bloqueado: no se pudo inicializar Firebase") from None
            return
        self.worker_task = asyncio.create_task(self._worker(), name="cava-evaluaciones")
        self.listener_task = asyncio.create_task(self._listen(), name="cava-listener")
        self._offer()  # Lectura inicial, aun si el nodo SSE es null o falla su apertura.

    def _offer(self):
        if not self.closing and self.queue.empty():
            self.queue.put_nowait(True)

    async def _listen(self):
        loop = asyncio.get_running_loop()

        def changed(_event):
            if self.closing:
                return
            def notify():
                self.last_event = self.now()
                self._offer()
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(notify)

        backoff = self.settings.listener_retry_seconds
        while not self.closing:
            try:
                # No hacer esta llamada síncrona dentro del event loop.
                opening = asyncio.create_task(asyncio.to_thread(self.repository.listen, changed))
                try:
                    self.listener = await asyncio.shield(opening)
                except asyncio.CancelledError:
                    # Cancelar to_thread no detiene su función. Recoger el
                    # registro que termine de abrir para no filtrar un SSE/hilo.
                    with suppress(Exception):
                        self.listener = await opening
                    raise
                backoff = self.settings.listener_retry_seconds
                while not self.closing and self.repository.listener_alive(self.listener):
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.set_problem("listener_firebase_no_disponible")
            finally:
                if self.listener is not None:
                    try:
                        await asyncio.to_thread(self.listener.close)
                    except Exception:
                        self.set_problem("cierre_listener_fallido_no_abrir_otro")
                        raise
                    self.listener = None
            if not self.closing:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _worker(self):
        while True:
            await self.queue.get()
            try:
                await self.evaluate()
            except Exception:
                self.rules.reset_recovery()
                self.set_problem("evaluacion_interna_fallida")
            finally:
                self.queue.task_done()

    async def evaluate(self) -> Evaluation | None:
        async with self.lock:
            if self.closing:
                return self.last
            try:
                zone = await asyncio.to_thread(self.repository.read_zone)
                self.firebase_ok = True
            except Exception:
                self.firebase_ok = False
                self.rules.reset_recovery()
                self.set_problem("lectura_firebase_fallida")
                return None
            try:
                sample = Measurement.model_validate(zone.get("ambiente"))
                control_raw = zone.get("control")
                control = ControlState.model_validate(control_raw)
                decision = self.rules.evaluate(sample, control, self.now())
            except (ValueError, TypeError, AttributeError):
                self.rules.reset_recovery()
                self.set_problem("datos_invalidos_antiguos_o_control_invalido")
                return None
            self.set_problem(None)
            self.last_communication = self.now()
            self.last_sample = sample.timestamp
            action_result = "sin_nueva_orden"
            if decision.accion is not None:
                if self.settings.dry_run:
                    action_result = "dry_run_encender" if decision.accion else "dry_run_apagar"
                    log.info("DRY_RUN: solicitaría %s; no se escribe Firebase", "encendido" if decision.accion else "apagado")
                else:
                    try:
                        sent = await asyncio.to_thread(self.repository.apply_control, deepcopy(control_raw), decision.accion, sample)
                        action_result = "orden_enviada" if sent else "sin_cambio"
                    except ConcurrentControlChange:
                        self.rules.reset_recovery()
                        action_result = "conflicto_control_no_se_escribio"
                        self.set_problem("control_cambio_durante_la_evaluacion")
                    except Exception:
                        self.rules.reset_recovery()
                        self.firebase_ok = False
                        action_result = "error_firebase_no_confirmar_ejecucion"
                        self.set_problem("escritura_control_fallida")
            key = analysis_key(sample, decision)
            report = self._current_report(key)
            self.last = Evaluation(fecha=self.now(), muestra=sample, control=control,
                                   decision=decision, ia=report, accion_resultado=action_result)
            # La orden determinista ya se resolvió antes de iniciar cualquier IA.
            if report.estado != "disponible" and self.analyzer.configured and self.ai_task is None and self.monotonic() >= self.next_ai_attempt:
                self.next_ai_attempt = self.monotonic() + self.settings.gemini_min_interval_seconds
                self.calls += 1
                self.ai_task = asyncio.create_task(self._analyze(key, sample, decision), name="cava-gemini")
            await self._publish(self.last)
            return self.last.model_copy(deep=True)

    def _current_report(self, key):
        cached = self.cache.get(key)
        if cached and self.monotonic() - cached[0] < self.settings.gemini_cache_seconds:
            self.cache.move_to_end(key)
            return cached[1].model_copy(deep=True)
        if not self.analyzer.configured:
            return AIReport(estado="no_disponible", motivo="sin_api_key")
        if self.ai_error:
            return AIReport(estado="no_disponible", motivo=self.ai_error)
        if self.ai_task is not None or self.monotonic() >= self.next_ai_attempt:
            return AIReport(estado="pendiente", motivo="analisis_en_curso_o_programado")
        return AIReport(estado="limitado", motivo="esperando_intervalo_minimo")

    async def _analyze(self, key, sample, decision):
        try:
            assessment = await self.analyzer.analyze(sample, decision)
            # Validar incluso adaptadores alternativos o respuestas de dobles.
            from .models import GeminiAssessment
            assessment = GeminiAssessment.model_validate(assessment)
            report = AIReport(estado="disponible", modelo=self.analyzer.model,
                              evaluacion=assessment, muestra=sample)
            self.cache[key] = (self.monotonic(), report)
            self.cache.move_to_end(key)
            while len(self.cache) > 32:
                self.cache.popitem(last=False)
            self.ai_failures, self.ai_error = 0, None
        except asyncio.CancelledError:
            self.ai_task = None
            raise
        except Exception as error:
            reason = str(error) if isinstance(error, GeminiFailure) else "respuesta_o_cliente_invalido"
            self.ai_error = reason
            self.ai_failures += 1
            backoff = min(self.settings.gemini_retry_max_seconds,
                          self.settings.gemini_retry_seconds * 2 ** min(self.ai_failures - 1, 10))
            self.next_ai_attempt = max(self.next_ai_attempt, self.monotonic() + backoff)
            log.warning("Análisis IA no disponible: %s; reintento posterior sin detener reglas", reason)
            report = AIReport(estado="no_disponible", motivo=reason)
        try:
            async with self.lock:
                if (self.closing or self.problem is not None or not self.firebase_ok or self.last is None
                        or analysis_key(self.last.muestra, self.last.decision) != key):
                    return
                try:
                    self.last.muestra.check_fresh(self.now(), self.settings.max_measurement_age_seconds,
                                                 self.settings.future_tolerance_seconds)
                except ValueError:
                    return
                self.last.ia = report
                self.last.fecha = self.now()
                await self._publish(self.last)
        finally:
            self.ai_task = None

    def _payload(self, evaluation):
        report, decision = evaluation.ia, evaluation.decision
        if report.estado == "disponible":
            source = report.muestra
            impact = f"[Gemini · {report.modelo} · muestra {source.temperatura:g} °C / {source.humedad:g} %] {report.evaluacion.impacto_enologico}"
            if (report.evaluacion.alerta_calidad, report.evaluacion.forzar_climatizacion) != (
                decision.alerta_calidad, decision.forzar_climatizacion
            ):
                impact += " Las reglas deterministas locales prevalecen sobre la recomendación IA."
        else:
            impact = f"Análisis IA no disponible ({report.motivo}). Protección basada en reglas deterministas locales."
        return {"alerta_calidad": decision.alerta_calidad,
                "forzar_climatizacion": decision.forzar_climatizacion,
                "impacto_enologico": impact,
                "ultima_evaluacion": evaluation.fecha.isoformat().replace("+00:00", "Z")}

    async def _publish(self, evaluation):
        if self.settings.dry_run:
            evaluation.publicacion = "dry_run_sin_escrituras"
            return
        payload = self._payload(evaluation)
        signature = {key: value for key, value in payload.items() if key != "ultima_evaluacion"}
        if signature == self.last_published_signature and self.monotonic() - self.last_published_time < self.settings.supervisor_publish_seconds:
            evaluation.publicacion = "sin_cambios_no_repetir_escritura"
            return
        try:
            evaluation.muestra.check_fresh(self.now(), self.settings.max_measurement_age_seconds,
                                           self.settings.future_tolerance_seconds)
            await asyncio.to_thread(self.repository.publish_supervisor, payload)
            self.last_published_signature = signature
            self.last_published_time = self.monotonic()
            evaluation.publicacion = "publicado_en_firebase"
        except Exception:
            self.firebase_ok = False
            evaluation.publicacion = "error_publicacion_firebase"
            self.set_problem("publicacion_supervisor_fallida")

    def status(self) -> StatusResponse:
        recent = self.last_sample is not None and -self.settings.future_tolerance_seconds <= (
            self.now() - self.last_sample
        ).total_seconds() <= self.settings.max_measurement_age_seconds
        listener_active = self.listener is not None and self.repository.listener_alive(self.listener)
        good = self.firebase_ok and recent and listener_active and self.problem is None
        ai_ready = self.last is not None and self.last.ia.estado == "disponible"
        state = ("operativo" if ai_ready else "operativo_reglas_locales") if good else "degradado"
        problem = self.problem or ("sin_telemetria_reciente" if not recent else "listener_no_activo" if not listener_active else None)
        health = HealthResponse(estado=state, dry_run=self.settings.dry_run,
                                firebase_configurado=self.repository.configured,
                                firebase_ultima_lectura_correcta=self.firebase_ok, listener_activo=listener_active,
                                datos_recientes=recent, gemini_configurado=self.analyzer.configured,
                                problema=problem)
        return StatusResponse(health=health, ultima_evaluacion=self.last,
                              ultima_comunicacion_valida=self.last_communication,
                              ultimo_evento=self.last_event, ultima_muestra_valida=self.last_sample,
                              llamadas_gemini=self.calls, modelo_gemini=self.analyzer.model,
                              evaluacion_ia_en_curso=self.ai_task is not None)

    async def close(self):
        self.closing = True
        try:
            for task in (self.listener_task, self.worker_task, self.ai_task):
                if task is not None:
                    task.cancel()
            await asyncio.gather(*(task for task in (self.listener_task, self.worker_task, self.ai_task)
                                   if task is not None), return_exceptions=True)
            if self.listener is not None:
                with suppress(Exception):
                    await asyncio.to_thread(self.listener.close)
                self.listener = None
            try:
                await self.analyzer.close()
            finally:
                await asyncio.to_thread(self.repository.close)
        finally:
            self.instance_lock.close()
