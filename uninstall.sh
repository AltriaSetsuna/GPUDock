#!/usr/bin/env bash
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  __gpudock_uninstall_sourced=1
  __gpudock_uninstall_shell_opts="$(set +o)"
else
  __gpudock_uninstall_sourced=0
fi

gpudock_uninstall_finish() {
  local status="${1:-0}"
  if [[ "${__gpudock_uninstall_sourced}" -eq 1 ]]; then
    eval "${__gpudock_uninstall_shell_opts}"
    return "${status}"
  fi
  exit "${status}"
}

set -euo pipefail

BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/gpudock"
SHELL_RC="${HOME}/.bashrc"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
MARKER_START="# >>> GPUDock path >>>"
MARKER_END="# <<< GPUDock path <<<"

rm -f "${WRAPPER}"

if [[ -f "${SHELL_RC}" ]]; then
  "${PYTHON_BIN}" - "${SHELL_RC}" "${MARKER_START}" "${MARKER_END}" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

rc_path = Path(sys.argv[1])
start = sys.argv[2]
end = sys.argv[3]
lines = rc_path.read_text().splitlines(keepends=True)
out = []
inside = False
for line in lines:
    if line.strip() == start:
        inside = True
        continue
    if line.strip() == end:
        inside = False
        continue
    if not inside:
        out.append(line)
rc_path.write_text("".join(out))
PY
fi

echo "GPUDock command wrapper removed from ${WRAPPER}."
echo "Restart the shell, or remove ${BIN_DIR} from PATH manually if it was only used for GPUDock."

gpudock_uninstall_finish 0
