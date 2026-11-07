import type { components } from "./schema";
import { getDriverSessionId } from "./sessionIdentity";

export type DriverContext = components["schemas"]["DriverRecommendationContext"];
export type DriverJourneySnapshot = components["schemas"]["DriverJourneySnapshot"];
export type JourneyRecommendation = components["schemas"]["JourneyRecommendationResponse"];
export type Journey = components["schemas"]["Journey"];
export type Recommendation = components["schemas"]["Recommendation"];
export type DriverRequest = components["schemas"]["DriverRequest"];
export type DriverTripSnapshot = components["schemas"]["DriverTripSnapshot"];
export type Layout = components["schemas"]["Layout"];
export type ParkingLot = components["schemas"]["ParkingLot"];
export type Route = components["schemas"]["Route"];
export type ReplanDecision = components["schemas"]["ReplanDecision"];
export type JourneyReplanResponse = components["schemas"]["JourneyReplanResponse"];
export type DemoReplanAction = components["schemas"]["DriverDemoReplanRequest"]["action"];
export type ReassignReason = components["schemas"]["JourneyReassignmentRequest"]["reason"];
export type DriverDemoProfile = components["schemas"]["DriverDemoProfile"];
export type DriverDemoProfileAdvanceResponse = components["schemas"]["DriverDemoProfileAdvanceResponse"];
export type DriverTandemArrivalReplay = components["schemas"]["DriverTandemArrivalReplay"];
export type DriverTandemArrivalStep = components["schemas"]["DriverTandemArrivalStep"];
export type DriverTandemDepartureReplay = components["schemas"]["DriverTandemDepartureReplay"];
export type DriverTandemReplayStep = components["schemas"]["DriverTandemReplayStep"];

export class RecommendationApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "RecommendationApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isDriverDemoProfile(value: unknown): value is DriverDemoProfile {
  return (
    isRecord(value) &&
    value.schema_version === "1.0.0" &&
    typeof value.profile_id === "string" && value.profile_id.length > 0 &&
    typeof value.label === "string" && value.label.length > 0 &&
    typeof value.description === "string" && value.description.length > 0 &&
    Number.isInteger(value.ordinal) && Number(value.ordinal) >= 1 &&
    Number.isInteger(value.total) && Number(value.total) >= Number(value.ordinal)
  );
}

async function requestJson(path: string, init: RequestInit = {}): Promise<unknown> {
  let response: Response;
  try {
    const suppliedHeaders = new Headers(init.headers);
    suppliedHeaders.set("Accept", "application/json");
    suppliedHeaders.set("X-Session-ID", getDriverSessionId());
    if (init.body !== undefined) suppliedHeaders.set("Content-Type", "application/json");
    response = await fetch(path, {
      ...init,
      cache: init.cache ?? "no-store",
      headers: suppliedHeaders,
    });
  } catch {
    if (init.signal?.aborted) {
      throw init.signal.reason ?? new DOMException("The request was aborted", "AbortError");
    }
    throw new RecommendationApiError(0, "NETWORK_UNAVAILABLE", "当前无法连接停车服务");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (init.signal?.aborted) {
      throw init.signal.reason ?? new DOMException("The request was aborted", "AbortError");
    }
    throw new RecommendationApiError(
      response.status,
      "INVALID_JSON_RESPONSE",
      "停车服务返回了无法解析的数据",
      response.headers.get("X-Request-ID"),
    );
  }
  if (!response.ok) {
    if (isRecord(payload) && typeof payload.code === "string" && typeof payload.message === "string") {
      throw new RecommendationApiError(
        response.status,
        payload.code,
        payload.message,
        typeof payload.request_id === "string" ? payload.request_id : null,
      );
    }
    throw new RecommendationApiError(response.status, "UNEXPECTED_API_ERROR", "停车服务暂时不可用");
  }
  return payload;
}

function isJourney(value: unknown): value is Journey {
  return (
    isRecord(value) &&
    value.schema_version === "2.0.0" &&
    typeof value.journey_id === "string" &&
    typeof value.session_id === "string" &&
    typeof value.parking_lot_id === "string" &&
    ["idle", "waiting", "soft_held", "session_reserved", "navigating", "occupied", "departed", "cancelled", "expired", "failed"].includes(String(value.state)) &&
    Number.isInteger(value.version) &&
    typeof value.updated_at === "string" && Number.isFinite(Date.parse(value.updated_at)) &&
    (value.expires_at === null || value.expires_at === undefined || typeof value.expires_at === "string" && Number.isFinite(Date.parse(value.expires_at))) &&
    Array.isArray(value.legal_operations) &&
    value.legal_operations.every((item) => typeof item === "string")
  );
}

function isRecommendation(value: unknown): value is Recommendation {
  return (
    isRecord(value) &&
    value.schema_version === "2.0.0" &&
    typeof value.recommendation_id === "string" &&
    typeof value.parking_lot_id === "string" &&
    ["success", "no_feasible_space", "failed"].includes(String(value.solver_status)) &&
    Array.isArray(value.alternative_space_ids) &&
    value.alternative_space_ids.every((item) => typeof item === "string") &&
    value.alternative_space_ids.length <= 1 &&
    Array.isArray(value.explanation_codes) &&
    value.explanation_codes.every((item) => typeof item === "string")
  );
}

function assertJourneyRecommendationConsistency(journey: Journey, recommendation: Recommendation): void {
  const held = journey.state === "soft_held";
  const terminal = ["departed", "cancelled", "expired", "failed"].includes(journey.state);
  if (
    journey.parking_lot_id !== recommendation.parking_lot_id ||
    (held && recommendation.claim_status !== "soft_held") ||
    (held && journey.space_id !== recommendation.recommended_space_id) ||
    (held && journey.expires_at !== recommendation.soft_lock_expires_at) ||
    (held && recommendation.solver_status !== "success") ||
    (held && recommendation.route === null) ||
    (held && recommendation.route?.parking_lot_id !== journey.parking_lot_id) ||
    (journey.state === "waiting" && recommendation.solver_status === "success") ||
    (journey.state === "waiting" && journey.space_id !== null) ||
    (journey.state === "waiting" && journey.expires_at !== null) ||
    (journey.state === "waiting" && recommendation.claim_status !== "not_created_m2") ||
    (!terminal && journey.session_id !== getDriverSessionId())
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "推荐与服务端权威行程不一致");
  }
}

function isDriverRequest(value: unknown): value is DriverRequest {
  return (
    isRecord(value) &&
    value.schema_version === "2.0.0" &&
    typeof value.request_id === "string" &&
    typeof value.session_id === "string" &&
    typeof value.parking_lot_id === "string" &&
    typeof value.entrance_node_id === "string" &&
    typeof value.requires_charging === "boolean" &&
    typeof value.requested_at === "string" && Number.isFinite(Date.parse(value.requested_at)) &&
    (value.expected_departure_at === null || value.expected_departure_at === undefined || typeof value.expected_departure_at === "string" && Number.isFinite(Date.parse(value.expected_departure_at)))
  );
}

function isRoute(value: unknown): value is Route {
  if (!(
    isRecord(value) &&
    value.schema_version === "2.0.0" &&
    typeof value.parking_lot_id === "string" &&
    typeof value.layout_version === "string" &&
    typeof value.cost_version === "string" &&
    typeof value.from_node_id === "string" &&
    typeof value.to_node_id === "string" &&
    Array.isArray(value.node_ids) &&
    value.node_ids.length >= 1 &&
    value.node_ids.every((item) => typeof item === "string") &&
    Array.isArray(value.edge_ids) &&
    value.edge_ids.every((item) => typeof item === "string") &&
    typeof value.distance_m === "number" && Number.isFinite(value.distance_m) && value.distance_m >= 0 &&
    typeof value.dynamic_eta_s === "number" && Number.isFinite(value.dynamic_eta_s) && value.dynamic_eta_s >= 0 &&
    Array.isArray(value.instructions) &&
    value.instructions.every((item) =>
      isRecord(item) &&
      Number.isInteger(item.sequence) &&
      typeof item.edge_id === "string" &&
      typeof item.text === "string" &&
      typeof item.distance_m === "number" && Number.isFinite(item.distance_m) && item.distance_m >= 0 &&
      typeof item.travel_time_s === "number" && Number.isFinite(item.travel_time_s) && item.travel_time_s >= 0
    )
  )) return false;
  const edgeIds = value.edge_ids;
  const instructions = value.instructions as Record<string, unknown>[];
  return (
    edgeIds.length === value.node_ids.length - 1 &&
    instructions.length === edgeIds.length &&
    value.from_node_id === value.node_ids[0] &&
    value.to_node_id === value.node_ids.at(-1) &&
    instructions.every((item, index) =>
      item.sequence === index + 1 && item.edge_id === edgeIds[index]
    )
  );
}

function sameRoute(left: Route, right: Route): boolean {
  return left.parking_lot_id === right.parking_lot_id &&
    left.layout_version === right.layout_version &&
    left.cost_version === right.cost_version &&
    left.from_node_id === right.from_node_id &&
    left.to_node_id === right.to_node_id &&
    left.distance_m === right.distance_m &&
    left.dynamic_eta_s === right.dynamic_eta_s &&
    left.node_ids.join("\u0000") === right.node_ids.join("\u0000") &&
    left.edge_ids.join("\u0000") === right.edge_ids.join("\u0000") &&
    left.instructions.length === right.instructions.length &&
    left.instructions.every((instruction, index) => {
      const candidate = right.instructions[index];
      return instruction.sequence === candidate?.sequence &&
        instruction.edge_id === candidate.edge_id &&
        instruction.text === candidate.text &&
        instruction.distance_m === candidate.distance_m &&
        instruction.travel_time_s === candidate.travel_time_s;
    });
}

function isTandemReplayLocation(value: unknown): boolean {
  return isRecord(value) &&
    ["space", "buffer", "exit"].includes(String(value.kind)) &&
    typeof value.location_id === "string" && value.location_id.length > 0 &&
    typeof value.node_id === "string" && value.node_id.length > 0 &&
    typeof value.floor_id === "string" && value.floor_id.length > 0 &&
    isRecord(value.coordinate) &&
    typeof value.coordinate.x_m === "number" && Number.isFinite(value.coordinate.x_m) &&
    typeof value.coordinate.y_m === "number" && Number.isFinite(value.coordinate.y_m);
}

function isTandemArrivalLocation(value: unknown): boolean {
  return isRecord(value) &&
    ["space", "buffer", "approach"].includes(String(value.kind)) &&
    typeof value.location_id === "string" && value.location_id.length > 0 &&
    typeof value.node_id === "string" && value.node_id.length > 0 &&
    typeof value.floor_id === "string" && value.floor_id.length > 0 &&
    isRecord(value.coordinate) &&
    typeof value.coordinate.x_m === "number" && Number.isFinite(value.coordinate.x_m) &&
    typeof value.coordinate.y_m === "number" && Number.isFinite(value.coordinate.y_m);
}

function isTandemArrivalStep(value: unknown): value is DriverTandemArrivalStep {
  return isRecord(value) &&
    Number.isInteger(value.sequence) && Number(value.sequence) >= 1 &&
    ["relocate_to_buffer", "direct_entry", "restore_original"].includes(String(value.action)) &&
    ["driver", "blocker"].includes(String(value.actor_role)) &&
    typeof value.actor_id === "string" && value.actor_id.length > 0 &&
    typeof value.label === "string" && value.label.length > 0 &&
    isTandemArrivalLocation(value.from_location) &&
    isTandemArrivalLocation(value.to_location) &&
    isRoute(value.route) &&
    typeof value.starts_at_s === "number" && Number.isFinite(value.starts_at_s) && value.starts_at_s >= 0 &&
    typeof value.duration_s === "number" && Number.isFinite(value.duration_s) && value.duration_s > 0 &&
    value.route.from_node_id === (value.from_location as Record<string, unknown>).node_id &&
    value.route.to_node_id === (value.to_location as Record<string, unknown>).node_id;
}

function assertTandemArrivalReplay(value: unknown, source?: Journey): DriverTandemArrivalReplay {
  if (!(
    isRecord(value) &&
    value.schema_version === "1.0.0" &&
    typeof value.replay_id === "string" && value.replay_id.length > 0 &&
    typeof value.created_at === "string" && Number.isFinite(Date.parse(value.created_at)) &&
    typeof value.journey_id === "string" &&
    typeof value.parking_lot_id === "string" &&
    typeof value.layout_version === "string" &&
    typeof value.scenario_version === "string" &&
    typeof value.before_state_version === "string" &&
    typeof value.after_state_version === "string" &&
    typeof value.cost_version === "string" &&
    value.profile_id === "tandem-focus" &&
    typeof value.stack_group_id === "string" &&
    typeof value.target_space_id === "string" &&
    Array.isArray(value.blocker_vehicle_ids) && value.blocker_vehicle_ids.length >= 1 &&
    value.blocker_vehicle_ids.every((item) => typeof item === "string") &&
    Array.isArray(value.buffer_ids) && value.buffer_ids.length === value.blocker_vehicle_ids.length &&
    value.buffer_ids.every((item) => typeof item === "string") &&
    Array.isArray(value.steps) && value.steps.length === value.blocker_vehicle_ids.length * 2 + 1 &&
    value.steps.every(isTandemArrivalStep) &&
    typeof value.total_duration_s === "number" && Number.isFinite(value.total_duration_s) && value.total_duration_s > 0 &&
    typeof value.before_sha256 === "string" && /^[0-9a-f]{64}$/.test(value.before_sha256) &&
    typeof value.after_sha256 === "string" && /^[0-9a-f]{64}$/.test(value.after_sha256) &&
    isRecord(value.before_facility_state) &&
    isRecord(value.after_facility_state) &&
    isJourney(value.final_journey)
  )) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "纵深协同入位回放与接口契约不一致");
  }
  const beforeState = value.before_facility_state;
  const afterState = value.after_facility_state;
  const statesValid = [
    [beforeState, value.before_state_version],
    [afterState, value.after_state_version],
  ].every(([state, stateVersion]) => isRecord(state) &&
    state.parking_lot_id === value.parking_lot_id &&
    state.layout_version === value.layout_version &&
    state.scenario_version === value.scenario_version &&
    state.state_version === stateVersion &&
    isRecord(state.demo_profile) && state.demo_profile.profile_id === value.profile_id);
  const steps = value.steps;
  let elapsed = 0;
  const directIndex = steps.findIndex((item) => item.action === "direct_entry");
  const identitiesValid = steps.every((item, index) => {
    const matches = item.sequence === index + 1 && Math.abs(item.starts_at_s - elapsed) <= 1e-6 &&
      item.route.parking_lot_id === value.parking_lot_id &&
      item.route.layout_version === value.layout_version &&
      item.route.cost_version === value.cost_version;
    elapsed += item.duration_s;
    return matches;
  });
  const finalJourney = value.final_journey;
  if (
    !statesValid || directIndex !== value.blocker_vehicle_ids.length ||
    steps.slice(0, directIndex).some((item) => item.action !== "relocate_to_buffer" || item.actor_role !== "blocker") ||
    steps[directIndex]?.actor_role !== "driver" ||
    steps.slice(directIndex + 1).some((item) => item.action !== "restore_original" || item.actor_role !== "blocker") ||
    !identitiesValid || Math.abs(elapsed - value.total_duration_s) > 1e-6 ||
    finalJourney.journey_id !== value.journey_id ||
    finalJourney.parking_lot_id !== value.parking_lot_id || finalJourney.state !== "occupied" ||
    finalJourney.space_id !== value.target_space_id ||
    (source !== undefined && (
      value.journey_id !== source.journey_id || value.parking_lot_id !== source.parking_lot_id ||
      finalJourney.version <= source.version
    ))
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "纵深协同入位事件顺序或身份不一致");
  }
  return value as unknown as DriverTandemArrivalReplay;
}

function isTandemReplayStep(value: unknown): value is DriverTandemReplayStep {
  return isRecord(value) &&
    Number.isInteger(value.sequence) && Number(value.sequence) >= 1 &&
    ["relocate_to_buffer", "direct_exit", "restore_original"].includes(String(value.action)) &&
    ["driver", "blocker"].includes(String(value.actor_role)) &&
    typeof value.actor_id === "string" && value.actor_id.length > 0 &&
    typeof value.label === "string" && value.label.length > 0 &&
    isTandemReplayLocation(value.from_location) &&
    isTandemReplayLocation(value.to_location) &&
    isRoute(value.route) &&
    typeof value.starts_at_s === "number" && Number.isFinite(value.starts_at_s) && value.starts_at_s >= 0 &&
    typeof value.duration_s === "number" && Number.isFinite(value.duration_s) && value.duration_s > 0 &&
    value.route.from_node_id === (value.from_location as Record<string, unknown>).node_id &&
    value.route.to_node_id === (value.to_location as Record<string, unknown>).node_id;
}

function assertTandemDepartureReplay(value: unknown, source?: Journey): DriverTandemDepartureReplay {
  if (!(
    isRecord(value) &&
    value.schema_version === "1.0.0" &&
    typeof value.replay_id === "string" && value.replay_id.length > 0 &&
    typeof value.created_at === "string" && Number.isFinite(Date.parse(value.created_at)) &&
    typeof value.journey_id === "string" &&
    typeof value.parking_lot_id === "string" &&
    typeof value.layout_version === "string" &&
    typeof value.scenario_version === "string" &&
    typeof value.state_version === "string" &&
    typeof value.cost_version === "string" &&
    value.profile_id === "tandem-focus" &&
    typeof value.stack_group_id === "string" &&
    typeof value.target_space_id === "string" &&
    Array.isArray(value.blocker_vehicle_ids) && value.blocker_vehicle_ids.length >= 1 &&
    value.blocker_vehicle_ids.every((item) => typeof item === "string") &&
    Array.isArray(value.buffer_ids) && value.buffer_ids.length === value.blocker_vehicle_ids.length &&
    value.buffer_ids.every((item) => typeof item === "string") &&
    Array.isArray(value.steps) && value.steps.length === value.blocker_vehicle_ids.length * 2 + 1 &&
    value.steps.every(isTandemReplayStep) &&
    typeof value.total_duration_s === "number" && Number.isFinite(value.total_duration_s) && value.total_duration_s > 0 &&
    typeof value.before_sha256 === "string" && /^[0-9a-f]{64}$/.test(value.before_sha256) &&
    typeof value.after_sha256 === "string" && /^[0-9a-f]{64}$/.test(value.after_sha256) &&
    isRecord(value.facility_state) &&
    value.facility_state.parking_lot_id === value.parking_lot_id &&
    value.facility_state.layout_version === value.layout_version &&
    value.facility_state.scenario_version === value.scenario_version &&
    value.facility_state.state_version === value.state_version &&
    isRecord(value.facility_state.demo_profile) &&
    value.facility_state.demo_profile.profile_id === value.profile_id &&
    isJourney(value.final_journey)
  )) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "纵深协同离场回放与接口契约不一致");
  }
  const steps = value.steps;
  let elapsed = 0;
  const directIndex = steps.findIndex((item) => item.action === "direct_exit");
  const identitiesValid = steps.every((item, index) => {
    const startsAt = item.starts_at_s;
    const matches = item.sequence === index + 1 && Math.abs(startsAt - elapsed) <= 1e-6 &&
      item.route.parking_lot_id === value.parking_lot_id &&
      item.route.layout_version === value.layout_version &&
      item.route.cost_version === value.cost_version;
    elapsed += item.duration_s;
    return matches;
  });
  const finalJourney = value.final_journey;
  if (
    directIndex !== value.blocker_vehicle_ids.length ||
    steps.slice(0, directIndex).some((item) => item.action !== "relocate_to_buffer" || item.actor_role !== "blocker") ||
    steps[directIndex]?.actor_role !== "driver" ||
    steps.slice(directIndex + 1).some((item) => item.action !== "restore_original" || item.actor_role !== "blocker") ||
    !identitiesValid || Math.abs(elapsed - value.total_duration_s) > 1e-6 ||
    finalJourney.journey_id !== value.journey_id ||
    finalJourney.parking_lot_id !== value.parking_lot_id || finalJourney.state !== "departed" ||
    (source !== undefined && (
      value.journey_id !== source.journey_id || value.parking_lot_id !== source.parking_lot_id ||
      finalJourney.version <= source.version
    ))
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "纵深协同离场事件顺序或身份不一致");
  }
  return value as unknown as DriverTandemDepartureReplay;
}

function isCostSnapshot(value: unknown): boolean {
  return isRecord(value) && value.schema_version === "2.0.0" &&
    typeof value.parking_lot_id === "string" && value.parking_lot_id.length > 0 &&
    typeof value.layout_version === "string" && value.layout_version.length > 0 &&
    typeof value.cost_version === "string" && value.cost_version.length > 0 &&
    typeof value.observed_at === "string" && Number.isFinite(Date.parse(value.observed_at)) &&
    isRecord(value.edge_travel_time_s) && Object.values(value.edge_travel_time_s).every((time) =>
      typeof time === "number" && Number.isFinite(time) && time >= 0
    ) &&
    Array.isArray(value.unavailable_edge_ids) && value.unavailable_edge_ids.every((edgeId) => typeof edgeId === "string");
}

function isReplanDecision(value: unknown): value is ReplanDecision {
  return isRecord(value) &&
    value.schema_version === "2.0.0" &&
    ["success", "warning", "failed"].includes(String(value.status)) &&
    ["deviation", "cost_update", "manual_refresh"].includes(String(value.trigger)) &&
    isRoute(value.previous_route) &&
    (value.route === null || value.route === undefined || isRoute(value.route)) &&
    Array.isArray(value.reason_codes) && value.reason_codes.every((code) => typeof code === "string") &&
    typeof value.remaining_reservation_s === "number" && Number.isFinite(value.remaining_reservation_s) && value.remaining_reservation_s >= 0 &&
    isCostSnapshot(value.cost_snapshot) &&
    (value.eta_with_safety_margin_s === null || value.eta_with_safety_margin_s === undefined ||
      typeof value.eta_with_safety_margin_s === "number" && Number.isFinite(value.eta_with_safety_margin_s) && value.eta_with_safety_margin_s >= 0) &&
    (value.status === "failed" ? value.route === null || value.route === undefined : isRoute(value.route));
}

function assertLayout(value: unknown): Layout {
  if (
    !isRecord(value) ||
    value.schema_version !== "2.0.0" ||
    typeof value.parking_lot_id !== "string" ||
    typeof value.layout_version !== "string" ||
    value.coordinate_system !== "local_meters" ||
    !Array.isArray(value.nodes) ||
    !Array.isArray(value.edges) ||
    !Array.isArray(value.spaces) ||
    value.nodes.length === 0 ||
    !value.nodes.every((node) =>
      isRecord(node) &&
      typeof node.node_id === "string" &&
      typeof node.label === "string" &&
      isRecord(node.coordinate) &&
      typeof node.coordinate.x_m === "number" && Number.isFinite(node.coordinate.x_m) &&
      typeof node.coordinate.y_m === "number" && Number.isFinite(node.coordinate.y_m)
    ) ||
    !value.edges.every((edge) =>
      isRecord(edge) &&
      typeof edge.edge_id === "string" &&
      typeof edge.from_node_id === "string" &&
      typeof edge.to_node_id === "string" &&
      typeof edge.directed === "boolean" &&
      typeof edge.distance_m === "number" && Number.isFinite(edge.distance_m) && edge.distance_m >= 0
    ) ||
    !value.spaces.every((space) =>
      isRecord(space) &&
      typeof space.space_id === "string" &&
      typeof space.parking_lot_id === "string" &&
      typeof space.access_node_id === "string" &&
      ["available", "occupied", "unavailable", "unknown"].includes(String(space.status))
    )
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "停车场布局与接口契约不一致");
  }
  return value as unknown as Layout;
}

function assertParkingLot(value: unknown): ParkingLot {
  if (
    !isRecord(value) ||
    value.schema_version !== "2.0.0" ||
    typeof value.parking_lot_id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.region_label !== "string" ||
    typeof value.synthetic !== "boolean" ||
    !isRecord(value.data_source) ||
    !["healthy", "degraded", "unavailable"].includes(String(value.data_source.health))
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "停车场摘要与接口契约不一致");
  }
  return value as unknown as ParkingLot;
}

function assertDriverTripSnapshot(value: unknown): DriverTripSnapshot {
  if (
    !isRecord(value) ||
    value.schema_version !== "1.0.0" ||
    typeof value.observed_at !== "string" ||
    !Number.isFinite(Date.parse(value.observed_at)) ||
    !Array.isArray(value.recent_events) ||
    !Array.isArray(value.recent_trips) ||
    typeof value.tandem_arrival_replay_enabled !== "boolean" ||
    typeof value.tandem_departure_replay_enabled !== "boolean" ||
    !value.recent_events.every((event) =>
      isRecord(event) &&
      Number.isInteger(event.sequence_no) &&
      typeof event.event_type === "string" &&
      typeof event.occurred_at === "string" && Number.isFinite(Date.parse(event.occurred_at))
    ) ||
    !value.recent_trips.every((trip) =>
      isRecord(trip) &&
      typeof trip.journey_id === "string" &&
      typeof trip.parking_lot_id === "string" &&
      ["occupied", "departed", "cancelled", "expired", "failed"].includes(String(trip.state))
    )
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前行程快照与接口契约不一致");
  }
  if (value.journey === null || value.journey === undefined) {
    if (
      value.driver !== null && value.driver !== undefined ||
      value.current_route !== null && value.current_route !== undefined ||
      value.current_node_id !== null && value.current_node_id !== undefined ||
      value.last_replan !== null && value.last_replan !== undefined ||
      value.started_at !== null && value.started_at !== undefined ||
      value.parked_at !== null && value.parked_at !== undefined ||
      value.ended_at !== null && value.ended_at !== undefined ||
      value.tandem_arrival_replay !== null && value.tandem_arrival_replay !== undefined ||
      value.tandem_departure_replay !== null && value.tandem_departure_replay !== undefined ||
      value.recent_events.length > 0 ||
      value.recent_trips.length > 0
    ) {
      throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "空行程快照包含了不应存在的路线");
    }
    return value as unknown as DriverTripSnapshot;
  }
  if (!isJourney(value.journey) || !isDriverRequest(value.driver)) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前行程快照内容不完整");
  }
  const route = value.current_route;
  const routeVisible = ["session_reserved", "navigating"].includes(value.journey.state);
  const lastReplan = value.last_replan;
  const lastReplanValid = lastReplan === null || lastReplan === undefined || (
    isReplanDecision(lastReplan) &&
    isRoute(route) &&
    (lastReplan.status === "failed" ? sameRoute(lastReplan.previous_route, route) :
      isRoute(lastReplan.route) && sameRoute(lastReplan.route, route)) &&
    lastReplan.previous_route.parking_lot_id === value.journey.parking_lot_id &&
    lastReplan.cost_snapshot.parking_lot_id === value.journey.parking_lot_id &&
    lastReplan.cost_snapshot.layout_version === lastReplan.previous_route.layout_version &&
    (lastReplan.route === null || lastReplan.route === undefined ||
      lastReplan.route.cost_version === lastReplan.cost_snapshot.cost_version &&
      lastReplan.route.layout_version === lastReplan.cost_snapshot.layout_version)
  );
  const lifecycleTimesValid = [value.started_at, value.parked_at, value.ended_at].every((timestamp) =>
    timestamp === null || timestamp === undefined || typeof timestamp === "string" && Number.isFinite(Date.parse(timestamp))
  );
  const failedOffRoute = isRoute(route) && isRecord(lastReplan) &&
    lastReplan.status === "failed" && isRoute(lastReplan.previous_route) &&
    sameRoute(route, lastReplan.previous_route);
  const tandemReplay = value.tandem_departure_replay;
  const tandemReplayValid = tandemReplay === null || tandemReplay === undefined || (
    value.journey.state === "departed" &&
    assertTandemDepartureReplay(tandemReplay).journey_id === value.journey.journey_id
  );
  const tandemArrivalReplay = value.tandem_arrival_replay;
  const tandemArrivalReplayValid = tandemArrivalReplay === null || tandemArrivalReplay === undefined || (
    ["occupied", "departed"].includes(value.journey.state) &&
    assertTandemArrivalReplay(tandemArrivalReplay).journey_id === value.journey.journey_id
  );
  if (
    value.journey.namespace !== "driver" ||
    value.journey.session_id !== getDriverSessionId() ||
    value.driver.session_id !== value.journey.session_id ||
    value.driver.parking_lot_id !== value.journey.parking_lot_id ||
    (routeVisible && !isRoute(route)) ||
    (!routeVisible && route !== null && route !== undefined) ||
    (isRoute(route) && (typeof value.current_node_id !== "string" || value.current_node_id.length === 0)) ||
    (isRoute(route) && route.parking_lot_id !== value.journey.parking_lot_id) ||
    (isRoute(route) && value.current_node_id !== null && value.current_node_id !== undefined &&
      (typeof value.current_node_id !== "string" || !route.node_ids.includes(value.current_node_id) && !failedOffRoute)) ||
    !lastReplanValid || !lifecycleTimesValid || !tandemArrivalReplayValid || !tandemReplayValid ||
    (lastReplan !== null && lastReplan !== undefined && !isRoute(route))
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前行程、会话与路线不一致");
  }
  return value as unknown as DriverTripSnapshot;
}

function assertContext(value: unknown): DriverContext {
  if (
    !isRecord(value) ||
    value.schema_version !== "1.0.0" ||
    typeof value.scenario_id !== "string" ||
    typeof value.parking_lot_id !== "string" ||
    !Array.isArray(value.entrances) ||
    value.entrances.length === 0 ||
    !Array.isArray(value.spaces) ||
    !Array.isArray(value.tandem_groups) ||
    (value.demo_profile !== null && value.demo_profile !== undefined && !isDriverDemoProfile(value.demo_profile))
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "推荐上下文与接口契约不一致");
  }
  return value as unknown as DriverContext;
}

function assertRecommendation(value: unknown): JourneyRecommendation {
  if (!isRecord(value) || !isJourney(value.journey) || !isRecommendation(value.recommendation)) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "推荐结果与接口契约不一致");
  }
  assertJourneyRecommendationConsistency(value.journey, value.recommendation);
  if (value.journey.session_id !== getDriverSessionId()) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "推荐不属于本浏览器会话");
  }
  return value as unknown as JourneyRecommendation;
}

export async function loadDriverContext(parkingLotId: string): Promise<DriverContext> {
  return assertContext(await requestJson(`/api/v2/parking-lots/${encodeURIComponent(parkingLotId)}/driver-context`));
}

export async function advanceDriverDemoProfile(
  parkingLotId: string,
  profile: DriverDemoProfile,
  stateVersion: string,
): Promise<DriverDemoProfileAdvanceResponse> {
  const value = await requestJson(
    `/api/v2/parking-lots/${encodeURIComponent(parkingLotId)}/driver-demo-profile/advance`,
    {
      method: "POST",
      body: JSON.stringify({
        schema_version: "1.0.0",
        expected_profile_id: profile.profile_id,
        expected_state_version: stateVersion,
        idempotency_key: commandId("demo-profile"),
      }),
    },
  );
  if (
    !isRecord(value) ||
    value.schema_version !== "1.0.0" ||
    !isDriverDemoProfile(value.demo_profile) ||
    !isRecord(value.facility_state) ||
    !isRecord(value.parking_lot) ||
    value.facility_state.parking_lot_id !== parkingLotId ||
    value.parking_lot.parking_lot_id !== parkingLotId ||
    !isRecord(value.facility_state.demo_profile) ||
    value.facility_state.demo_profile.profile_id !== value.demo_profile.profile_id
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "模拟状态切换结果与接口契约不一致");
  }
  return value as unknown as DriverDemoProfileAdvanceResponse;
}

export async function loadCurrentDriverJourney(): Promise<DriverJourneySnapshot> {
  const value = await requestJson("/api/v2/driver-session/current-journey");
  if (!isRecord(value) || value.schema_version !== "1.0.0" || typeof value.observed_at !== "string" || !Number.isFinite(Date.parse(value.observed_at))) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前行程与接口契约不一致");
  }
  if (value.journey === null && value.recommendation === null && value.driver === null) {
    return value as unknown as DriverJourneySnapshot;
  }
  if (!isJourney(value.journey) || !isRecommendation(value.recommendation) || !isDriverRequest(value.driver)) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前行程内容不完整");
  }
  assertJourneyRecommendationConsistency(value.journey, value.recommendation);
  if (
    value.driver.session_id !== value.journey.session_id ||
    value.driver.parking_lot_id !== value.journey.parking_lot_id ||
    value.driver.session_id !== getDriverSessionId()
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前行程不属于本浏览器会话");
  }
  return value as unknown as DriverJourneySnapshot;
}

export async function loadCurrentDriverTrip(signal?: AbortSignal): Promise<DriverTripSnapshot> {
  return assertDriverTripSnapshot(await requestJson(
    "/api/v2/driver-session/current-trip",
    signal === undefined ? {} : { signal },
  ));
}

export async function loadJourneyLayout(parkingLotId: string): Promise<Layout> {
  return assertLayout(await requestJson(`/api/v2/parking-lots/${encodeURIComponent(parkingLotId)}/layout`));
}

export async function loadJourneyParkingLot(parkingLotId: string, signal?: AbortSignal): Promise<ParkingLot> {
  return assertParkingLot(await requestJson(
    `/api/v2/parking-lots/${encodeURIComponent(parkingLotId)}`,
    signal === undefined ? {} : { signal },
  ));
}

function commandId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export async function createRecommendation(
  context: DriverContext,
  entranceNodeId: string,
  requiresCharging: boolean,
  expectedStayMinutes: number | null = null,
): Promise<JourneyRecommendation> {
  if (expectedStayMinutes !== null && (!Number.isFinite(expectedStayMinutes) || expectedStayMinutes < 5 || expectedStayMinutes > 1440)) {
    throw new RecommendationApiError(422, "INVALID_STAY_ESTIMATE", "预计停留需在5分钟到24小时之间");
  }
  const now = new Date().toISOString();
  const requestId = commandId("request");
  const body = {
    schema_version: "2.0.0",
    namespace: "driver",
    scenario_id: context.scenario_id,
    journey_id: commandId("journey"),
    attempt_id: commandId("attempt"),
    algorithm_id: "online-rule-v2",
    idempotency_key: commandId("recommend"),
    driver: {
      schema_version: "2.0.0",
      request_id: requestId,
      idempotency_key: commandId("driver"),
      session_id: getDriverSessionId(),
      parking_lot_id: context.parking_lot_id,
      entrance_node_id: entranceNodeId,
      requires_charging: requiresCharging,
      requested_at: now,
      expected_departure_at: expectedStayMinutes === null ? null : new Date(Date.parse(now) + expectedStayMinutes * 60_000).toISOString(),
    },
  };
  return assertRecommendation(
    await requestJson("/api/v2/journeys/recommendations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
}

async function postRecommendationCommand(path: string, body: object): Promise<JourneyRecommendation> {
  return assertRecommendation(await requestJson(path, { method: "POST", body: JSON.stringify(body) }));
}

export function retryWaiting(result: JourneyRecommendation): Promise<JourneyRecommendation> {
  return postRecommendationCommand(
    `/api/v2/journeys/${encodeURIComponent(result.journey.journey_id)}/retry-recommendation`,
    { schema_version: "2.0.0", expected_version: result.journey.version, idempotency_key: commandId("retry") },
  );
}

export function selectAlternative(result: JourneyRecommendation, spaceId: string): Promise<JourneyRecommendation> {
  return postRecommendationCommand(
    `/api/v2/journeys/${encodeURIComponent(result.journey.journey_id)}/select-alternative`,
    {
      schema_version: "2.0.0",
      expected_version: result.journey.version,
      idempotency_key: commandId("alternative"),
      space_id: spaceId,
    },
  );
}

export async function confirmRecommendation(result: JourneyRecommendation): Promise<Journey> {
  const value = await requestJson(`/api/v2/journeys/${encodeURIComponent(result.journey.journey_id)}/confirm`, {
    method: "POST",
    body: JSON.stringify({
      schema_version: "2.0.0",
      expected_version: result.journey.version,
      idempotency_key: commandId("confirm"),
      accepted: true,
    }),
  });
  if (!isJourney(value)) throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "确认结果不完整");
  return value;
}

export async function startNavigation(journey: Journey): Promise<Journey> {
  const value = await requestJson(`/api/v2/journeys/${encodeURIComponent(journey.journey_id)}/start-navigation`, {
    method: "POST",
    body: JSON.stringify({
      schema_version: "2.0.0",
      expected_version: journey.version,
      idempotency_key: commandId("navigate"),
    }),
  });
  if (
    !isJourney(value) ||
    value.state !== "navigating" ||
    value.journey_id !== journey.journey_id ||
    value.session_id !== journey.session_id ||
    value.parking_lot_id !== journey.parking_lot_id
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "开始指引后的行程状态不完整");
  }
  return value;
}

function assertJourneyCommandResult(value: unknown, source: Journey, state: Journey["state"]): Journey {
  if (!isJourney(value) || value.journey_id !== source.journey_id ||
    value.session_id !== source.session_id || value.parking_lot_id !== source.parking_lot_id ||
    value.state !== state || value.version <= source.version) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "行程操作结果与当前状态不一致");
  }
  return value;
}

async function postJourneyCommand(journey: Journey, operation: string, prefix: string): Promise<unknown> {
  return requestJson(`/api/v2/journeys/${encodeURIComponent(journey.journey_id)}/${operation}`, {
    method: "POST",
    body: JSON.stringify({
      schema_version: "2.0.0",
      expected_version: journey.version,
      idempotency_key: commandId(prefix),
    }),
  });
}

export async function driverDemoReplan(journey: Journey, action: DemoReplanAction): Promise<JourneyReplanResponse> {
  const value = await requestJson(`/api/v2/journeys/${encodeURIComponent(journey.journey_id)}/driver-demo-replan`, {
    method: "POST",
    body: JSON.stringify({ schema_version: "2.0.0", expected_version: journey.version, idempotency_key: commandId("demo-replan"), action }),
  });
  if (!isRecord(value) || value.schema_version !== "2.0.0" || !isJourney(value.journey) || !isReplanDecision(value.decision) ||
    value.journey.journey_id !== journey.journey_id || value.journey.session_id !== journey.session_id ||
    value.journey.parking_lot_id !== journey.parking_lot_id || value.journey.version <= journey.version ||
    !["navigating", "expired"].includes(value.journey.state) ||
    value.decision.trigger !== (action === "simulate_deviation" ? "deviation" : "cost_update") ||
    value.decision.cost_snapshot.parking_lot_id !== journey.parking_lot_id ||
    value.decision.cost_snapshot.layout_version !== value.decision.previous_route.layout_version ||
    (value.decision.route !== null && value.decision.route !== undefined &&
      (value.decision.route.cost_version !== value.decision.cost_snapshot.cost_version ||
        value.decision.route.layout_version !== value.decision.cost_snapshot.layout_version)) ||
    value.decision.previous_route.parking_lot_id !== journey.parking_lot_id ||
    (value.decision.route !== null && value.decision.route !== undefined && value.decision.route.parking_lot_id !== journey.parking_lot_id)) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "路线更新结果与当前行程不一致");
  }
  return value as unknown as JourneyReplanResponse;
}

export async function occupyJourney(journey: Journey): Promise<Journey> {
  return assertJourneyCommandResult(await postJourneyCommand(journey, "occupy", "occupy"), journey, "occupied");
}

export async function departJourney(journey: Journey): Promise<Journey> {
  const result = assertJourneyCommandResult(await postJourneyCommand(journey, "depart", "depart"), journey, "departed");
  if (result.terminal_reason !== "NORMAL_DEPARTURE") throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "正常离场原因不一致");
  return result;
}

export async function occupyTandemWithReplay(
  journey: Journey,
  stateVersion: string,
): Promise<DriverTandemArrivalReplay> {
  const value = await requestJson(
    `/api/v2/journeys/${encodeURIComponent(journey.journey_id)}/tandem-arrival-replay`,
    {
      method: "POST",
      body: JSON.stringify({
        schema_version: "1.0.0",
        expected_version: journey.version,
        expected_state_version: stateVersion,
        idempotency_key: commandId("tandem-arrival"),
      }),
    },
  );
  return assertTandemArrivalReplay(value, journey);
}

export async function departTandemWithReplay(
  journey: Journey,
  stateVersion: string,
): Promise<DriverTandemDepartureReplay> {
  const value = await requestJson(
    `/api/v2/journeys/${encodeURIComponent(journey.journey_id)}/tandem-departure-replay`,
    {
      method: "POST",
      body: JSON.stringify({
        schema_version: "1.0.0",
        expected_version: journey.version,
        expected_state_version: stateVersion,
        idempotency_key: commandId("tandem-depart"),
      }),
    },
  );
  return assertTandemDepartureReplay(value, journey);
}

export async function resetDemoJourney(journey: Journey): Promise<Journey> {
  const result = assertJourneyCommandResult(await postJourneyCommand(journey, "reset-demo", "reset"), journey, "departed");
  if (result.terminal_reason !== "DEMO_RESET") throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "演示重置原因不一致");
  return result;
}

async function replacementCommand(journey: Journey, operation: "report-external-occupancy" | "reassign", reason?: ReassignReason): Promise<JourneyRecommendation> {
  const value = await requestJson(`/api/v2/journeys/${encodeURIComponent(journey.journey_id)}/${operation}`, {
    method: "POST",
    body: JSON.stringify({
      schema_version: "2.0.0",
      expected_version: journey.version,
      idempotency_key: commandId(operation === "reassign" ? "reassign" : "external"),
      replacement_journey_id: commandId("journey"),
      replacement_attempt_id: commandId("attempt"),
      replacement_request_id: commandId("request"),
      ...(reason === undefined ? {} : { reason }),
    }),
  });
  const expectedSchemaVersion = operation === "reassign" ? "1.0.0" : "2.0.0";
  if (!isRecord(value) || value.schema_version !== expectedSchemaVersion) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "重新推荐结果不完整");
  }
  const ended = operation === "reassign" ? value.ended_journey : value.failed_journey;
  const expectedReason = operation === "report-external-occupancy" ? "EXTERNAL_SPACE_OCCUPIED" :
    reason === "unable_to_park" ? "USER_UNABLE_TO_PARK" : "ETA_EXCEEDS_RESERVATION";
  if (!isJourney(ended) || ended.journey_id !== journey.journey_id || ended.state !== "failed" ||
    ended.session_id !== journey.session_id || ended.parking_lot_id !== journey.parking_lot_id ||
    ended.terminal_reason !== expectedReason) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "原行程终止结果不一致");
  }
  const replacement = assertRecommendation(value.replacement);
  if (replacement.journey.session_id !== journey.session_id || replacement.journey.parking_lot_id !== journey.parking_lot_id) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "新推荐不属于当前行程上下文");
  }
  return replacement;
}

export function reportExternalOccupancy(journey: Journey): Promise<JourneyRecommendation> {
  return replacementCommand(journey, "report-external-occupancy");
}

export function reassignJourney(journey: Journey, reason: ReassignReason): Promise<JourneyRecommendation> {
  return replacementCommand(journey, "reassign", reason);
}

export async function cancelJourney(journey: Journey): Promise<Journey> {
  const value = await requestJson(`/api/v2/journeys/${encodeURIComponent(journey.journey_id)}/cancel`, {
    method: "POST",
    body: JSON.stringify({
      schema_version: "2.0.0",
      expected_version: journey.version,
      idempotency_key: commandId("cancel"),
    }),
  });
  if (!isJourney(value)) throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "取消结果不完整");
  return value;
}

export async function declineTandem(result: JourneyRecommendation): Promise<JourneyRecommendation> {
  const value = await requestJson(
    `/api/v2/journeys/${encodeURIComponent(result.journey.journey_id)}/decline-tandem`,
    {
      method: "POST",
      body: JSON.stringify({
        schema_version: "2.0.0",
        expected_version: result.journey.version,
        idempotency_key: commandId("decline"),
        replacement_journey_id: commandId("journey"),
        replacement_attempt_id: commandId("attempt"),
        replacement_request_id: commandId("request"),
      }),
    },
  );
  if (!isRecord(value)) throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "重推荐结果不完整");
  if (value.schema_version !== "1.0.0" || !isJourney(value.declined_journey)) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "被拒绝的原行程状态不完整");
  }
  const replacement = assertRecommendation(value.replacement);
  if (
    value.declined_journey.journey_id !== result.journey.journey_id ||
    value.declined_journey.state !== "cancelled" ||
    value.declined_journey.terminal_reason !== "USER_REJECTED" ||
    value.declined_journey.session_id !== replacement.journey.session_id ||
    value.declined_journey.parking_lot_id !== replacement.journey.parking_lot_id
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "纵深拒绝与新推荐不属于同一行程上下文");
  }
  return replacement;
}
