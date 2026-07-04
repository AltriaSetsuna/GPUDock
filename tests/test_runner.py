from __future__ import annotations

from cmddock.runner import classify_exit_code, run_command


def _write_script(tmp_path, body: str):
    script = tmp_path / "task.sh"
    script.write_text(body)
    return script


def test_classify_success():
    exit_status, killed = classify_exit_code(0)

    assert exit_status == "exited_zero"
    assert killed is False


def test_classify_signal_kill():
    exit_status, killed = classify_exit_code(-9)

    assert exit_status == "killed_by_signal:SIGKILL"
    assert killed is True


def test_classify_nonzero_exit():
    exit_status, killed = classify_exit_code(2)

    assert exit_status == "exited_nonzero:2"
    assert killed is False


def test_run_command_reports_pid(tmp_path):
    seen_pids = []
    script = _write_script(tmp_path, "printf hello")

    result = run_command(
        str(script),
        None,
        tmp_path / "stdout.log",
        tmp_path / "stderr.log",
        on_start=seen_pids.append,
    )

    assert result.exit_code == 0
    assert seen_pids
    assert (tmp_path / "stdout.log").read_text() == "hello"
