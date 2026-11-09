"""Per-run state saved beside the outputs, so a stopped run can resume without repeating paid steps."""

from __future__ import annotations

import json
import os
from pathlib import Path

STATE_FILE = "run-state.json"
_VERSION = 1


def write_text_atomic(path: Path, text: str) -> None:
    """Write via a temp file and rename, so a kill mid-write never leaves a partial file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class RunState:
    """Values and finished steps of one run, saved to <folder>/run-state.json on every change."""

    def __init__(self, folder: Path, values: dict, done: list[str]) -> None:
        self.folder = folder
        self._values = values
        self._done = done

    @classmethod
    def create(cls, folder: Path, **values) -> RunState:
        folder.mkdir(parents=True, exist_ok=True)
        state = cls(folder, dict(values), [])
        state._save()
        return state

    @classmethod
    def load(cls, folder: Path) -> RunState:
        path = folder / STATE_FILE
        if not path.exists():
            raise FileNotFoundError(f"No {STATE_FILE} in '{folder}' — nothing to resume.")
        try:
            data = json.loads(path.read_text())
            values, done = data["values"], data["done"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"'{path}' is unreadable ({e!r}).") from e
        if data.get("version") != _VERSION:
            raise ValueError(f"'{path}' has state version {data.get('version')!r}, expected {_VERSION}.")
        return cls(folder, values, done)

    @property
    def finished(self) -> list[str]:
        return list(self._done)

    def get(self, key: str, default=None):
        return self._values.get(key, default)

    def is_done(self, step: str) -> bool:
        return step in self._done

    def set(self, **values) -> None:
        self._values.update(values)
        self._save()

    def complete(self, step: str, **values) -> None:
        """Record values and mark the step done in one write. Call only after its output is on disk."""
        self._values.update(values)
        if step not in self._done:
            self._done.append(step)
        self._save()

    def forget(self, steps: list[str]) -> None:
        """Mark steps as not done, so they run again. Their values and files are left alone."""
        self._done[:] = [step for step in self._done if step not in steps]
        self._save()

    def _save(self) -> None:
        payload = {"version": _VERSION, "values": self._values, "done": self._done}
        write_text_atomic(self.folder / STATE_FILE, json.dumps(payload, indent=2, ensure_ascii=False))
