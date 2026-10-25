import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from main import create_app
from supervisor.config import Settings
from conftest import wait_listener


@asynccontextmanager
async def api(setup, client_ip="127.0.0.1"):
    clock, settings, repo, analyzer, _ = setup
    analyzer.configured = False
    app = create_app(settings, repository=repo, analyzer=analyzer)
    async with app.router.lifespan_context(app):
        runtime = app.state.supervisor
        # El fixture usa una fecha fija; la API comparte ese reloj explícito.
        runtime.now = clock.now
        runtime.monotonic = clock.monotonic
        await wait_listener(runtime)
        await runtime.queue.join()
        transport = httpx.ASGITransport(app=app, client=(client_ip, 50123))
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            yield client, runtime


async def test_health_status_openapi_and_protected_evaluation(setup):
    async with api(setup) as (client, runtime):
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["dry_run"] is True
        assert health.json()["listener_activo"] is True
        assert health.json()["datos_recientes"] is True
        response = await client.get("/status")
        assert response.status_code == 200
        assert response.json()["ultima_evaluacion"]["decision"]["estado"] == "normal"
        assert response.json()["ultima_comunicacion_valida"].endswith("Z")
        assert (await client.post("/evaluar", json={})).status_code == 403
        response = await client.post("/evaluar", json={}, headers={"X-Local-Token": "x"*32})
        assert response.status_code == 200
        assert response.json()["publicacion"] == "dry_run_sin_escrituras"
        assert (await client.get("/openapi.json")).status_code == 200
        assert (await client.get("/docs")).status_code == 200
        assert "x"*32 not in (await client.get("/status")).text
    assert runtime.repository.closed and runtime.analyzer.closed


async def test_rejects_simulated_measurements_bad_host_and_open_cors(setup):
    async with api(setup) as (client, _):
        response = await client.post("/evaluar", json={"temperatura": 24}, headers={"X-Local-Token":"x"*32})
        assert response.status_code == 422
        assert (await client.get("/health", headers={"Host":"attacker.example"})).status_code == 400
        cors = await client.options("/evaluar", headers={"Origin":"https://attacker.example", "Access-Control-Request-Method":"POST"})
        assert "access-control-allow-origin" not in cors.headers


async def test_remote_peer_cannot_use_token_or_forwarded_header(setup):
    async with api(setup, "203.0.113.10") as (client, _):
        response = await client.post("/evaluar", json={}, headers={
            "X-Local-Token":"x"*32, "X-Forwarded-For":"127.0.0.1",
        })
        assert response.status_code == 403


@pytest.mark.parametrize("token", [b"token-incorrecto", b"\xc3\xa1-token-no-ascii"], ids=["incorrecto", "no-ascii"])
async def test_malformed_local_token_is_rejected_without_server_error(setup, token):
    async with api(setup) as (client, runtime):
        response = await client.post("/evaluar", json={}, headers=[(b"X-Local-Token", token)])
        assert response.status_code == 403
        assert runtime.repository.actions == runtime.repository.publications == []


async def test_invalid_and_disconnected_firebase_return_controlled_errors(setup):
    async with api(setup) as (client, runtime):
        runtime.repository.zone["ambiente"] = None
        assert (await client.post("/evaluar", headers={"X-Local-Token":"x"*32})).status_code == 409
        runtime.repository.fail_read = True
        assert (await client.post("/evaluar", headers={"X-Local-Token":"x"*32})).status_code == 503


async def test_default_start_without_secrets_is_degraded_but_serves_health(tmp_path):
    settings = Settings(supervisor_lock_file=tmp_path/"default.lock")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)), base_url="http://localhost") as client:
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json()["estado"] == "degradado"
            assert health.json()["firebase_configurado"] is False
            assert (await client.post("/evaluar")).status_code == 503


async def test_real_mode_without_verified_config_is_blocked(tmp_path):
    app = create_app(Settings(dry_run=False, supervisor_lock_file=tmp_path/"real.lock"))
    with pytest.raises(ValueError, match="Modo real bloqueado"):
        async with app.router.lifespan_context(app):
            pytest.fail("No debe iniciar modo real sin configuración")
