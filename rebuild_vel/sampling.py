"""Stratified sampling over (device x month) cells.

The platform's measurement volume is far larger than any training budget
(one pilot device alone lists ~13k measurements/year across 500+ devices), so
training data has to be *sampled*, not swept. Sampling uniformly over devices
and months also keeps seasonal and station-level coverage balanced, which
matters because the train/val/test split is station-level: a station that only
contributes one month gives the split no seasonal diversity to learn from.

Allocation is round-robin across strata rather than proportional to available
volume: a station that measures hourly would otherwise crowd out a station that
measures daily, and station diversity is the scarcer resource here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence


def month_bounds(begin_time: str, end_time: str) -> list[tuple[str, str, str]]:
    """Enumerate calendar months covering [begin_time, end_time].

    Returns ``[(label, begin, end), ...]`` where label is ``YYYY-MM`` and the
    bounds are the full month clipped to the requested window, in the platform's
    ``%Y-%m-%d %H:%M:%S.%f``-style string form.
    """
    begin = _parse(begin_time)
    end = _parse(end_time)
    if end < begin:
        raise ValueError("end_time precedes begin_time")
    months: list[tuple[str, str, str]] = []
    cursor = datetime(begin.year, begin.month, 1)
    while cursor <= end:
        last_day = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        month_start = max(cursor, begin)
        month_end = min(last_day.replace(hour=23, minute=59, second=59, microsecond=999000), end)
        if month_start <= month_end:
            months.append((cursor.strftime("%Y-%m"), _format(month_start), _format(month_end)))
        cursor = last_day + timedelta(days=1)
        cursor = datetime(cursor.year, cursor.month, 1)
    return months


def _parse(value: str) -> datetime:
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised time format: {value!r}")


def _format(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.") + f"{value.microsecond // 1000:03d}"


@dataclass
class Stratum:
    """One (device, month) cell and its sampling cursor."""

    month: str
    begin: str
    end: str
    total: int = -1          # -1 until the first list call reveals pageInfo.total
    taken: int = 0
    exhausted: bool = False
    accepted: int = 0

    @property
    def remaining(self) -> int:
        if self.total < 0:
            return 1
        return max(0, self.total - self.taken)


@dataclass
class DevicePlan:
    """All month strata for one device; export calls must be device-local."""

    station_code: str
    device_code: str
    station_name: str
    strata: list[Stratum]

    @property
    def active(self) -> bool:
        return any(not stratum.exhausted for stratum in self.strata)


def build_plans(
    devices: Sequence[tuple[str, str, str]],
    months: Sequence[tuple[str, str, str]],
) -> list[DevicePlan]:
    """One plan per usable device, crossing it with every month."""
    return [
        DevicePlan(
            station_code=station,
            device_code=device,
            station_name=name,
            strata=[Stratum(month=label, begin=begin, end=end)
                    for label, begin, end in months],
        )
        for station, device, name in devices
    ]


def even_pages(pages_total: int, want: int) -> list[int]:
    """Page numbers spread evenly over ``[1, pages_total]``, endpoints included.

    The list endpoint returns newest-first, so walking pages 1, 2, 3... would
    sample only the tail of each month. Spreading the pages covers the month.
    """
    if pages_total <= 0:
        return []
    want = max(1, min(want, pages_total))
    if want == 1:
        return [1]
    indices = sorted({round(i * (pages_total - 1) / (want - 1)) for i in range(want)})
    return [index + 1 for index in indices]


@dataclass
class SpreadCursor:
    """Hands out evenly spread page numbers for one (device, month) cell.

    The first call returns page 1, which both samples the cell and reveals
    ``pageInfo.total``; ``set_total`` then plans the remaining pages.
    """

    step: int
    want_pages: int = 12
    total: int = -1
    _queue: list[int] = field(default_factory=list)

    def set_total(self, total: int) -> None:
        self.total = total
        pages_total = math.ceil(total / self.step) if total > 0 else 0
        queue = even_pages(pages_total, self.want_pages)
        # page 1 was already consumed to discover the total
        if queue and queue[0] == 1:
            queue.pop(0)
        self._queue = queue

    def next_page(self) -> int | None:
        if self.total < 0:
            return 1
        if not self._queue:
            return None
        return self._queue.pop(0)


