from __future__ import annotations

import logging
import os
import smtplib
import threading
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailConfig:
    receiver: str | None = os.getenv("GPUDOCK_EMAIL_RECEIVER", "1744141921@qq.com")
    sender: str | None = os.getenv("GPUDOCK_EMAIL_SENDER", "1744141921@qq.com")
    password: str | None = os.getenv("GPUDOCK_EMAIL_PASSWORD", "zvlnwyusxlqpbhia")
    smtp_server: str = os.getenv("GPUDOCK_SMTP_SERVER", "smtp.qq.com")
    smtp_port: int = int(os.getenv("GPUDOCK_SMTP_PORT", "465"))

    @property
    def enabled(self) -> bool:
        return bool(self.receiver and self.sender and self.password)


def send_launch_email_async(
    *,
    script_path: str,
    selected_gpus: list[int],
    idle_gpus: list[int],
    command_id: int,
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
    config: EmailConfig,
) -> None:
    cuda_devices = ",".join(str(gpu_id) for gpu_id in selected_gpus)
    idle_text = ", ".join(str(gpu_id) for gpu_id in idle_gpus) if idle_gpus else "无"
    subject = "✅ GPUDock GPU 任务已启动"
    body = (
        "GPUDock 报告：GPU 空闲条件已满足，任务已启动。\n\n"
        f"任务 ID: {command_id}\n"
        f"脚本路径: {script_path}\n"
        f"使用 GPU: {cuda_devices}\n"
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
