export interface ServerClockAnchor {
  observedAt: string;
  monotonicAt: number;
}

export function conservativeServerClock(
  observedAt: string,
  requestStartedAt: number,
  requestReceivedAt: number,
): ServerClockAnchor {
  return {
    observedAt: new Date(
      new Date(observedAt).getTime() + (requestReceivedAt - requestStartedAt),
    ).toISOString(),
    monotonicAt: requestReceivedAt,
  };
}
