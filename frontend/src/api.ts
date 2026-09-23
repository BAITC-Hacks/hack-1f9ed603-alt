export type TurbineSummary = {
  id: "turbine_1" | "turbine_2";
  rows: number;
  first_observation: string;
  last_observation: string;
  expected_rows: number;
  missing_intervals: number;
};

export type TurbinesResponse = { turbines: TurbineSummary[] };

export type ForecastRunRequest = {
  turbine_id: TurbineSummary["id"];
  issued_at: string;
  horizon_hours: 24 | 48;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const body: unknown = await response.json();
  if (!response.ok) {
    const error = body as { error?: string };
    throw new Error(error.error ?? `HTTP ${response.status}`);
  }
  return body as T;
}

export function getHealth(): Promise<{ status: string }> {
  return request("/api/health");
}

export function getTurbines(): Promise<TurbinesResponse> {
  return request("/api/turbines");
}

export function createForecastRun(payload: ForecastRunRequest): Promise<unknown> {
  return request("/api/forecast-runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
