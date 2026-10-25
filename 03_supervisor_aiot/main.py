from contextlib import asynccontextmanager
import ipaddress
import logging
import secrets

from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import APIKeyHeader

from supervisor.config import Settings
from supervisor.firebase import FirebaseRepository
from supervisor.gemini import GeminiAnalyzer
from supervisor.models import EvaluateRequest, Evaluation, HealthResponse, StatusResponse
from supervisor.runtime import Supervisor

local_token = APIKeyHeader(name="X-Local-Token", auto_error=False)


def create_app(settings: Settings | None = None, *, repository=None, analyzer=None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger = logging.getLogger("cava.supervisor")
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        runtime = Supervisor(settings, repository or FirebaseRepository(settings), analyzer or GeminiAnalyzer(settings))
        app.state.supervisor = runtime
        try:
            await runtime.start()
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="Supervisor AIoT de la Cava Inteligente", version="1.0.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request):
        # Diagnóstico local: no dispara una petición de red por cada health check.
        return request.app.state.supervisor.status().health

    @app.get("/status", response_model=StatusResponse)
    async def status(request: Request):
        return request.app.state.supervisor.status()

    @app.post("/evaluar", response_model=Evaluation)
    async def evaluate(request: Request, payload: EvaluateRequest | None = None,
                       token: str | None = Security(local_token)):
        try:
            is_local = ipaddress.ip_address(request.client.host).is_loopback
        except (ValueError, AttributeError):
            is_local = False
        if not is_local:
            raise HTTPException(403, "La evaluación solo se permite desde loopback")
        configured = settings.local_api_token.get_secret_value() if settings.local_api_token else ""
        if len(configured) < 24:
            raise HTTPException(503, "Configurar LOCAL_API_TOKEN de al menos 24 caracteres para habilitar este endpoint")
        # compare_digest(str, str) rechaza caracteres no ASCII con TypeError.
        if not token or not secrets.compare_digest(configured.encode("utf-8"), token.encode("utf-8")):
            raise HTTPException(403, "Token local inválido o ausente")
        runtime = request.app.state.supervisor
        result = await runtime.evaluate()
        if result is None:
            code = 409 if runtime.firebase_ok else 503
            raise HTTPException(code, "No hay datos válidos y recientes para evaluar. Consultá /status.")
        return result

    return app


app = create_app()
