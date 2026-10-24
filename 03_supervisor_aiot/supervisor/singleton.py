import fcntl
from pathlib import Path


class InstanceLock:
    """Exclusión entre procesos del mismo equipo/checkout; no es un lease distribuido."""
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.file.close()
            self.file = None
            raise RuntimeError("Ya hay un supervisor activo. Usar un solo worker y la misma ruta de lock.") from error

    def close(self) -> None:
        if self.file:
            fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
            self.file = None
