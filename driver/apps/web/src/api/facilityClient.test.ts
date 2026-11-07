import { expect, test } from "vitest";

import { isParkingFacilityLayout, isParkingFacilityState, isRoutePreview } from "./facilityClient";
import { facilityLayout, facilitySnapshot, facilityState, routePreview } from "../test/facilityFixture";

test("accepts a complete same-scope facility snapshot and route", () => {
  expect(isParkingFacilityLayout(facilityLayout)).toBe(true);
  expect(isParkingFacilityState(facilityState, facilityLayout)).toBe(true);
  expect(isRoutePreview(routePreview, facilitySnapshot)).toBe(true);
});

test("fails closed for unknown references and incomplete state", () => {
  const badLayout = structuredClone(facilityLayout) as unknown as Record<string, unknown>;
  (badLayout.spaces as Record<string, unknown>[])[0]!.access_node_id = "missing";
  expect(isParkingFacilityLayout(badLayout)).toBe(false);

  const badState = structuredClone(facilityState) as unknown as Record<string, unknown>;
  (badState.spaces as unknown[]).pop();
  expect(isParkingFacilityState(badState, facilityLayout)).toBe(false);

  const badRoute = structuredClone(routePreview) as unknown as Record<string, unknown>;
  (badRoute.route as Record<string, unknown>).edge_ids = ["missing-edge"];
  expect(isRoutePreview(badRoute, facilitySnapshot)).toBe(false);
});

test("fails closed for malformed rendered geometry and source metadata", () => {
  const badRestricted = structuredClone(facilityLayout) as unknown as Record<string, unknown>;
  badRestricted.restricted_areas = [{}];
  expect(isParkingFacilityLayout(badRestricted)).toBe(false);

  const badSource = structuredClone(facilityState) as unknown as Record<string, unknown>;
  (badSource.source as Record<string, unknown>).source_kind = "oracle";
  expect(isParkingFacilityState(badSource, facilityLayout)).toBe(false);

  const omittedRegistration = structuredClone(facilityLayout) as unknown as Record<string, unknown>;
  delete omittedRegistration.image_registration;
  expect(isParkingFacilityLayout(omittedRegistration)).toBe(true);

  const outsideRectangle = structuredClone(facilityLayout) as unknown as Record<string, unknown>;
  (((outsideRectangle.spaces as Record<string, unknown>[])[0]!.geometry as Record<string, unknown>).center as Record<string, unknown>).x_m = 0.5;
  expect(isParkingFacilityLayout(outsideRectangle)).toBe(false);
});

test("binds route previews to the requested target and contiguous directed path", () => {
  expect(isRoutePreview(routePreview, facilitySnapshot, { entranceId: "south", targetSpaceId: "P-01" })).toBe(true);
  expect(isRoutePreview(routePreview, facilitySnapshot, { entranceId: "south", targetSpaceId: "P-02" })).toBe(false);

  const disconnected = structuredClone(routePreview) as unknown as Record<string, unknown>;
  const route = disconnected.route as Record<string, unknown>;
  route.node_ids = ["access", "entry"];
  route.from_node_id = "access";
  route.to_node_id = "entry";
  expect(isRoutePreview(disconnected, facilitySnapshot)).toBe(false);

  const badInstruction = structuredClone(routePreview) as unknown as Record<string, unknown>;
  ((badInstruction.route as Record<string, unknown>).instructions as Record<string, unknown>[])[0]!.edge_id = "access-exit";
  expect(isRoutePreview(badInstruction, facilitySnapshot)).toBe(false);
});
