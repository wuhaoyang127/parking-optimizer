import type { FacilitySnapshot, FacilitySpace, FacilitySpaceState, ParkingFacilityLayout } from "../../api/facilityClient";

export interface FacilityStats {
  total: number;
  available: number;
  occupied: number;
  unavailable: number;
  unknown: number;
  charging: number;
  tandem: number;
}

export function stateBySpace(snapshot: FacilitySnapshot): Map<string, FacilitySpaceState> {
  return new Map(snapshot.state.spaces.map((item) => [item.space_id, item]));
}

export function facilityStats(snapshot: FacilitySnapshot): FacilityStats {
  const statuses = snapshot.state.spaces.map((item) => item.effective_status);
  return {
    total: snapshot.layout.spaces.length,
    available: statuses.filter((item) => item === "available").length,
    occupied: statuses.filter((item) => item === "occupied").length,
    unavailable: statuses.filter((item) => item === "unavailable").length,
    unknown: statuses.filter((item) => item === "unknown").length,
    charging: snapshot.layout.spaces.filter((item) => item.charging).length,
    tandem: snapshot.layout.spaces.filter((item) => item.stack_group_id != null).length,
  };
}

export function spaceState(snapshot: FacilitySnapshot, spaceId: string | null): FacilitySpaceState | null {
  if (spaceId === null) return null;
  return snapshot.state.spaces.find((item) => item.space_id === spaceId) ?? null;
}

export function spaceById(layout: ParkingFacilityLayout, spaceId: string | null): FacilitySpace | null {
  if (spaceId === null) return null;
  return layout.spaces.find((item) => item.space_id === spaceId) ?? null;
}

export function points(values: { x_m: number; y_m: number }[]): string {
  return values.map((item) => `${String(item.x_m)},${String(item.y_m)}`).join(" ");
}

export function statusLabel(status: string): string {
  return { available: "空闲", occupied: "占用", unavailable: "不可用", unknown: "未知" }[status] ?? "未知";
}

export function sourceLabel(kind: string): string {
  return { synthetic: "Synthetic 演示数据", imported: "导入数据", real: "真实数据" }[kind] ?? "来源未知";
}
