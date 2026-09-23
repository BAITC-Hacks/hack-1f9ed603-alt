export type TurbineSummary = {
  id: "turbine_1" | "turbine_2";
  latitude: number;
  longitude: number;
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

export type ForecastPoint = {
  time: string;
  normalized_power: number;
};

export type ForecastRunResponse = {
  run_id: string;
  status: "completed";
  turbine_id: TurbineSummary["id"];
  issued_at: string;
  horizon_hours: 24 | 48;
  unit: "normalized_power";
  input_data_cutoff_at: string;
  weather_source: string;
  weather_run_id: string;
  weather_run_issued_at: string;
  model_version: string;
  points: ForecastPoint[];
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

export function createForecastRun(payload: ForecastRunRequest): Promise<ForecastRunResponse> {
  return request("/api/forecast-runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
