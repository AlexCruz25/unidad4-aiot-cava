"""Compila y ejecuta las dos suites C++ en PC; no carga ni conecta el ESP32."""
import ctypes.util
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
FIRMWARE = ROOT / "01_firmware"


def main() -> None:
    try:
        result = subprocess.run(["pkg-config", "--cflags", "--libs", "libcjson"],
            capture_output=True, text=True, check=False)
        cjson = shlex.split(result.stdout) if result.returncode == 0 else []
    except FileNotFoundError:
        cjson = []
    if not cjson:
        # Alternativa del entorno verificado, sin descargar ni cambiar el sistema.
        header = Path.home() / ".arduino15/packages/esp32/tools/esp32-libs/3.3.11/include/json/cJSON"
        if not (header / "cJSON.h").is_file() or not ctypes.util.find_library("cjson"):
            raise SystemExit("Falta cJSON para PC. En Ubuntu instalar build-essential, pkg-config y libcjson-dev.")
        cjson = [f"-I{header}", "-l:libcjson.so.1"]
    with tempfile.TemporaryDirectory(prefix="cava-paso9-cpp-") as build:
        for name, source, flags in [("ack", "firebase_ack.cpp", []), ("sse", "sse_parser.cpp", cjson)]:
            binary = str(Path(build) / name)
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                f"-I{FIRMWARE / 'cava_esp32'}", str(FIRMWARE / f"tests/test_{name}.cpp"),
                str(FIRMWARE / "cava_esp32" / source), *flags, "-o", binary], check=True)
            subprocess.run([binary], check=True)
    print("2 suites C++ aprobadas; sin prueba física ni handshake TLS real.")


if __name__ == "__main__":
    main()
