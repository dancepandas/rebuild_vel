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
        path = Path(accounts_file) if accounts_file else DEFAULT_ACCOUNTS_FILE
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("accounts", payload) if isinstance(payload, dict) else payload
        self._accounts: list[tuple[int, str, str]] = [
            (index, str(item["username"]), str(item["password"]))
            for index, item in enumerate(entries)
        ]
        if not self._accounts:
            raise ValueError(f"no accounts found in {path}")
        self._cycle: Iterator[tuple[int, str, str]] = itertools.cycle(self._accounts)
        self._lock = threading.Lock()
        self._by_slot = {slot: (username, password) for slot, username, password in self._accounts}
        # slot -> username mapping for trace logging (passwords never logged)
        self.slots = {slot: username for slot, username, _ in self._accounts}

    def __len__(self) -> int:
        return len(self._accounts)

    def next(self) -> tuple[int, str, str]:
        with self._lock:
            return next(self._cycle)

    def credentials(self, slot: int) -> tuple[str, str]:
        """(username, password) for a slot — passwords never leave this class."""
        return self._by_slot[slot]
