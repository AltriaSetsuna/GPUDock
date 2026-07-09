from __future__ import annotations

from pathlib import Path

from cmddock.emailer import EmailConfig, send_launch_email


def test_email_config_requires_environment_values(monkeypatch):
    monkeypatch.setattr("cmddock.emailer.Path.home", lambda: Path("/missing-home"))
    monkeypatch.setattr("cmddock.emailer._load_shell_email_settings", lambda: {})
    for name in [
        "GPUDOCK_EMAIL_RECEIVER",
        "GPUDOCK_EMAIL_SENDER",
        "GPUDOCK_EMAIL_PASSWORD",
        "GPUDOCK_SMTP_SERVER",
        "GPUDOCK_SMTP_PORT",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = EmailConfig()

    assert config.receiver is None
    assert config.sender is None
    assert config.password is None
    assert config.smtp_server is None
    assert config.smtp_port == 465
    assert not config.enabled


def test_email_config_can_read_gpudock_bashrc_block(tmp_path, monkeypatch):
    monkeypatch.setattr("cmddock.emailer.Path.home", lambda: tmp_path)
    monkeypatch.delenv("GPUDOCK_EMAIL_RECEIVER", raising=False)
    monkeypatch.delenv("GPUDOCK_EMAIL_SENDER", raising=False)
    monkeypatch.delenv("GPUDOCK_EMAIL_PASSWORD", raising=False)
    monkeypatch.delenv("GPUDOCK_SMTP_SERVER", raising=False)
    monkeypatch.delenv("GPUDOCK_SMTP_PORT", raising=False)
    from cmddock import emailer

    emailer._load_shell_email_settings.cache_clear()
    (tmp_path / ".bashrc").write_text(
        "# >>> GPUDock email settings >>>\n"
        "export GPUDOCK_EMAIL_RECEIVER='receiver@example.com'\n"
        "export GPUDOCK_EMAIL_SENDER='sender@example.com'\n"
        "export GPUDOCK_EMAIL_PASSWORD='secret'\n"
        "export GPUDOCK_SMTP_SERVER='smtp.example.com'\n"
        "export GPUDOCK_SMTP_PORT='465'\n"
        "# <<< GPUDock email settings <<<\n",
    )

    config = EmailConfig()

    assert config.enabled
    assert config.receiver == "receiver@example.com"
    assert config.smtp_server == "smtp.example.com"
    emailer._load_shell_email_settings.cache_clear()


def test_launch_email_labels_remote_gpu_resource(monkeypatch):
    messages = []

    class FakeSMTP:
        def __init__(self, smtp_server, smtp_port):
            assert smtp_server == "smtp.example.com"
            assert smtp_port == 465

        def login(self, sender, password):
            assert sender == "sender@example.com"
            assert password == "secret"

        def send_message(self, msg):
            messages.append(msg)

        def quit(self):
            pass

    monkeypatch.setattr("cmddock.emailer.smtplib.SMTP_SSL", FakeSMTP)
    config = EmailConfig(
        receiver="receiver@example.com",
        sender="sender@example.com",
        password="secret",
        smtp_server="smtp.example.com",
        smtp_port=465,
    )

    send_launch_email(
        script_path="/tmp/train.sh",
        selected_gpus=[6, 7],
        idle_gpus=[6, 7],
        command_id=17,
        gpu_resource="node1",
        config=config,
    )

    body = messages[0].get_payload(0).get_payload(decode=True).decode("utf-8")
    assert "GPU 资源: node1" in body
    assert "使用 GPU: node1:6, node1:7" in body
    assert "当前可用 GPU: node1:6, node1:7" in body
