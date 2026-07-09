from __future__ import annotations

from typer.testing import CliRunner

from cmddock.cli import app
from cmddock.service_state import ServiceState, write_service_state


def test_status_reports_not_running(tmp_path):
    result = CliRunner().invoke(app, ["status", "--data-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "GPUDock is not running." in result.output


def test_status_reports_running_service(tmp_path):
    write_service_state(
        tmp_path,
        ServiceState(pid=1, host="127.0.0.1", port=45678, data_dir=str(tmp_path)),
    )

    result = CliRunner().invoke(app, ["status", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert '"status": "running"' in result.output
    assert '"port": 45678' in result.output
    assert '"url": "http://127.0.0.1:45678/"' in result.output
