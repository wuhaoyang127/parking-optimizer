import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from "react";

import type { FacilityRoute, FacilitySnapshot } from "../../api/facilityClient";
import { FacilityBaseLayers, FacilityRouteLayer, FacilitySpaceLayer, FacilityVehicleLayer } from "./FacilityLayers";
import { useFacilityViewport } from "./useFacilityViewport";

export interface FacilityActor {
  actorId: string;
  role: "driver" | "blocker";
  label: string;
  floorId: string;
  x_m: number;
  y_m: number;
}

const NO_ACTORS: readonly FacilityActor[] = [];
const NO_HIDDEN_SPACES: readonly string[] = [];

export function FacilityCanvas({ snapshot, floorId, selectedSpaceId, targetSpaceId = null, route = null, vehicle = null, actors = NO_ACTORS, hiddenOccupiedSpaceIds = NO_HIDDEN_SPACES, routeMotion = false, ariaLabel = "完整停车场布局", onSelect, onFocusReady }: { snapshot: FacilitySnapshot; floorId: string; selectedSpaceId: string | null; targetSpaceId?: string | null; route?: FacilityRoute | null; vehicle?: { x_m: number; y_m: number } | null; actors?: readonly FacilityActor[]; hiddenOccupiedSpaceIds?: readonly string[]; routeMotion?: boolean; ariaLabel?: string; onSelect: (spaceId: string) => void; onFocusReady?: (focus: () => void) => void }) {
  const controller = useFacilityViewport(snapshot.layout, floorId);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number; startX: number; startY: number; spaceId: string | null }>());
  const pinchDistance = useRef<number | null>(null);
  const gestureMoved = useRef(false);
  const touchSelect = useCallback((id: string) => {
    if (!gestureMoved.current) onSelect(id);
  }, [onSelect]);
  const selected = snapshot.layout.spaces.find((item) => item.space_id === selectedSpaceId);
  const focusSelected = useCallback(() => {
    if (selected !== undefined) controller.focus(selected.geometry.center.x_m, selected.geometry.center.y_m);
  }, [controller, selected]);

  useEffect(() => {
    onFocusReady?.(focusSelected);
  }, [focusSelected, onFocusReady]);

  function domainPoint(clientX: number, clientY: number) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (rect === undefined) return { x: controller.viewport.x, y: controller.viewport.y };
    return { x: controller.viewport.x + ((clientX - rect.left) / rect.width) * controller.viewport.width, y: controller.viewport.y + ((clientY - rect.top) / rect.height) * controller.viewport.height };
  }

  function wheel(event: WheelEvent<SVGSVGElement>) {
    event.preventDefault();
    const point = domainPoint(event.clientX, event.clientY);
    controller.zoomAt(event.deltaY > 0 ? 1.16 : 0.86, point.x, point.y);
  }

  function pointerDown(event: PointerEvent<SVGSVGElement>) {
    if (pointers.current.size === 0) gestureMoved.current = false;
    const spaceId = (event.target as Element).closest<SVGGElement>(".facility-space")?.dataset.spaceId ?? null;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, spaceId });
    if (pointers.current.size === 1) {
      if (spaceId === null) setDrag({ x: event.clientX, y: event.clientY });
    } else {
      const [first, second] = [...pointers.current.values()];
      if (first === undefined || second === undefined) return;
      pinchDistance.current = Math.hypot(second.x - first.x, second.y - first.y);
      gestureMoved.current = true;
      setDrag(null);
    }
  }

  function pointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!pointers.current.has(event.pointerId)) return;
    const previous = pointers.current.get(event.pointerId);
    if (previous === undefined) return;
    pointers.current.set(event.pointerId, { ...previous, x: event.clientX, y: event.clientY });
    if (pointers.current.size >= 2) {
      try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* capture is an optional enhancement */ }
      const [first, second] = [...pointers.current.values()];
      if (first === undefined || second === undefined) return;
      const nextDistance = Math.hypot(second.x - first.x, second.y - first.y);
      const previousDistance = pinchDistance.current;
      if (previousDistance !== null && nextDistance > 0) {
        const midpoint = domainPoint((first.x + second.x) / 2, (first.y + second.y) / 2);
        controller.zoomAt(previousDistance / nextDistance, midpoint.x, midpoint.y);
      }
      pinchDistance.current = nextDistance;
      return;
    }
    const movedFromStart = Math.hypot(event.clientX - previous.startX, event.clientY - previous.startY);
    if (movedFromStart > 12) {
      gestureMoved.current = true;
      try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* capture is an optional enhancement */ }
    }
    if (previous.spaceId !== null && !gestureMoved.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    controller.panBy(-((event.clientX - previous.x) / rect.width) * controller.viewport.width, -((event.clientY - previous.y) / rect.height) * controller.viewport.height);
    setDrag({ x: event.clientX, y: event.clientY });
  }

  function pointerEnd(event: PointerEvent<SVGSVGElement>) {
    pointers.current.delete(event.pointerId);
    pinchDistance.current = null;
    const remaining = [...pointers.current.values()][0];
    setDrag(remaining ?? null);
  }

  function keyboard(event: KeyboardEvent<SVGSVGElement>) {
    const step = controller.viewport.width / 14;
    if (event.key === "ArrowLeft") controller.panBy(-step, 0);
    else if (event.key === "ArrowRight") controller.panBy(step, 0);
    else if (event.key === "ArrowUp") controller.panBy(0, -step);
    else if (event.key === "ArrowDown") controller.panBy(0, step);
    else if (event.key === "+" || event.key === "=") controller.zoomIn();
    else if (event.key === "-") controller.zoomOut();
    else if (event.key === "0") controller.reset();
    else return;
    event.preventDefault();
  }

  return (
    <div className="facility-canvas-wrap">
      <div className="facility-toolbar" aria-label="画布工具"><button type="button" title="放大" aria-label="放大" onClick={controller.zoomIn}>+</button><button type="button" title="缩小" aria-label="缩小" onClick={controller.zoomOut}>−</button><button type="button" title="重置视图" aria-label="重置视图" onClick={controller.reset}>↺</button><span>{controller.zoomLevel.toFixed(1)}×</span></div>
      <svg ref={svgRef} className={drag === null ? "facility-canvas" : "facility-canvas dragging"} viewBox={controller.viewBox} role="application" aria-label={ariaLabel} tabIndex={0} onWheel={wheel} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerEnd} onPointerCancel={pointerEnd} onKeyDown={keyboard}>
        <FacilityBaseLayers layout={snapshot.layout} floorId={floorId} />
        <FacilitySpaceLayer layout={snapshot.layout} state={snapshot.state} floorId={floorId} selectedSpaceId={selectedSpaceId} targetSpaceId={targetSpaceId} hiddenOccupiedSpaceIds={hiddenOccupiedSpaceIds} zoomLevel={controller.zoomLevel} onSelect={onSelect} onTouchSelect={touchSelect} />
        <FacilityRouteLayer layout={snapshot.layout} floorId={floorId} route={route} motion={routeMotion} />
        <FacilityVehicleLayer {...(vehicle === null ? {} : { x: vehicle.x_m, y: vehicle.y_m })} />
        {actors.filter((actor) => actor.floorId === floorId).map((actor) => <FacilityVehicleLayer key={actor.actorId} x={actor.x_m} y={actor.y_m} role={actor.role} label={actor.label} />)}
      </svg>
    </div>
  );
}
