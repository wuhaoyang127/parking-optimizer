import { useCallback, useMemo, useState } from "react";

import type { ParkingFacilityLayout } from "../../api/facilityClient";

export interface ViewportRect { x: number; y: number; width: number; height: number }

export function useFacilityViewport(layout: ParkingFacilityLayout, floorId: string) {
  const base = useMemo<ViewportRect>(() => ({
    x: (layout.floors.find((item) => item.floor_id === floorId)?.bounds.min_x_m ?? layout.bounds.min_x_m) - 4,
    y: (layout.floors.find((item) => item.floor_id === floorId)?.bounds.min_y_m ?? layout.bounds.min_y_m) - 4,
    width: (layout.floors.find((item) => item.floor_id === floorId)?.bounds.max_x_m ?? layout.bounds.max_x_m) - (layout.floors.find((item) => item.floor_id === floorId)?.bounds.min_x_m ?? layout.bounds.min_x_m) + 8,
    height: (layout.floors.find((item) => item.floor_id === floorId)?.bounds.max_y_m ?? layout.bounds.max_y_m) - (layout.floors.find((item) => item.floor_id === floorId)?.bounds.min_y_m ?? layout.bounds.min_y_m) + 8,
  }), [floorId, layout]);
  const [viewport, setViewport] = useState(base);

  const clamp = useCallback((next: ViewportRect): ViewportRect => {
    const minimumWidth = base.width / 5;
    const width = Math.min(base.width, Math.max(minimumWidth, next.width));
    const height = width * (base.height / base.width);
    return {
      x: Math.min(base.x + base.width - width, Math.max(base.x, next.x)),
      y: Math.min(base.y + base.height - height, Math.max(base.y, next.y)),
      width,
      height,
    };
  }, [base]);

  const zoomAt = useCallback((factor: number, x: number, y: number) => {
    setViewport((current) => clamp({
      x: x - (x - current.x) * factor,
      y: y - (y - current.y) * factor,
      width: current.width * factor,
      height: current.height * factor,
    }));
  }, [clamp]);

  const panBy = useCallback((dx: number, dy: number) => {
    setViewport((current) => clamp({ ...current, x: current.x + dx, y: current.y + dy }));
  }, [clamp]);

  const focus = useCallback((x: number, y: number) => {
    const width = base.width / 3.4;
    const height = width * (base.height / base.width);
    setViewport(clamp({ x: x - width / 2, y: y - height / 2, width, height }));
  }, [base, clamp]);

  return {
    viewport,
    viewBox: `${String(viewport.x)} ${String(viewport.y)} ${String(viewport.width)} ${String(viewport.height)}`,
    zoomLevel: base.width / viewport.width,
    reset: () => { setViewport(base); },
    zoomIn: () => { zoomAt(0.72, viewport.x + viewport.width / 2, viewport.y + viewport.height / 2); },
    zoomOut: () => { zoomAt(1.38, viewport.x + viewport.width / 2, viewport.y + viewport.height / 2); },
    zoomAt,
    panBy,
    focus,
  };
}
