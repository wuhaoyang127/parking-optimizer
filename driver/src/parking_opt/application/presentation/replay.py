"""Deterministic D3 replay navigation with a bounded frame cache."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass

from parking_opt.application.presentation.facade import frame_at
from parking_opt.application.presentation.models import (
    ReplayEventView,
    ReplayFrame,
    ReplayIndex,
    ReplayTimeline,
)


@dataclass(frozen=True, slots=True)
class ReplayCacheInfo:
    """Observable cache counters used by the UI and performance tests."""

    size: int
    max_entries: int
    hits: int
    misses: int
    invalidations: int


class BoundedReplayFrameCache:
    """Small LRU cache that invalidates when the bound replay content changes."""

    def __init__(self, max_entries: int = 128) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._frames: OrderedDict[int, ReplayFrame] = OrderedDict()
        self._signature: str | None = None
        self._hits = 0
        self._misses = 0
        self._invalidations = 0

    @staticmethod
    def _index_signature(index: ReplayIndex) -> str:
        digest = hashlib.sha256()
        digest.update(index.run_id.encode())
        digest.update(b"\0")
        digest.update(index.scenario_id.encode())
        digest.update(b"\0")
        digest.update(str(index.checkpoint_interval).encode())
        for event in index._events:
            digest.update(str(event["sequence_no"]).encode())
            digest.update(b"\0")
            digest.update(str(event["event_id"]).encode())
            digest.update(b"\0")
            digest.update(str(event["event_type"]).encode())
            digest.update(b"\0")
            digest.update(str(event["sim_time_s"]).encode())
            digest.update(b"\n")
        return digest.hexdigest()

    def bind(self, index: ReplayIndex) -> None:
        """Bind to an immutable index and clear stale frames on content changes."""

        signature = self._index_signature(index)
        if self._signature is not None and signature != self._signature:
            self._frames.clear()
            self._invalidations += 1
        self._signature = signature

    def frame(self, index: ReplayIndex, sequence_no: int) -> ReplayFrame:
        """Return one frame, preserving LRU order and the configured bound."""

        self.bind(index)
        cached = self._frames.get(sequence_no)
        if cached is not None:
            self._frames.move_to_end(sequence_no)
            self._hits += 1
            return cached
        result = frame_at(index, sequence_no)
        self._frames[sequence_no] = result
        self._frames.move_to_end(sequence_no)
        while len(self._frames) > self._max_entries:
            self._frames.popitem(last=False)
        self._misses += 1
        return result

    @property
    def info(self) -> ReplayCacheInfo:
        return ReplayCacheInfo(
            size=len(self._frames),
            max_entries=self._max_entries,
            hits=self._hits,
            misses=self._misses,
            invalidations=self._invalidations,
        )


class ReplayNavigator:
    """Navigate one saved timeline by sequence, time, transaction, or event type."""

    def __init__(
        self,
        index: ReplayIndex,
        timeline: ReplayTimeline,
        *,
        cache_entries: int = 128,
    ) -> None:
        if (index.run_id, index.scenario_id) != (timeline.run_id, timeline.scenario_id):
            raise ValueError("replay index and timeline identity differ")
        if index.last_sequence_no != len(timeline.events):
            raise ValueError("replay index and timeline lengths differ")
        self.index = index
        self.timeline = timeline
        self.cache = BoundedReplayFrameCache(cache_entries)
        self._events_by_sequence = {item.sequence_no: item for item in timeline.events}

    def event_at(self, sequence_no: int) -> ReplayEventView | None:
        """Return None for the initial frame and reject out-of-range requests."""

        self._require_bounds(sequence_no)
        return self._events_by_sequence.get(sequence_no)

    def frame(self, sequence_no: int) -> ReplayFrame:
        self._require_bounds(sequence_no)
        return self.cache.frame(self.index, sequence_no)

    def _require_bounds(self, sequence_no: int) -> None:
        if not self.index.first_sequence_no <= sequence_no <= self.index.last_sequence_no:
            raise IndexError("sequence_no is outside the replay timeline")

    def matching_sequences(
        self,
        *,
        event_types: Iterable[str] = (),
        transaction_id: str | None = None,
    ) -> tuple[int, ...]:
        """Return stable event-order matches; an empty filter includes the initial frame."""

        selected_types = frozenset(event_types)
        if selected_types - set(self.timeline.event_types):
            raise ValueError("event type filter contains an unsupported value")
        if transaction_id is not None and transaction_id not in self.timeline.transaction_ids:
            raise ValueError("unknown transaction_id")
        matches = tuple(
            item.sequence_no
            for item in self.timeline.events
            if (not selected_types or item.event_type in selected_types)
            and (transaction_id is None or item.transaction_id == transaction_id)
        )
        if selected_types or transaction_id is not None:
            return matches
        return (0, *matches)

    def step(
        self,
        current_sequence_no: int,
        delta: int,
        *,
        event_types: Iterable[str] = (),
        transaction_id: str | None = None,
    ) -> int:
        """Move discretely among filtered events and clamp at both ends."""

        self._require_bounds(current_sequence_no)
        if delta == 0:
            return current_sequence_no
        matches = self.matching_sequences(
            event_types=event_types,
            transaction_id=transaction_id,
        )
        if not matches:
            return current_sequence_no
        if delta > 0:
            candidates = [value for value in matches if value > current_sequence_no]
            return candidates[min(delta - 1, len(candidates) - 1)] if candidates else matches[-1]
        candidates = [value for value in matches if value < current_sequence_no]
        offset = min(abs(delta), len(candidates))
        return candidates[-offset] if candidates else matches[0]

    def at_or_before_time(self, sim_time_s: int) -> int:
        """Locate the last confirmed event at or before a simulation second."""

        if sim_time_s < 0:
            raise ValueError("sim_time_s must be non-negative")
        result = 0
        for item in self.timeline.events:
            if item.sim_time_s > sim_time_s:
                break
            result = item.sequence_no
        return result

    def transaction_bounds(self, transaction_id: str) -> tuple[int, int]:
        matches = self.matching_sequences(transaction_id=transaction_id)
        if not matches:
            raise ValueError("transaction has no events")
        return matches[0], matches[-1]
