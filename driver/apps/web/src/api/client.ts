import type { components } from "./schema";
import { getDriverSessionId } from "./sessionIdentity";

export type ParkingLot = components["schemas"]["ParkingLot"];
export type DiscoveryArea = components["schemas"]["DiscoveryArea"];
export type DiscoveryLotSummary = components["schemas"]["DiscoveryLotSummary"];
export type DiscoveryReferencePoint = components["schemas"]["DiscoveryReferencePoint"];
type ErrorResponse = components["schemas"]["ErrorResponse"];

export interface ParkingDiscoveryData {
  lots: ParkingLot[];
  area: DiscoveryArea;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isAbortError(value: unknown): boolean {
  return isRecord(value) && value.name === "AbortError";
}

function isFiniteNumber(value: unknown, minimum = 0, maximum = Number.POSITIVE_INFINITY): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= minimum && value <= maximum;
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    typeof value.message === "string" &&
    typeof value.request_id === "string" &&
    Array.isArray(value.details)
  );
}

function isParkingLot(value: unknown): value is ParkingLot {
  if (!isRecord(value) || !isRecord(value.pricing) || !isRecord(value.data_source)) return false;
  return (
    value.schema_version === "2.0.0" &&
    typeof value.parking_lot_id === "string" &&
    typeof value.name === "string" &&
    typeof value.region_label === "string" &&
    ["commercial", "school", "hospital", "transport_hub"].includes(String(value.venue_type)) &&
    typeof value.synthetic === "boolean" &&
    ["open", "closed", "unknown"].includes(String(value.opening_status)) &&
    Number.isInteger(value.available_spaces) && isFiniteNumber(value.available_spaces) &&
    Number.isInteger(value.total_spaces) && isFiniteNumber(value.total_spaces, 1) &&
    value.available_spaces <= value.total_spaces &&
    Number.isInteger(value.charging_spaces) && isFiniteNumber(value.charging_spaces) &&
    isFiniteNumber(value.pricing.first_hour_yuan) &&
    typeof value.pricing.note === "string" &&
    typeof value.updated_at === "string" &&
    ["synthetic", "real"].includes(String(value.data_source.mode)) &&
    ["healthy", "degraded", "unavailable"].includes(String(value.data_source.health))
  );
}

function isPosition(value: unknown): boolean {
  return isRecord(value) && isFiniteNumber(value.x_pct, 0, 100) && isFiniteNumber(value.y_pct, 0, 100);
}

function isDiscoveryArea(value: unknown): value is DiscoveryArea {
  if (!isRecord(value) || !Array.isArray(value.references) || !Array.isArray(value.lots)) return false;
  const referenceIds = value.references.flatMap((reference) =>
    isRecord(reference) && typeof reference.reference_id === "string" ? [reference.reference_id] : [],
  );
  const referenceIdSet = new Set(referenceIds);
  const referencesValid = value.references.every(
    (reference) =>
      isRecord(reference) &&
      typeof reference.reference_id === "string" &&
      typeof reference.label === "string" &&
      isPosition(reference.position),
  );
  const lotsValid = value.lots.every(
    (lot) =>
      isRecord(lot) &&
      typeof lot.parking_lot_id === "string" &&
      typeof lot.opening_hours_label === "string" &&
      isPosition(lot.position) &&
      Array.isArray(lot.offsite_estimates) &&
      lot.offsite_estimates.length === referenceIds.length &&
      new Set(
        lot.offsite_estimates.flatMap((estimate) =>
          isRecord(estimate) && typeof estimate.reference_id === "string" ? [estimate.reference_id] : [],
        ),
      ).size === referenceIds.length &&
      lot.offsite_estimates.every(
        (estimate) =>
          isRecord(estimate) &&
          typeof estimate.reference_id === "string" &&
          referenceIdSet.has(estimate.reference_id) &&
          Number.isInteger(estimate.distance_m) &&
          isFiniteNumber(estimate.distance_m) &&
          Number.isInteger(estimate.eta_s) &&
          isFiniteNumber(estimate.eta_s),
      ),
  );
  return (
    value.schema_version === "1.0.0" &&
    typeof value.area_id === "string" &&
    typeof value.display_version === "string" &&
    value.coordinate_system === "percentage_top_left" &&
    typeof value.synthetic === "boolean" &&
    ["synthetic", "real"].includes(String(value.source_mode)) &&
    value.synthetic === (value.source_mode === "synthetic") &&
    ["healthy", "degraded", "unavailable"].includes(String(value.source_health)) &&
    typeof value.default_reference_id === "string" &&
    referenceIds.length > 0 &&
    referenceIdSet.size === referenceIds.length &&
    referenceIdSet.has(value.default_reference_id) &&
    typeof value.updated_at === "string" &&
    referencesValid &&
    lotsValid
  );
}

async function fetchPayload(
  path: string,
  signal: AbortSignal,
  sessionId?: string,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: {
        Accept: "application/json",
        ...(sessionId === undefined ? {} : { "X-Session-ID": sessionId }),
      },
      signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "无法连接停车场服务，请检查本地后端或网络连接");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(
      response.status,
      "INVALID_JSON_RESPONSE",
      "停车场服务返回了无法解析的数据",
      response.headers.get("X-Request-ID"),
    );
  }
  if (!response.ok) {
    if (isErrorResponse(payload)) {
      throw new ApiError(response.status, payload.code, payload.message, payload.request_id);
    }
    throw new ApiError(response.status, "UNEXPECTED_API_ERROR", "停车场服务暂时不可用");
  }
  return payload;
}

export async function loadParkingDiscovery(signal?: AbortSignal): Promise<ParkingDiscoveryData> {
  const controller = new AbortController();
  if (signal?.aborted === true) controller.abort(signal.reason);
  const timeoutReason = new Error("parking discovery request timed out");
  const timeout = globalThis.setTimeout(() => {
    controller.abort(timeoutReason);
  }, 10_000);
  const abortFromCaller = () => {
    controller.abort();
  };
  signal?.addEventListener("abort", abortFromCaller, { once: true });
  try {
    controller.signal.throwIfAborted();
    const sessionId = getDriverSessionId();
    const [lotsPayload, areaPayload] = await Promise.all([
      fetchPayload("/api/v2/parking-lots", controller.signal, sessionId),
      fetchPayload("/api/v2/discovery-area", controller.signal),
    ]);
    if (!Array.isArray(lotsPayload) || !lotsPayload.every(isParkingLot) || !isDiscoveryArea(areaPayload)) {
      throw new ApiError(200, "CONTRACT_MISMATCH", "停车场数据与版本化接口契约不一致");
    }
    if (areaPayload.source_health === "unavailable") {
      throw new ApiError(503, "DATA_SOURCE_UNAVAILABLE", "区域发现数据源不可用");
    }
    const lotIds = new Set(lotsPayload.map((lot) => lot.parking_lot_id));
    const discoveryLotIds = new Set(areaPayload.lots.map((lot) => lot.parking_lot_id));
    if (
      lotIds.size !== discoveryLotIds.size ||
      [...lotIds].some((lotId) => !discoveryLotIds.has(lotId)) ||
      lotsPayload.some(
        (lot) =>
          lot.synthetic !== (lot.data_source.mode === "synthetic") ||
          lot.synthetic !== areaPayload.synthetic ||
          lot.data_source.mode !== areaPayload.source_mode ||
          lot.charging_spaces > lot.total_spaces,
      )
    ) {
      throw new ApiError(200, "DISCOVERY_SCOPE_MISMATCH", "停车场列表与区域发现数据不属于同一数据源");
    }
    return { lots: lotsPayload, area: areaPayload };
  } catch (error) {
    if (controller.signal.reason === timeoutReason) {
      throw new ApiError(0, "REQUEST_TIMEOUT", "停车场服务响应超时，请稍后重试");
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}
