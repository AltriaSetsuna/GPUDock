from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(".cmddock")
    host: str = "127.0.0.1"
    port: int = 8765
    poll_interval_seconds: float = 1.0

    @property
    def database_path(self) -> Path:
        return self.data_dir / "cmddock.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def build_settings(
    data_dir: Path | str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> Settings:
    resolved_data_dir = Path(data_dir) if data_dir is not None else Path(".cmddock")
    return Settings(data_dir=resolved_data_dir, host=host, port=port)
