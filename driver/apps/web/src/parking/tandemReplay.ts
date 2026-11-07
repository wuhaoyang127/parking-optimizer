import type {
  DriverTandemArrivalReplay,
  DriverTandemArrivalStep,
  DriverTandemDepartureReplay,
  DriverTandemReplayStep,
} from "../api/recommendationClient";
import type { FacilityRoute, ParkingFacilityLayout } from "../api/facilityClient";
import type { FacilityActor } from "./facility/FacilityCanvas";
import { routeVehiclePosition } from "./facility/routeGeometry";
import { routeTimeline } from "./routeTimeline";

type ActorPosition = FacilityActor;
export type TandemReplay = DriverTandemArrivalReplay | DriverTandemDepartureReplay;
type TandemReplayStep = DriverTandemArrivalStep | DriverTandemReplayStep;

export interface TandemReplayFrame {
  actors: FacilityActor[];
  route: FacilityRoute;
  activeStep: number;
  completedSteps: number;
  complete: boolean;
  progress: number;
  hiddenOccupiedSpaceIds: string[];
}

function atLocation(step: TandemReplayStep, which: "from" | "to"): ActorPosition {
  const location = which === "from" ? step.from_location : step.to_location;
  return {
    actorId: step.actor_id,
    role: step.actor_role,
    label: step.actor_role === "driver" ? "您的车辆" : "外侧阻挡车辆",
    floorId: location.floor_id,
    x_m: location.coordinate.x_m,
    y_m: location.coordinate.y_m,
  };
}

function mix(from: ActorPosition, to: ActorPosition, progress: number): ActorPosition {
  const safe = Math.min(1, Math.max(0, progress));
  return {
    ...from,
    floorId: safe < 0.5 ? from.floorId : to.floorId,
    x_m: from.x_m + (to.x_m - from.x_m) * safe,
    y_m: from.y_m + (to.y_m - from.y_m) * safe,
  };
}

function movingPosition(
  layout: ParkingFacilityLayout,
  step: TandemReplayStep,
  progress: number,
): ActorPosition {
  const from = atLocation(step, "from");
  const to = atLocation(step, "to");
  if (step.route.edge_ids.length === 0 || step.route.dynamic_eta_s <= 0) {
    return mix(from, to, progress);
  }
  const start = routeVehiclePosition(layout, step.route, routeTimeline(step.route, 0));
  const end = routeVehiclePosition(
    layout,
    step.route,
    routeTimeline(step.route, step.route.dynamic_eta_s),
  );
  if (start === null || end === null) return mix(from, to, progress);
  const startActor = { ...from, floorId: start.floor_id, x_m: start.x_m, y_m: start.y_m };
  const endActor = { ...from, floorId: end.floor_id, x_m: end.x_m, y_m: end.y_m };
  if (progress <= 0.12) return mix(from, startActor, progress / 0.12);
  if (progress >= 0.88) return mix(endActor, to, (progress - 0.88) / 0.12);
  const routeProgress = (progress - 0.12) / 0.76;
  const position = routeVehiclePosition(
    layout,
    step.route,
    routeTimeline(step.route, routeProgress * step.route.dynamic_eta_s),
  );
  return position === null ? mix(from, to, progress) : {
    ...from,
    floorId: position.floor_id,
    x_m: position.x_m,
    y_m: position.y_m,
  };
}

export function tandemReplayFrame(
  layout: ParkingFacilityLayout,
  replay: TandemReplay,
  elapsedS: number,
  manualCompletedSteps?: number,
): TandemReplayFrame {
  const steps = replay.steps;
  const safeElapsed = Math.min(replay.total_duration_s, Math.max(0, elapsedS));
  const manualCount = manualCompletedSteps === undefined
    ? null
    : Math.min(steps.length, Math.max(0, manualCompletedSteps));
  const actors = new Map<string, ActorPosition>();
  for (const step of steps) {
    if (!actors.has(step.actor_id)) actors.set(step.actor_id, atLocation(step, "from"));
  }

  let activeStep = Math.max(0, steps.length - 1);
  let completedSteps = 0;
  let foundActive = false;
  for (const [index, step] of steps.entries()) {
    const manuallyComplete = manualCount !== null && index < manualCount;
    const manuallyActive = manualCount !== null && index === manualCount && manualCount < steps.length;
    const endS = step.starts_at_s + step.duration_s;
    if (manuallyComplete || manualCount === null && safeElapsed >= endS) {
      actors.set(step.actor_id, atLocation(step, "to"));
      completedSteps = index + 1;
      continue;
    }
    if (!foundActive && (manuallyActive || manualCount === null && safeElapsed >= step.starts_at_s)) {
      activeStep = index;
      foundActive = true;
      if (manualCount === null) {
        actors.set(
          step.actor_id,
          movingPosition(layout, step, (safeElapsed - step.starts_at_s) / step.duration_s),
        );
      }
    }
  }
  if (!foundActive && completedSteps < steps.length) activeStep = completedSteps;
  const complete = completedSteps === steps.length;
  const route = steps[Math.min(activeStep, steps.length - 1)]?.route;
  if (route === undefined) throw new Error("tandem replay has no route stage");
  return {
    actors: [...actors.values()],
    route,
    activeStep,
    completedSteps,
    complete,
    progress: manualCount === null
      ? safeElapsed / replay.total_duration_s
      : manualCount / steps.length,
    hiddenOccupiedSpaceIds: [
      replay.target_space_id,
      ...steps
        .filter((step) => step.action === "relocate_to_buffer")
        .map((step) => step.from_location.location_id),
    ],
  };
}
