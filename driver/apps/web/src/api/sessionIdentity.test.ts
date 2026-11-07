import { afterEach, expect, test, vi } from "vitest";

import { getDriverSessionId } from "./sessionIdentity";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

test("creates one valid driver session id and reuses it across reads", () => {
  vi.spyOn(crypto, "randomUUID").mockReturnValue("123e4567-e89b-12d3-a456-426614174000");
  expect(getDriverSessionId()).toBe("driver-123e4567-e89b-12d3-a456-426614174000");
  expect(getDriverSessionId()).toBe("driver-123e4567-e89b-12d3-a456-426614174000");
});

test("replaces an invalid stored value instead of sending it to the API", () => {
  localStorage.setItem("parksim.driver-session-id.v1", "bad id");
  vi.spyOn(crypto, "randomUUID").mockReturnValue("123e4567-e89b-12d3-a456-426614174001");
  expect(getDriverSessionId()).toBe("driver-123e4567-e89b-12d3-a456-426614174001");
});

test("replaces a stored value that exceeds the domain maximum length", () => {
  localStorage.setItem("parksim.driver-session-id.v1", `driver-${"x".repeat(128)}`);
  vi.spyOn(crypto, "randomUUID").mockReturnValue("123e4567-e89b-12d3-a456-426614174002");
  expect(getDriverSessionId()).toBe("driver-123e4567-e89b-12d3-a456-426614174002");
});
