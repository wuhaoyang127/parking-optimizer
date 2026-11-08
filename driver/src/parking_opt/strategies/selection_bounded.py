"""Bounded per-request selection set generation."""

from __future__ import annotations

from collections.abc import Callable

from parking_opt.domain.enums import PrimaryDecision
from parking_opt.domain.records import DecisionRequest, PendingRequest
from parking_opt.strategies._selection import BoundedSelectionSet
from parking_opt.strategies.selection_arrival import _bounded_arrival_candidates
from parking_opt.strategies.selection_choose import (
    _arrival_non_action_selection,
    _arrival_selection_from_candidate,
    _departure_selection,
)


def bounded_selections_for_target(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> BoundedSelectionSet:
    if target.request_type == "ARRIVAL":
        limit = int(request.approved_config["max_positions_per_arrival"])
        candidates, seen, timed_out = _bounded_arrival_candidates(
            request, target, limit=limit, first_fit=False, deadline=deadline, clock=clock
        )
        selections = tuple(
            _arrival_selection_from_candidate(request, target, candidate) for candidate in candidates
        )
        non_action = _arrival_non_action_selection(request, target)
        if non_action.primary_decision is not PrimaryDecision.REJECT:
            selections = (*selections, non_action)
        elif not selections:
            selections = (non_action,)
        return BoundedSelectionSet(
            selections=selections,
            positions_seen=seen,
            positions_kept=len(candidates),
            timed_out=timed_out,
        )

    selection = _departure_selection(request, target, first_fit=False, deadline=deadline, clock=clock)
    matchings = int(selection.transaction is not None)
    return BoundedSelectionSet(
        selections=(selection,),
        buffer_matchings_seen=matchings,
        buffer_matchings_kept=matchings,
        timed_out=clock() >= deadline,
    )
