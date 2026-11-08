"""Deterministic discrete-event engine using only standard-library scheduling."""
from __future__ import annotations
import heapq
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.snapshot_projection import project_observed_snapshot
from parking_opt.demand.truth_store import ScheduledTruth, TruthStore
from parking_opt.domain.conversion import action_to_mapping, transaction_to_mapping
from parking_opt.domain.records import Action, DecisionRequest, RelocationTransaction
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import Layout, layout_to_mapping
from parking_opt.layout.state_adapter import initial_state_from_layout
from parking_opt.logging.event_writer import AtomicEventLog, EventSink
from parking_opt.simulation.engine_decision import EngineDecisionMixin
from parking_opt.simulation.engine_transaction import EngineTransactionMixin
from parking_opt.simulation.engine_truth import EngineTruthMixin
from parking_opt.simulation.engine_types import _DecisionTrigger, _ScheduledItem, SimulationResult, approved_config_from_scenario
from parking_opt.strategies.protocol import DecisionPolicy
_BASE_RECORDED_AT = datetime(2026, 7, 28, tzinfo=UTC)
class DeterministicSimulation(
    EngineTruthMixin,
    EngineDecisionMixin,
    EngineTransactionMixin,
):
    """Advance truth, confirmations, resources, policy decisions, and event logs."""
    def __init__(
        self,
        *,
        run_id: str,
        layout: Layout,
        scenario: dict[str, Any],
        policy: DecisionPolicy,
        schema_catalog: SchemaCatalog,
        event_sink: EventSink,
        event_log_path: Path | None = None,
        initial_state: AuthoritativeState | None = None,
        decision_config_overrides: Mapping[str, Any] | None = None,
        algorithm_id: str = "online-rule-v1",
        algorithm_version: str = "1.0.0",
        decision_target_s: float = 1.0,
        decision_deadline_s: float = 3.0,
    ) -> None:
        self.run_id = run_id
        self.layout = layout
        self.scenario = scenario
        self.policy = policy
        self.catalog = schema_catalog
        self.truth_store = TruthStore(scenario)
        self.config = approved_config_from_scenario(scenario)
        if decision_config_overrides is not None:
            unknown = set(decision_config_overrides) - set(self.config)
            if unknown:
                raise ValueError(f"unknown decision config overrides: {sorted(unknown)}")
            self.config.update(decision_config_overrides)
        if not algorithm_id or not algorithm_version:
            raise ValueError("algorithm ID and version must be non-empty")
        if not 0 < decision_target_s <= decision_deadline_s: raise ValueError("decision target must be positive and no greater than deadline")
        self.algorithm_id = algorithm_id
        self.algorithm_version = algorithm_version
        self.decision_target_s = decision_target_s
        self.decision_deadline_s = decision_deadline_s
        self.layout_mapping = layout_to_mapping(layout)
        self.layout_sha256 = canonical_sha256(self.layout_mapping)
        self.config_sha256 = canonical_sha256(self.config)
        initial = initial_state
        if initial is None:
            initial = initial_state_from_layout(
                layout,
                run_id=run_id,
                scenario_id=scenario["scenario_id"],
                active_buffer_position_ids=tuple(self.config["active_buffer_position_ids"]),
                relocation_executor_capacity=int(self.config["relocation_executor_capacity"]),
                arrival_wait_capacity=int(self.config["arrival_wait_capacity"]),
                max_arrival_wait_s=int(self.config["max_arrival_wait_s"]),
            )
        if (initial.run_id != run_id or initial.scenario_id != scenario["scenario_id"] or initial.layout_id != layout.layout_id or initial.sequence_no != 0):
            raise ValueError("initial_state identifiers or sequence do not match the run")
        self.initial_state = initial
        self.event_log = AtomicEventLog(
            initial_state=initial,
            schema_catalog=schema_catalog,
            sink=event_sink,
        )
        self.event_log_path = event_log_path
        self._queue: list[_ScheduledItem] = []
        self._order = 0
        self._decision_counter = 0
        self._decisions: list[dict[str, Any]] = []
        self._waiting_action_ids: set[str] = set()
        self._scheduled_timers: set[tuple[str, str]] = set()
        self._deferred_departures: dict[str, ScheduledTruth] = {}
        for truth in self.truth_store.scheduled_items():
            self._schedule(truth.event_time_s, 20, "truth", truth)
    @property
    def state(self) -> AuthoritativeState:
        return self.event_log.state
    def _schedule(self, time_s: int, priority: int, kind: str, payload: Any) -> None:
        self._order += 1
        heapq.heappush(
            self._queue,
            _ScheduledItem(
                time_s=time_s,
                priority=priority,
                stable_order=self._order,
                kind=kind,
                payload=payload,
            ),
        )
    def _recorded_at(self, sim_time_s: int) -> str:
        return (_BASE_RECORDED_AT + timedelta(seconds=sim_time_s)).isoformat()
    def _emit(
        self,
        *,
        time_s: int,
        event_type: str,
        vehicle_id: str | None,
        action: Action | None = None,
        transaction_id: str | None = None,
        transaction: RelocationTransaction | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sequence = self.state.sequence_no + 1
        event = {
            "schema_version": "1.0.0",
            "event_id": f"{self.run_id}-event-{sequence:06d}",
            "run_id": self.run_id,
            "scenario_id": self.scenario["scenario_id"],
            "sequence_no": sequence,
            "sim_time_s": time_s,
            "recorded_at": self._recorded_at(time_s),
            "event_type": event_type,
            "anonymous_vehicle_id": vehicle_id,
            "action": action_to_mapping(action) if action is not None else None,
            "transaction_id": transaction_id,
            "transaction": transaction_to_mapping(transaction) if transaction is not None else None,
            "payload": payload or {},
        }
        self.event_log.append(event)
        return event
    def _enqueue_decision(self, *, time_s: int, trigger: _DecisionTrigger) -> None:
        self._schedule(time_s, 50, "decision", trigger)
    def _build_request(self, *, time_s: int, trigger: _DecisionTrigger) -> DecisionRequest | None:
        if not self.state.pending_requests:
            return None
        if trigger.event_type == "ARRIVAL_REQUESTED" and not any(
            item.request_id == trigger.request_id for item in self.state.pending_requests
        ):
            return None
        self._decision_counter += 1
        snapshot = project_observed_snapshot(
            self.state,
            snapshot_id=f"{self.run_id}-snapshot-{self._decision_counter:06d}",
            decision_time_s=time_s,
        )
        return DecisionRequest(
            request_id=f"{self.run_id}-decision-request-{self._decision_counter:06d}",
            algorithm_id=self.algorithm_id,
            algorithm_version=self.algorithm_version,
            trigger_event_id=trigger.event_id,
            trigger_event_type=trigger.event_type,
            trigger_request_id=trigger.request_id,
            trigger_anonymous_vehicle_id=trigger.vehicle_id,
            decision_time_s=time_s,
            layout=self.layout_mapping,
            approved_config=self.config,
            observed_snapshot=snapshot,
            config_sha256=self.config_sha256,
            layout_sha256=self.layout_sha256,
            visible_snapshot_sha256=snapshot.snapshot_content_sha256,
            decision_target_s=self.decision_target_s,
            decision_deadline_s=self.decision_deadline_s,
        )
    def run(self) -> SimulationResult:
        """Run every scheduled item through the fixed drain deadline."""
        drain_deadline = int(self.scenario["drain_deadline_s"])
        while self._queue:
            item = heapq.heappop(self._queue)
            if item.time_s > drain_deadline:
                break
            if item.kind == "truth":
                self._handle_truth(item.payload, item.time_s)
            elif item.kind == "decision":
                self._handle_decision(item.payload, item.time_s)
            elif item.kind == "action_complete":
                self._handle_action_complete(item.payload, item.time_s)
            elif item.kind == "timer":
                self._handle_timer(item.payload, item.time_s)
            else:
                raise RuntimeError(f"unknown simulation schedule kind: {item.kind}")
        return SimulationResult(
            initial_state=self.initial_state,
            final_state=self.state,
            events=self.event_log.events,
            decisions=tuple(self._decisions),
            event_log_path=self.event_log_path,
        )
