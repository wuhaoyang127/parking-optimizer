import type { DiscoveryLotSummary, ParkingLot } from "../api/client";

interface MapPosition { x: number; y: number; shortName: string; icon: string }

const venuePresentation: Record<ParkingLot["venue_type"], Pick<MapPosition, "shortName" | "icon">> = {
  commercial: { shortName: "商场", icon: "商" },
  school: { shortName: "学校", icon: "校" },
  hospital: { shortName: "医院", icon: "医" },
  transport_hub: { shortName: "枢纽", icon: "枢" },
};

export function mapPosition(lot: ParkingLot, discovery: DiscoveryLotSummary): MapPosition {
  return { x: discovery.position.x_pct, y: discovery.position.y_pct, ...venuePresentation[lot.venue_type] };
}

export function availabilityLevel(lot: ParkingLot): "good" | "medium" | "busy" {
  const ratio = lot.available_spaces / lot.total_spaces;
  if (ratio >= 0.5) return "good";
  if (ratio >= 0.25) return "medium";
  return "busy";
}

export function availabilityLabel(lot: ParkingLot): string {
  return { good: "充足", medium: "适中", busy: "紧张" }[availabilityLevel(lot)];
}

export function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "更新时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

export function formatDistance(distanceM: number): string {
  return distanceM < 1000 ? `${String(distanceM)} 米` : `${(distanceM / 1000).toFixed(1)} 公里`;
}

export function formatEta(etaS: number): string {
  return `约 ${String(Math.max(1, Math.ceil(etaS / 60)))} 分钟`;
}
