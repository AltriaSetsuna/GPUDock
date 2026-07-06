from __future__ import annotations

DEFAULT_MIN_IDLE_SECONDS = 120
MAX_MIN_IDLE_SECONDS = 24 * 60 * 60


def normalize_min_idle_seconds(value: int | None) -> int:
    if value is None:
        return DEFAULT_MIN_IDLE_SECONDS
    if value < 0:
        raise ValueError("min_idle_seconds must be greater than or equal to 0.")
    if value > MAX_MIN_IDLE_SECONDS:
        raise ValueError(f"min_idle_seconds must be no greater than {MAX_MIN_IDLE_SECONDS}.")
    return value
