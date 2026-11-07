"""Frozen v1 enumerations from the approved stage B schemas."""

from enum import StrEnum


class RecoverabilityPolicy(StrEnum):
    """Service policy for accepting future relocation exposure."""

    STRICT_RECOVERABLE = "strict_recoverable"
    RISK_ACCEPTING = "risk_accepting"


class ExecutorType(StrEnum):
    """Label describing who would execute a modeled movement."""

    SIMULATION_ONLY = "simulation_only"
    HUMAN_OPERATOR = "human_operator"
    EXTERNAL_SYSTEM = "external_system"
    AUTONOMOUS_VEHICLE = "autonomous_vehicle"


class ReservationStatus(StrEnum):
    """Information-only reservation lifecycle."""

    NONE = "NONE"
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class DepartureInformationSource(StrEnum):
    """Approved provenance labels for expected departure information."""

    UNKNOWN = "unknown"
    RESERVATION = "reservation"
    USER_ESTIMATE = "user_estimate"
    MODEL_PREDICTION = "model_prediction"


class LocationKind(StrEnum):
    """Mutually exclusive vehicle location states."""

    ENTRY_QUEUE = "ENTRY_QUEUE"
    AT_POSITION = "AT_POSITION"
    IN_TRANSIT = "IN_TRANSIT"
    POSITION_UNCERTAIN = "POSITION_UNCERTAIN"
    EXITED = "EXITED"
    REJECTED = "REJECTED"


class ArrivalStatus(StrEnum):
    """Arrival-service lifecycle independent from physical location."""

    PENDING = "PENDING"
    RECOMMENDED = "RECOMMENDED"
    ADMITTED = "ADMITTED"
    ENTRY_COMPLETED = "ENTRY_COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class DepartureStatus(StrEnum):
    """Departure-service lifecycle."""

    NONE = "NONE"
    PENDING = "PENDING"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"


class ManualStatus(StrEnum):
    """Manual-intervention lifecycle that never implies a location change."""

    NONE = "NONE"
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PositionKind(StrEnum):
    """Normal operating position or dedicated relocation buffer."""

    NORMAL = "normal"
    BUFFER = "buffer"


class ActionType(StrEnum):
    """Executable movement actions approved for the core model."""

    ASSIGN = "ASSIGN"
    DIRECT_EXIT = "DIRECT_EXIT"
    RELOCATE_TO_BUFFER = "RELOCATE_TO_BUFFER"
    RESTORE_ORIGINAL = "RESTORE_ORIGINAL"


class ActionStatus(StrEnum):
    """Executable action lifecycle."""

    RECOMMENDED = "RECOMMENDED"
    ACCEPTED = "ACCEPTED"
    WAITING_FOR_RESOURCES = "WAITING_FOR_RESOURCES"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class PositionConfirmation(StrEnum):
    """How an action terminal event confirms the vehicle location."""

    NOT_REQUIRED = "NOT_REQUIRED"
    AT_ORIGIN = "AT_ORIGIN"
    AT_DESTINATION = "AT_DESTINATION"
    AT_OTHER_POSITION = "AT_OTHER_POSITION"
    UNKNOWN = "UNKNOWN"


class TransactionStatus(StrEnum):
    """Passive relocation transaction lifecycle."""

    PROPOSED = "PROPOSED"
    RESERVED = "RESERVED"
    MOVING_BLOCKERS_OUT = "MOVING_BLOCKERS_OUT"
    TARGET_EXITING = "TARGET_EXITING"
    RESTORING_ORIGINALS = "RESTORING_ORIGINALS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED_MANUAL_PENDING = "FAILED_MANUAL_PENDING"
    FAILED_RESOLVED = "FAILED_RESOLVED"


class SolverStatus(StrEnum):
    """Common solver status without hiding fallback usage."""

    NOT_RUN = "NOT_RUN"
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    TIME_LIMIT_FEASIBLE = "TIME_LIMIT_FEASIBLE"
    TIME_LIMIT_NO_FEASIBLE = "TIME_LIMIT_NO_FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    MODEL_INVALID = "MODEL_INVALID"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    ERROR = "ERROR"


class PrimaryDecision(StrEnum):
    """Exactly one primary outcome returned by a dynamic policy."""

    RECOMMEND_ACTIONS = "RECOMMEND_ACTIONS"
    WAIT = "WAIT"
    REJECT = "REJECT"
    REQUEST_MANUAL_INTERVENTION = "REQUEST_MANUAL_INTERVENTION"


class ValidationStatus(StrEnum):
    """Public validation result status."""

    NOT_RUN = "NOT_RUN"
    VALID = "VALID"
    INVALID = "INVALID"
    ERROR = "ERROR"
