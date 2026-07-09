#!/usr/bin/env bash
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  __gpudock_install_sourced=1
  __gpudock_install_shell_opts="$(set +o)"
else
  __gpudock_install_sourced=0
fi

gpudock_install_finish() {
  local status="${1:-0}"
  if [[ "${__gpudock_install_sourced}" -eq 1 ]]; then
    eval "${__gpudock_install_shell_opts}"
    return "${status}"
  fi
  exit "${status}"
}

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/gpudock"
SHELL_RC="${HOME}/.bashrc"
MARKER_START="# >>> GPUDock path >>>"
MARKER_END="# <<< GPUDock path <<<"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but was not found in PATH." >&2
  gpudock_install_finish 1
fi

mkdir -p "${BIN_DIR}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  uv venv "${VENV_DIR}"
fi

uv pip install --python "${VENV_DIR}/bin/python" -e "${ROOT_DIR}"

cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

if [[ "\${1:-}" == "--help" || "\${1:-}" == "--version" ]]; then
  exec "${VENV_DIR}/bin/gpudock" "\$@"
fi

if [[ "\$#" -eq 0 ]]; then
  exec "${VENV_DIR}/bin/gpudock"
fi

has_data_dir=0
for arg in "\$@"; do
  if [[ "\${arg}" == "--data-dir" || "\${arg}" == --data-dir=* ]]; then
    has_data_dir=1
    break
  fi
done

if [[ "\${has_data_dir}" -eq 1 ]]; then
  exec "${VENV_DIR}/bin/gpudock" "\$@"
fi

exec "${VENV_DIR}/bin/gpudock" "\$@" --data-dir "${ROOT_DIR}/.cmddock"
EOF
chmod +x "${WRAPPER}"

touch "${SHELL_RC}"
"${PYTHON_BIN}" - "${SHELL_RC}" "${BIN_DIR}" "${MARKER_START}" "${MARKER_END}" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

rc_path = Path(sys.argv[1])
bin_dir = sys.argv[2]
start = sys.argv[3]
end = sys.argv[4]
block = f"{start}\nexport PATH=\"{bin_dir}:$PATH\"\n{end}\n"
text = rc_path.read_text() if rc_path.exists() else ""
lines = text.splitlines(keepends=True)
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
if out and not out[-1].endswith("\n"):
    out[-1] += "\n"
out.append(block)
rc_path.write_text("".join(out))
PY

export PATH="${BIN_DIR}:${PATH}"

if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
  export PATH="${BIN_DIR}:${PATH}"
fi

echo "GPUDock installed."
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "For this terminal, run: export PATH=\"${BIN_DIR}:\$PATH\""
  echo "Or install with: source ./install.sh"
else
  echo "Current shell PATH updated."
fi
echo "Command path: ${WRAPPER}"
echo "Run: gpudock serve"

gpudock_install_finish 0
