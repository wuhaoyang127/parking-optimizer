import { isParkingFacilityState, type FacilitySnapshot } from "../api/facilityClient";
import { RecommendationApiError, type DriverTripSnapshot } from "../api/recommendationClient";

export function facilityForTandemReplay(
  snapshot: DriverTripSnapshot,
  facility: FacilitySnapshot,
): FacilitySnapshot {
  const departure = snapshot.tandem_departure_replay;
  if (departure !== null && departure !== undefined) {
    const state = departure.facility_state;
    if (
      !isParkingFacilityState(state, facility.layout) ||
      state.parking_lot_id !== departure.parking_lot_id ||
      state.layout_version !== departure.layout_version ||
      state.scenario_version !== departure.scenario_version ||
      state.state_version !== departure.state_version ||
      state.demo_profile?.profile_id !== departure.profile_id
    ) {
      throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "纵深协同离场回放与权威设施快照不一致");
    }
    return { layout: facility.layout, state };
  }
  const arrival = snapshot.tandem_arrival_replay;
  if (arrival === null || arrival === undefined) return facility;
  const states = [
    [arrival.before_facility_state, arrival.before_state_version],
    [arrival.after_facility_state, arrival.after_state_version],
  ] as const;
  if (states.some(([state, stateVersion]) =>
    !isParkingFacilityState(state, facility.layout) ||
    state.parking_lot_id !== arrival.parking_lot_id ||
    state.layout_version !== arrival.layout_version ||
    state.scenario_version !== arrival.scenario_version ||
    state.state_version !== stateVersion ||
    state.demo_profile?.profile_id !== arrival.profile_id
  )) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "纵深协同入位回放与权威设施快照不一致");
  }
  return { layout: facility.layout, state: arrival.after_facility_state };
}
