from copy import deepcopy
from collections.abc import Callable
import uuid

import firebase_admin
from firebase_admin import credentials, db

from .config import ROOT_PATH, Settings
from .models import ControlState, Measurement, utc_now


class ConcurrentControlChange(Exception):
    pass


class NothingToChange(Exception):
    pass


def control_update(current: dict, expected: dict, target: bool) -> dict:
    """Callback puro: Firebase puede repetirlo si hay conflicto de ETag."""
    if not isinstance(current, dict) or current != expected:
        raise ConcurrentControlChange("El control cambió durante la evaluación")
    try:
        ControlState.model_validate(current)
    except ValueError:
        raise ConcurrentControlChange("El control dejó de tener tipos válidos") from None
    if current.get("extractor_solicitado") is target:
        raise NothingToChange()
    result = deepcopy(current)
    result.update(extractor_solicitado=target, origen="supervisor")
    return result


class FirebaseRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.app = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.firebase_credentials_path and self.settings.firebase_credentials_path.is_file())

    def open(self) -> None:
        if self.app is not None:
            return
        if not self.configured:
            raise ValueError("Faltan credenciales privadas de Firebase")
        certificate = credentials.Certificate(str(self.settings.firebase_credentials_path))
        if certificate.project_id != "unidad4-aiot-cava":
            raise ValueError("Las credenciales pertenecen a otro proyecto")
        self.app = firebase_admin.initialize_app(certificate, {
            "databaseURL": self.settings.firebase_database_url,
            "httpTimeout": self.settings.firebase_timeout_seconds,
        }, name=f"cava-supervisor-{uuid.uuid4().hex}")

    def reference(self, suffix: str = ""):
        if self.app is None:
            raise RuntimeError("Firebase no inicializado")
        return db.reference(ROOT_PATH + suffix, app=self.app)

    def read_zone(self) -> dict:
        value = self.reference().get()
        if not isinstance(value, dict):
            raise ValueError("No hay datos de la zona de crianza")
        return value

    def listen(self, callback: Callable):
        # Exactamente un registro vivo por runtime. El SDK reconecta su SSE.
        return self.reference("/ambiente").listen(callback)

    @staticmethod
    def listener_alive(registration) -> bool:
        # La API experimental no expone salud pública del hilo. Aislar aquí
        # esta observación del SDK 7.7.0, sin alterar su transporte ni credenciales.
        thread = getattr(registration, "_thread", None)
        return thread is not None and thread.is_alive()

    def apply_control(self, expected: dict, target: bool, sample: Measurement) -> bool:
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN impide toda escritura Firebase")

        def update(current):
            sample.check_fresh(utc_now(), self.settings.max_measurement_age_seconds,
                               self.settings.future_tolerance_seconds)
            return control_update(current, expected, target)

        try:
            self.reference("/control").transaction(update)
            return True
        except NothingToChange:
            return False

    def publish_supervisor(self, payload: dict) -> None:
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN impide toda escritura Firebase")
        # Actualizar cuatro hijos, nunca reemplazar el nodo ni escribir ACK.
        self.reference("/supervisor").update(payload)

    def close(self) -> None:
        if self.app is not None:
            firebase_admin.delete_app(self.app)
            self.app = None
