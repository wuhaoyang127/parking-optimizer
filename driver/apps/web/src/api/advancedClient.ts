import { ApiError } from "./client";

export interface AdvancedStatus {
  account: { username: string; role: string };
  active: {
    release_id: string;
    algorithm_id: string;
    algorithm_version: string;
    release_hash: string;
    status: string;
  } | null;
  trial: {
    release_id: string;
    algorithm_id: string;
    trial_ratio: number;
    research_score: number;
  } | null;
  trial_stats: {
    trial_request_count: number;
    trial_success_count: number;
    trial_fallback_count: number;
  };
  recent_receipts: Array<{
    kind: string;
    requested_algorithm?: string;
    executed_algorithm?: string;
    status?: string;
    fallback_reason?: string | null;
    elapsed_ms?: number;
  }>;
}

export async function loadAdvancedStatus(token: string): Promise<AdvancedStatus> {
  let response: Response;
  try {
    response = await fetch("/api/v2/advanced/status", {
      headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "无法连接停车场服务，请检查本地后端或网络连接");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(response.status, "INVALID_JSON_RESPONSE", "停车场服务返回了无法解析的数据");
  }
  if (!response.ok) {
    const message =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "加载高级模式数据失败";
    throw new ApiError(response.status, "ADVANCED_LOAD_FAILED", message);
  }
  return payload as AdvancedStatus;
}

export interface ImportedLayout {
  parking_lot_id: string;
  layout_version: string;
  spaces: number;
  buffers: number;
}

export async function listLayouts(token: string): Promise<ImportedLayout[]> {
  const response = await fetch("/api/v2/advanced/layouts", {
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
  });
  const payload = await response.json();
  if (!response.ok) throw new ApiError(response.status, "ADVANCED_LOAD_FAILED", "加载已导入布局失败");
  return payload as ImportedLayout[];
}

export async function importLayout(
  token: string,
  json: string,
): Promise<{ saved: boolean; parking_lot_id: string }> {
  let body: unknown;
  try {
    body = JSON.parse(json);
  } catch {
    throw new ApiError(422, "INVALID_JSON", "JSON 格式不合法");
  }
  const response = await fetch("/api/v2/advanced/layouts", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    const message =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "导入布局失败";
    throw new ApiError(response.status, "ADVANCED_IMPORT_FAILED", message);
  }
  return payload as { saved: boolean; parking_lot_id: string };
}
