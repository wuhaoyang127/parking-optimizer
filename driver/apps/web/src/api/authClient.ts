import { ApiError } from "./client";

export interface Account {
  success: boolean;
  username: string;
  role: string;
  token: string;
}

export interface SessionInfo {
  success: boolean;
  username: string;
  role: string;
}

async function postAuth(path: string, body: unknown): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
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
    const detail =
      typeof payload === "object" && payload !== null
        ? (payload as Record<string, unknown>).message ?? (payload as Record<string, unknown>).detail
        : undefined;
    const message = typeof detail === "string" ? detail : "请求失败";
    throw new ApiError(response.status, "AUTH_FAILED", message);
  }
  return payload;
}

export async function login(username: string, password: string): Promise<Account> {
  const payload = await postAuth("/api/v2/auth/login", { username, password });
  if (typeof payload !== "object" || payload === null || !("token" in payload)) {
    throw new ApiError(200, "CONTRACT_MISMATCH", "登录结果与接口契约不一致");
  }
  return payload as Account;
}

export async function validateSession(token: string): Promise<SessionInfo> {
  const payload = await postAuth("/api/v2/auth/session", { token });
  if (typeof payload !== "object" || payload === null) {
    throw new ApiError(200, "CONTRACT_MISMATCH", "会话结果与接口契约不一致");
  }
  return payload as SessionInfo;
}
