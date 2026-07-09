from __future__ import annotations

import logging
import os
import smtplib
import threading
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailConfig:
    receiver: str | None = field(default_factory=lambda: _getenv_optional("GPUDOCK_EMAIL_RECEIVER"))
    sender: str | None = field(default_factory=lambda: _getenv_optional("GPUDOCK_EMAIL_SENDER"))
    password: str | None = field(default_factory=lambda: _getenv_optional("GPUDOCK_EMAIL_PASSWORD"))
    smtp_server: str | None = field(default_factory=lambda: _getenv_optional("GPUDOCK_SMTP_SERVER"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("GPUDOCK_SMTP_PORT", "465")))

    @property
    def enabled(self) -> bool:
        return bool(self.receiver and self.sender and self.password and self.smtp_server)


def send_launch_email_async(
    *,
    script_path: str,
    selected_gpus: list[int],
    idle_gpus: list[int],
    command_id: int,
    gpu_resource: str = "local",
    config: EmailConfig | None = None,
) -> None:
    email_config = config or EmailConfig()
    if not email_config.enabled:
        return
    threading.Thread(
        target=send_launch_email,
        kwargs={
            "script_path": script_path,
            "selected_gpus": list(selected_gpus),
            "idle_gpus": list(idle_gpus),
            "command_id": command_id,
            "gpu_resource": gpu_resource,
            "config": email_config,
        },
        daemon=True,
    ).start()


def send_launch_email(
    *,
    script_path: str,
    selected_gpus: list[int],
    idle_gpus: list[int],
    command_id: int,
    gpu_resource: str,
    config: EmailConfig,
) -> None:
    cuda_devices = ",".join(str(gpu_id) for gpu_id in selected_gpus)
    selected_text = _format_gpu_list(gpu_resource, selected_gpus)
    idle_text = _format_gpu_list(gpu_resource, idle_gpus) if idle_gpus else "无"
    subject = "✅ GPUDock GPU 任务已启动"
    body = (
        "GPUDock 报告：GPU 空闲条件已满足，任务已启动。\n\n"
        f"任务 ID: {command_id}\n"
        f"脚本路径: {script_path}\n"
        f"GPU 资源: {gpu_resource}\n"
        f"使用 GPU: {selected_text}\n"
        f"GPU_COUNT: {len(selected_gpus)}\n"
        f"当前可用 GPU: {idle_text}\n"
        f"注入环境: CUDA_DEVICES={cuda_devices}\n"
    )

    msg = MIMEMultipart()
    msg["From"] = config.sender
    msg["To"] = config.receiver
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        if config.smtp_port == 465:
            server = smtplib.SMTP_SSL(config.smtp_server, config.smtp_port)
        else:
            server = smtplib.SMTP(config.smtp_server, config.smtp_port)
            server.starttls()
        server.login(config.sender, config.password)
        server.send_message(msg)
        server.quit()
    except Exception:
        logger.exception("Failed to send GPUDock launch email")


def _getenv_optional(name: str) -> str | None:
    value = os.getenv(name)
    return value or None


def _format_gpu_list(resource_id: str, gpu_ids: list[int]) -> str:
    return ", ".join(f"{resource_id}:{gpu_id}" for gpu_id in gpu_ids)
