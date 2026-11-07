import type { Route } from "../api/recommendationClient";

export interface RouteTimeline {
  activeStep: number;
  edgeProgress: number;
  progress: number;
}

export function routeTimeline(route: Route, elapsedS: number): RouteTimeline {
  if (route.instructions.length === 0) return { activeStep: 0, edgeProgress: 1, progress: 1 };
  const total = route.instructions.reduce((sum, instruction) => sum + instruction.travel_time_s, 0);
  if (total <= 0) return { activeStep: route.instructions.length - 1, edgeProgress: 1, progress: 1 };
  const safeTotal = Math.max(total, 1);
  const clampedElapsed = Math.min(Math.max(elapsedS, 0), safeTotal);
  let remaining = clampedElapsed;
  for (let index = 0; index < route.instructions.length; index += 1) {
    const instruction = route.instructions[index];
    if (instruction === undefined) continue;
    const duration = instruction.travel_time_s;
    if (remaining <= duration || index === route.instructions.length - 1) {
      return {
        activeStep: index,
        edgeProgress: duration === 0 ? 1 : Math.min(remaining / duration, 1),
        progress: clampedElapsed / safeTotal,
      };
    }
    remaining -= duration;
  }
  return { activeStep: route.instructions.length - 1, edgeProgress: 1, progress: 1 };
}
