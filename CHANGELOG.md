# Changelog

## 0.2.0

- Added `serial` and `parallel` queue modes using a single unified `commands` table.
- Added `queue` to command creation, command records, CLI filters, and HTTP filters.
- Added a parallel dispatcher that immediately starts all pending parallel commands.
- Preserved default serial behavior for existing usage.
- Documented the single-table queue-mode design in `docs/design.md`.

## 0.1.0

- Added the initial local command queue daemon.
- Added SQLite persistence, CLI commands, HTTP API, logs, kill/requeue behavior, and tests.
