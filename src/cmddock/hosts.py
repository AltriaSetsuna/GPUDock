from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

LOCAL_RESOURCE = "local"
DEFAULT_CONFIG_NAME = "gpu_hosts.conf"


@dataclass(frozen=True)
class HostConfig:
    name: str
    hostname: str
    user: str | None = None
    port: int | None = None
    identity_file: Path | None = None

    @property
    def resource_id(self) -> str:
        return self.name


@dataclass(frozen=True)
class RemoteEnvBinding:
    env_name: str
    env_value: str | None = None
    host_name: str | None = None


@dataclass(frozen=True)
class GPUHostConfig:
    hosts: dict[str, HostConfig]
    remote_env_bindings: tuple[RemoteEnvBinding, ...]

    def select_resource_for_env(self, env: dict[str, str]) -> GPUResourceSelection:
        matches: list[str] = []
        for binding in self.remote_env_bindings:
            env_value = _remote_env_value(env, binding.env_name)
            if env_value is None or _is_local_target(env_value):
                continue
            if binding.env_value is None:
                matches.append(binding.host_name or env_value)
            elif env_value == binding.env_value and binding.host_name is not None:
                matches.append(binding.host_name)
        unique_matches = sorted(set(matches))
        if len(unique_matches) > 1:
            raise ValueError(
                "Command matches multiple remote GPU hosts: " + ", ".join(unique_matches)
            )
        if unique_matches:
            host_name = unique_matches[0]
            return GPUResourceSelection(host_name, self.get_host(host_name))

        vllm_selection = self._select_implicit_vllm_resource(env)
        if vllm_selection is not None:
            return vllm_selection

        return GPUResourceSelection(LOCAL_RESOURCE, None)

    def resource_for_env(self, env: dict[str, str]) -> str:
        return self.select_resource_for_env(env).resource_id

    def get_host(self, resource_id: str) -> HostConfig | None:
        if resource_id == LOCAL_RESOURCE:
            return None
        try:
            return self.hosts[resource_id]
        except KeyError as exc:
            raise ValueError(f"Remote GPU host '{resource_id}' is not configured.") from exc

    def _select_implicit_vllm_resource(
        self,
        env: dict[str, str],
    ) -> GPUResourceSelection | None:
        target = _remote_env_value(env, "VLLM_TARGET")
        if target is None:
            return None
        if _is_local_target(target):
            return GPUResourceSelection(LOCAL_RESOURCE, None)
        if target in self.hosts:
            return GPUResourceSelection(target, self.hosts[target])

        dynamic_host = _host_config_from_vllm_env(target, env)
        if dynamic_host is not None:
            return GPUResourceSelection(dynamic_host.resource_id, dynamic_host)

        raise ValueError(
            f"Remote GPU target VLLM_TARGET={target!r} was found, but GPUDock cannot "
            "resolve it. Configure a matching Host block in gpu_hosts.conf or provide "
            f"VLLM_{_vllm_target_key(target)}_HOST in the referenced vLLM config."
        )


@dataclass(frozen=True)
class GPUResourceSelection:
    resource_id: str
    host_config: HostConfig | None = None


def default_gpu_hosts_config_path(data_dir: Path) -> Path:
    return data_dir / DEFAULT_CONFIG_NAME


def load_gpu_host_config(path: Path | None) -> GPUHostConfig:
    if path is None or not path.exists():
        return GPUHostConfig(hosts={}, remote_env_bindings=())
    return parse_gpu_host_config(path.read_text(errors="replace"), base_dir=path.parent)


def parse_gpu_host_config(text: str, base_dir: Path | None = None) -> GPUHostConfig:
    hosts: dict[str, HostConfig] = {}
    bindings: list[RemoteEnvBinding] = []
    current_host: str | None = None
    current_values: dict[str, str] = {}

    def flush_host() -> None:
        nonlocal current_host, current_values
        if current_host is None:
            return
        hostname = current_values.get("hostname")
        if not hostname:
            raise ValueError(f"Host {current_host} is missing HostName.")
        port_value = current_values.get("port")
        port = int(port_value) if port_value else None
        identity_file = current_values.get("identityfile")
        hosts[current_host] = HostConfig(
            name=current_host,
            hostname=hostname,
            user=current_values.get("user"),
            port=port,
            identity_file=_expand_path(identity_file, base_dir) if identity_file else None,
        )
        current_host = None
        current_values = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = shlex.split(line, comments=True)
        if not parts:
            continue
        key = parts[0].lower()
        values = parts[1:]
        if key == "host":
            if len(values) != 1:
                raise ValueError("Host line must contain exactly one host alias.")
            flush_host()
            current_host = values[0]
            current_values = {}
            continue
        if key in {"remoteenv", "remote_env", "gpuenv", "gpu_env"}:
            flush_host()
            if len(values) not in {1, 3}:
                raise ValueError(
                    "RemoteEnv lines must use either 'RemoteEnv ENV_NAME' or "
                    "'RemoteEnv ENV_NAME ENV_VALUE HOST_ALIAS'."
                )
            if len(values) == 1:
                bindings.append(RemoteEnvBinding(env_name=values[0]))
            else:
                bindings.append(
                    RemoteEnvBinding(env_name=values[0], env_value=values[1], host_name=values[2])
                )
            continue
        if current_host is None:
            raise ValueError(f"Unexpected config line outside a Host block: {raw_line}")
        if len(values) != 1:
            raise ValueError(f"Host option {parts[0]} must contain exactly one value.")
        current_values[key] = values[0]

    flush_host()
    for binding in bindings:
        if binding.host_name is not None and binding.host_name not in hosts:
            raise ValueError(
                f"RemoteEnv {binding.env_name}={binding.env_value} references unknown host "
                f"'{binding.host_name}'."
            )
    return GPUHostConfig(hosts=hosts, remote_env_bindings=tuple(bindings))


def _expand_path(value: str, base_dir: Path | None) -> Path:
    normalized = value.replace("\\", "/")
    path = Path(normalized).expanduser()
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


def _remote_env_value(env: dict[str, str], env_name: str) -> str | None:
    value = env.get(env_name)
    if value is None and env_name == "VLLM_TARGET":
        value = env.get("VLLM_TARGET_DEFAULT")
    return value


def _is_local_target(value: str) -> bool:
    return value.strip().lower() in {"", LOCAL_RESOURCE, "localhost", "127.0.0.1"}


def _host_config_from_vllm_env(target: str, env: dict[str, str]) -> HostConfig | None:
    target_key = _vllm_target_key(target)
    hostname = env.get(f"VLLM_{target_key}_HOST") or env.get("VLLM_HOST")
    if not hostname:
        return None
    port_value = env.get(f"VLLM_{target_key}_SSH_PORT")
    identity_file = env.get(f"VLLM_{target_key}_SSH_KEY") or env.get("VLLM_SSH_KEY")
    user = env.get(f"VLLM_{target_key}_USER") or env.get("VLLM_USER")
    return HostConfig(
        name=target,
        hostname=hostname,
        user=user,
        port=int(port_value) if port_value else None,
        identity_file=Path(identity_file).expanduser() if identity_file else None,
    )


def _vllm_target_key(target: str) -> str:
    return target.upper().replace("-", "_")


def build_ssh_command(host: HostConfig, remote_command: list[str]) -> list[str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=1",
    ]
    if host.port is not None:
        cmd.extend(["-p", str(host.port)])
    if host.identity_file is not None:
        cmd.extend(["-i", str(host.identity_file)])
    target = host.hostname
    if host.user:
        target = f"{host.user}@{target}"
    cmd.append(target)
    cmd.extend(remote_command)
    return cmd
