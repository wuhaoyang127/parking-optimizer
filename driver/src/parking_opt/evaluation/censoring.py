"""Request-observation helpers for explicit right censoring."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestObservation:
    """One completed or right-censored request duration."""

    value_s: int
    event_observed: bool
    pending_at_horizon: bool
    observed_wait_lower_bound_s: int | None


def observe_duration(
    *,
    request_time_s: int,
    terminal_time_s: int | None,
    drain_deadline_s: int,
) -> RequestObservation:
    """Return an observed duration or a lower bound at the frozen horizon."""

    if terminal_time_s is not None and terminal_time_s <= drain_deadline_s:
        return RequestObservation(
            value_s=max(0, terminal_time_s - request_time_s),
            event_observed=True,
            pending_at_horizon=False,
            observed_wait_lower_bound_s=None,
        )
    lower_bound = max(0, drain_deadline_s - request_time_s)
    return RequestObservation(
        value_s=lower_bound,
        event_observed=False,
        pending_at_horizon=True,
        observed_wait_lower_bound_s=lower_bound,
    )
