"""Multi-account rotation for the internal flow-data API."""

from __future__ import annotations

import itertools
import json
import threading
from pathlib import Path
from typing import Iterator, Optional


DEFAULT_ACCOUNTS_FILE = Path(__file__).resolve().parent.parent / "accounts.json"


class AccountPool:
    """Round-robin account pool; yields (slot, username, password)."""

    def __init__(self, accounts_file: Optional[str | Path] = None) -> None:
        self._path = Path(accounts_file) if accounts_file else DEFAULT_ACCOUNTS_FILE
        self._mtime = 0.0
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        # stat before read: a file written during the read leaves a newer mtime
        # behind, so the next reload_if_changed notices and reads it again
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            mtime = 0.0
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        entries = payload.get("accounts", payload) if isinstance(payload, dict) else payload
        accounts: list[tuple[int, str, str]] = [
            (index, str(item["username"]), str(item["password"]))
            for index, item in enumerate(entries)
        ]
        if not accounts:
            raise ValueError(f"no accounts found in {self._path}")
        with self._lock:
            self._accounts = accounts
            self._cycle: Iterator[tuple[int, str, str]] = itertools.cycle(accounts)
            self._by_slot = {slot: (username, password) for slot, username, password in accounts}
            # slot -> username mapping for trace logging (passwords never logged)
            self.slots = {slot: username for slot, username, _ in accounts}
        self._mtime = mtime

    def reload_if_changed(self) -> bool:
        """Pick up a credentials file edited since it was last read.

        The pool is read once per process, and the tokens and cooldowns hung off
        it are keyed by slot number.  Without this, a renewed account waits for a
        service restart - a bad trade when the whole pool has just been suspended
        and somebody is fixing it by hand.  A bad edit is ignored rather than
        allowed to take the pool down with it.
        """
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return False
        if mtime == self._mtime:
            return False
        try:
            self._load()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return False
        return True

    def __len__(self) -> int:
        return len(self._accounts)

    def next(self) -> tuple[int, str, str]:
        with self._lock:
            return next(self._cycle)

    def credentials(self, slot: int) -> tuple[str, str]:
        """(username, password) for a slot — passwords never leave this class."""
        return self._by_slot[slot]
