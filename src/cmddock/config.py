from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cmddock.hosts import default_gpu_hosts_config_path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(".cmddock")
    host: str = "127.0.0.1"
    port: int = 8765
    poll_interval_seconds: float = 1.0
    gpu_hosts_config_path: Path | None = None

    @property
    def database_path(self) -> Path:
        return self.data_dir / "cmddock.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def resolved_gpu_hosts_config_path(self) -> Path:
        return self.gpu_hosts_config_path or default_gpu_hosts_config_path(self.data_dir)


def build_settings(
    data_dir: Path | str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    gpu_hosts_config: Path | str | None = None,
) -> Settings:
    resolved_data_dir = Path(data_dir) if data_dir is not None else Path(".cmddock")
    resolved_gpu_hosts_config = Path(gpu_hosts_config) if gpu_hosts_config is not None else None
    return Settings(
        data_dir=resolved_data_dir,
        host=host,
        port=port,
        gpu_hosts_config_path=resolved_gpu_hosts_config,
    )
