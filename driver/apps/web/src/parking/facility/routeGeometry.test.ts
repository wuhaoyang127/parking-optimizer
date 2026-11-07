import { describe, expect, it } from "vitest";

import type { FacilityRoute, ParkingFacilityLayout } from "../../api/facilityClient";
import { facilityLayout, routePreview } from "../../test/facilityFixture";
import { routeSegmentsForFloor, routeVehiclePosition } from "./routeGeometry";

describe("facility route geometry", () => {
  it("projects time progress along the authoritative curved centerline", () => {
    const layout = structuredClone(facilityLayout) as ParkingFacilityLayout;
    const edge = layout.edges[0];
    if (edge === undefined) throw new Error("missing fixture edge");
    layout.edges[0] = { ...edge, centerline: [{ x_m: 2, y_m: 15 }, { x_m: 2, y_m: 24 }, { x_m: 20, y_m: 24 }] };
    const position = routeVehiclePosition(layout, routePreview.route, { activeStep: 0, edgeProgress: 0.5, progress: 0.5 });
    expect(position).toEqual({ x_m: 6.5, y_m: 24, floor_id: "floor-1" });
    expect(routeSegmentsForFloor(layout, routePreview.route, "floor-1")[0]).toEqual(layout.edges[0].centerline);
  });

  it("reverses an undirected centerline and rejects a directed reverse traversal", () => {
    const layout = structuredClone(facilityLayout) as ParkingFacilityLayout;
    const edge = layout.edges[0];
    if (edge === undefined) throw new Error("missing fixture edge");
    layout.edges[0] = { ...edge, directed: false };
    const reverse = {
      ...routePreview.route,
      from_node_id: "access",
      to_node_id: "entry",
      node_ids: ["access", "entry"],
    } satisfies FacilityRoute;
    expect(routeVehiclePosition(layout, reverse, { activeStep: 0, edgeProgress: 0.25, progress: 0.25 })?.x_m).toBe(15.5);
    layout.edges[0] = { ...edge, directed: true };
    expect(routeVehiclePosition(layout, reverse, { activeStep: 0, edgeProgress: 0.25, progress: 0.25 })).toBeNull();
  });

  it("shows a cross-floor edge on both endpoint floors and transfers the vehicle floor", () => {
    const layout = structuredClone(facilityLayout) as ParkingFacilityLayout;
    layout.floors.push({ floor_id: "floor-2", label: "地下层", elevation_m: -4, bounds: layout.bounds });
    const access = layout.nodes.find((node) => node.node_id === "access");
    if (access === undefined) throw new Error("missing fixture access node");
    access.floor_id = "floor-2";
    expect(routeSegmentsForFloor(layout, routePreview.route, "floor-1")).toHaveLength(1);
    expect(routeSegmentsForFloor(layout, routePreview.route, "floor-2")).toHaveLength(1);
    expect(routeVehiclePosition(layout, routePreview.route, { activeStep: 0, edgeProgress: 0.49, progress: 0.49 })?.floor_id).toBe("floor-1");
    expect(routeVehiclePosition(layout, routePreview.route, { activeStep: 0, edgeProgress: 0.5, progress: 0.5 })?.floor_id).toBe("floor-2");
  });
});
