"""Ejecuta solamente el emulador demo, sin heredar secretos ni DEBUG del shell."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    cache = Path(tempfile.gettempdir())
    environment = {name: os.environ[name] for name in ("PATH", "JAVA_HOME", "SSL_CERT_FILE", "SSL_CERT_DIR") if name in os.environ}
    environment.update({
        "CI": "true", "LANG": "C.UTF-8",
        "FIREBASE_EMULATORS_PATH": str(cache / "cava-paso9-emulators"),
        "XDG_CONFIG_HOME": str(cache / "cava-paso9-config"),
        "npm_config_cache": str(cache / "cava-paso9-npm-cache"),
    })
    result = subprocess.run(["npm", "run", "test:emulator"], cwd=ROOT / "tests/firebase",
        env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    log_path = cache / "cava-paso9-emulador-salida.log"
    log_path.write_text(result.stdout, encoding="utf-8")
    print("Proyecto: demo-cava-paso9; RTDB: 127.0.0.1:9019; sin credenciales de producción.")
    failure = False
    for line in result.stdout.splitlines():
        if line.startswith("not ok "):
            failure = True
        elif line.startswith(("ok ", "# Subtest:", "1..")):
            failure = False
        if failure or line.startswith(("ok ", "not ok ", "# tests", "# pass", "# fail", "# skipped", "# duration_ms", "Error:", "✔", "⚠")):
            print(line)
    print(f"Registro local de datos simulados: {log_path}")
    if result.returncode:
        print(f"El emulador o las pruebas fallaron (código {result.returncode}); revisar el registro local.")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
