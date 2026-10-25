"""Auditoría local de Git. Solo informa rutas/motivos; nunca valores privados."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def private_path(name: str) -> bool:
    path = Path(name)
    base = path.name.lower()
    if base.endswith(".example"):
        return False
    return (
        base in {".env", "secrets.h", "firebase-admin.json"}
        or (base.startswith(".env.") and base != ".env.example")
        or (base.endswith(".json") and any(tag in base for tag in ("service-account", "serviceaccount", "firebase-adminsdk")))
        or ("credentials" in path.parts and path.suffix.lower() in {".json", ".pem", ".key"})
    )


def content_findings(data: bytes) -> list[str]:
    findings = []
    if re.search(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----", data):
        findings.append("clave_privada_PEM")
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        payload = None
    if isinstance(payload, dict) and payload.get("type") == "service_account" and payload.get("private_key"):
        findings.append("cuenta_servicio_con_clave_privada")
    return findings


def main() -> int:
    files = [item.decode() for item in git("ls-files", "-z").split(b"\0") if item]
    untracked = [item.decode() for item in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if item]
    findings = []
    for name in files:
        if private_path(name):
            findings.append({"ruta": name, "motivo": "archivo_privado_rastreado"})
        # Comprobar tanto el índice como la copia de trabajo sin imprimir blobs.
        index = git("show", f":{name}")
        working = ROOT / name
        sources = {"indice": index}
        if working.is_file():
            sources["trabajo"] = working.read_bytes()
        for source, data in sources.items():
            for reason in content_findings(data):
                findings.append({"ruta": name, "origen": source, "motivo": reason})
    for name in untracked:
        if private_path(name):
            findings.append({"ruta": name, "motivo": "archivo_privado_sin_ignorar"})
        working = ROOT / name
        if working.is_file():
            for reason in content_findings(working.read_bytes()):
                findings.append({"ruta": name, "origen": "sin_rastrear", "motivo": reason})
    history_names = set(git("log", "--all", "--format=", "--name-only").decode().splitlines())
    historical = sorted(name for name in history_names if name and private_path(name))
    print(json.dumps({"archivos_rastreados_revisados": len(files), "archivos_publicos_sin_rastrear_revisados": len(untracked), "hallazgos": findings,
        "rutas_privadas_en_historial": historical,
        "alcance": "rutas históricas; contenido de índice y trabajo; no escaneo exhaustivo de secretos o blobs históricos"}, ensure_ascii=False, indent=2))
    return int(bool(findings or historical))


if __name__ == "__main__":
    raise SystemExit(main())
