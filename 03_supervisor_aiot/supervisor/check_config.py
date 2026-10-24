"""Comprobaciones explícitas de solo lectura; nunca escribe Firebase."""
import argparse
import asyncio
import importlib.metadata

from .config import BASE_DIR, Settings
from .firebase import FirebaseRepository
from .gemini import GeminiAnalyzer, diagnose_failure, select_model
from .models import ControlState, Measurement, utc_now
from .rules import EnvironmentalRules


def print_failure(error: Exception, *, phase: str) -> None:
    diagnostic = diagnose_failure(error, phase=phase)
    print(f"Comprobación fallida ({phase}).")
    print(f"Tipo de excepción: {diagnostic.exception_type}")
    print(f"Código HTTP: {diagnostic.http_code if diagnostic.http_code is not None else 'no disponible'}")
    print(f"Motivo: {diagnostic}")
    print(f"Causa: {diagnostic.cause}")
    print(f"Qué revisar: {diagnostic.advice}")
    print("No se escribió Firebase. No se muestran mensajes privados del proveedor.")


async def check(args) -> int:
    try:
        settings = Settings.from_env()
    except Exception as error:
        print_failure(error, phase="configuracion")
        return 1
    for package in ("fastapi", "uvicorn", "firebase-admin", "google-genai", "pydantic", "pytest"):
        print(f"{package}={importlib.metadata.version(package)}")
    print(f"DRY_RUN={settings.dry_run}")
    print(f"Archivo .env: {BASE_DIR / '.env'} (existe={BASE_DIR.joinpath('.env').is_file()}; las variables exportadas tienen prioridad)")
    print(f"Firebase credenciales presentes={bool(settings.firebase_credentials_path and settings.firebase_credentials_path.is_file())}")
    print(f"Gemini API key configurada={bool(settings.gemini_api_key)}")
    print(f"GEMINI_MODEL={settings.gemini_model}")
    print(f"Token local válido={bool(settings.local_api_token and len(settings.local_api_token.get_secret_value()) >= 24)}")
    analyzer, repository = GeminiAnalyzer(settings), None
    phase, exit_code = "solicitud", 0
    try:
        if args.check_firebase:
            phase = "firebase"
            repository = FirebaseRepository(settings)
            await asyncio.to_thread(repository.open)
            zone = await asyncio.to_thread(repository.read_zone)
            sample = Measurement.model_validate(zone.get("ambiente"))
            sample.check_fresh(utc_now(), settings.max_measurement_age_seconds, settings.future_tolerance_seconds)
            ControlState.model_validate(zone.get("control"))
            print("Firebase: lectura administrativa correcta; medición reciente y control válidos")
        if args.list_models:
            phase = "listar_modelos"
            models = await analyzer.list_models()
            for model in models:
                if "generateContent" in (model.supported_actions or []):
                    print(model.name)
            analyzer.model = select_model(models, settings.gemini_model)
            print("Modelo seleccionado:", analyzer.model)
            print("La compatibilidad JSON/Pydantic se verifica con --probe-gemini")
        if args.probe_gemini:
            phase = "generacion_estructurada"
            print("Prueba aislada de IA: 16 °C / 70 %. No se publica ni se actúa sobre Firebase.")
            print("Modelo utilizado:", await analyzer.resolve_model())
            sample = Measurement(temperatura=16, humedad=70, timestamp=utc_now())
            control = ControlState(extractor_solicitado=False, origen="manual")
            decision = EnvironmentalRules(settings).evaluate(sample, control, utc_now())
            result = await analyzer.analyze(sample, decision)
            print("Generación estructurada: exitosa")
            print("Validación JSON/Pydantic: exitosa (tipos estrictos y campos adicionales prohibidos)")
            print("Campos verificados: alerta_calidad (bool), forzar_climatizacion (bool), impacto_enologico (20 a 900 caracteres)")
            print(result.model_dump_json())
    except Exception as error:
        print_failure(error, phase=phase)
        exit_code = 1
    finally:
        try:
            await analyzer.close()
        except Exception as error:
            print_failure(error, phase="cierre_gemini")
            exit_code = 1
        if repository is not None:
            try:
                await asyncio.to_thread(repository.close)
            except Exception as error:
                print_failure(error, phase="firebase")
                exit_code = 1
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-firebase", action="store_true")
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--probe-gemini", action="store_true")
    raise SystemExit(asyncio.run(check(parser.parse_args())))


if __name__ == "__main__":
    main()
