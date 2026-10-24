from pathlib import Path
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = "https://unidad4-aiot-cava-default-rtdb.firebaseio.com"
ROOT_PATH = "/bodega/zona_crianza"


class Settings(BaseModel):
    dry_run: bool = True
    firebase_database_url: str = DATABASE_URL
    firebase_credentials_path: Path | None = None
    firebase_timeout_seconds: float = Field(default=10, ge=1, le=60)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "auto"
    gemini_timeout_seconds: float = Field(default=20, ge=1, le=120)
    gemini_min_interval_seconds: float = Field(default=60, ge=10)
    gemini_cache_seconds: float = Field(default=300, ge=10)
    gemini_retry_seconds: float = Field(default=120, ge=10)
    gemini_retry_max_seconds: float = Field(default=900, ge=10)
    recovery_stable_seconds: float = Field(default=60, ge=1)
    max_measurement_age_seconds: float = Field(default=20, ge=1, le=300)
    max_sample_gap_seconds: float = Field(default=15, ge=1, le=300)
    future_tolerance_seconds: float = Field(default=5, ge=0, le=60)
    supervisor_publish_seconds: float = Field(default=60, ge=10)
    listener_retry_seconds: float = Field(default=5, ge=1, le=60)
    local_api_token: SecretStr | None = None
    supervisor_lock_file: Path = BASE_DIR / ".runtime/supervisor.lock"

    @field_validator("firebase_database_url")
    @classmethod
    def database_is_project(cls, value: str) -> str:
        if value.rstrip("/") != DATABASE_URL:
            raise ValueError("Usar la base existente de unidad4-aiot-cava")
        return DATABASE_URL

    @field_validator("firebase_credentials_path", "supervisor_lock_file", mode="after")
    @classmethod
    def absolute_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        expanded = value.expanduser()
        return expanded.resolve() if expanded.is_absolute() else (BASE_DIR / expanded).resolve()

    @model_validator(mode="after")
    def consistent_intervals(self):
        if self.max_sample_gap_seconds > self.max_measurement_age_seconds:
            raise ValueError("MAX_SAMPLE_GAP_SECONDS no debe superar MAX_MEASUREMENT_AGE_SECONDS")
        if self.gemini_retry_max_seconds < self.gemini_retry_seconds:
            raise ValueError("El máximo de reintento Gemini debe ser mayor o igual al inicial")
        return self

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)
        values = {}
        for name in cls.model_fields:
            raw = os.getenv(name.upper())
            if raw is not None and raw.strip():
                values[name] = raw.strip()
        return cls.model_validate(values)

    def validate_real_mode(self) -> None:
        if not self.dry_run:
            if not self.firebase_credentials_path or not self.firebase_credentials_path.is_file():
                raise ValueError("Modo real bloqueado: faltan credenciales Firebase válidas")
            if not self.local_api_token or len(self.local_api_token.get_secret_value()) < 24:
                raise ValueError("Modo real bloqueado: configurar LOCAL_API_TOKEN de al menos 24 caracteres")
