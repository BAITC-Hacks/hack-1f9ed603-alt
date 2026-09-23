import type { MessageKey } from "./messages";

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
  weather_run_initialized_at: string;
  weather_run_usable_after_at: string;
  weather_actual_publication_at: string | null;
  model_version: string;
  points: ForecastPoint[];
};

export class ApiError extends Error {
  readonly messageKey: MessageKey;
  readonly status?: number;

  constructor(messageKey: MessageKey, status?: number, cause?: unknown) {
    super(messageKey, { cause });
    this.name = "ApiError";
    this.messageKey = messageKey;
    this.status = status;
  }
}

// The backend currently returns text rather than stable error codes.
const serverMessages: readonly MessageKey[] = [
  "Исходные данные недоступны или повреждены",
  "Прогнозная модель пока не подключена",
  "Данные для прогноза временно недоступны",
  "Прогнозная модель вернула некорректный результат",
  "Не удалось сохранить прогноз",
  "Внутренняя ошибка сервера",
];

function serverError(status: number, body: unknown): ApiError {
  const detail = isRecord(body) && typeof body.error === "string" ? body.error : undefined;
  const known = serverMessages.find((message) => message === detail);
  const fallback: MessageKey = status === 422 || status === 400
    ? "Сервер отклонил параметры запроса. Проверьте время, турбину и горизонт."
    : status === 503 ? "Сервис временно недоступен. Повторите попытку позже."
    : status >= 500 ? "Внутренняя ошибка сервера" : "Не удалось выполнить запрос";
  return new ApiError(known ?? fallback, status, detail);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch (cause) {
    throw new ApiError("Не удалось связаться с сервером. Проверьте подключение и повторите попытку.", undefined, cause);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch (cause) {
    if (!response.ok) throw serverError(response.status, undefined);
    throw new ApiError("Сервер вернул некорректный ответ", response.status, cause);
  }
  if (!response.ok) throw serverError(response.status, body);
  return body as T;
}

export function getHealth(): Promise<{ status: string }> {
  return request("/api/health");
}

export function getTurbines(): Promise<TurbinesResponse> {
  return request("/api/turbines");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseZonedTime(value: unknown): number {
  if (typeof value !== "string" || !/(Z|[+-]\d{2}:\d{2})$/.test(value)) return NaN;
  return Date.parse(value);
}

function isForecastRunResponse(value: unknown, payload: ForecastRunRequest): value is ForecastRunResponse {
  if (!isRecord(value) || value.status !== "completed" || value.turbine_id !== payload.turbine_id ||
      value.horizon_hours !== payload.horizon_hours || value.unit !== "normalized_power" ||
      !Array.isArray(value.points) || value.points.length !== payload.horizon_hours) return false;

  for (const field of ["run_id", "weather_source", "weather_run_id", "model_version"]) {
    if (typeof value[field] !== "string" || !value[field].trim()) return false;
  }

  const issuedAt = parseZonedTime(value.issued_at);
  const weatherIssuedAt = parseZonedTime(value.weather_run_issued_at);
  const weatherInitializedAt = parseZonedTime(value.weather_run_initialized_at);
  const weatherUsableAfterAt = parseZonedTime(value.weather_run_usable_after_at);
  const weatherPublicationAt = value.weather_actual_publication_at === null
    ? null : parseZonedTime(value.weather_actual_publication_at);
  const inputCutoffAt = parseZonedTime(value.input_data_cutoff_at);
  if (!Number.isFinite(issuedAt) || !Number.isFinite(weatherIssuedAt) ||
      !Number.isFinite(weatherInitializedAt) || !Number.isFinite(weatherUsableAfterAt) ||
      !Number.isFinite(inputCutoffAt) ||
      issuedAt !== Date.parse(payload.issued_at) || weatherIssuedAt !== weatherInitializedAt ||
      weatherInitializedAt > weatherUsableAfterAt || weatherUsableAfterAt > issuedAt ||
      (weatherPublicationAt !== null && (!Number.isFinite(weatherPublicationAt) ||
        weatherPublicationAt < weatherInitializedAt || weatherPublicationAt > issuedAt)) ||
      inputCutoffAt > issuedAt) return false;

  return value.points.every((point, index) =>
    isRecord(point) && typeof point.normalized_power === "number" &&
    Number.isFinite(point.normalized_power) && point.normalized_power >= 0 && point.normalized_power <= 1 &&
    parseZonedTime(point.time) === issuedAt + (index + 1) * 3_600_000
  );
}

export async function createForecastRun(payload: ForecastRunRequest): Promise<ForecastRunResponse> {
  const result = await request<unknown>("/api/forecast-runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!isForecastRunResponse(result, payload)) {
    throw new ApiError("API вернул прогноз, не соответствующий контракту");
  }
  return result;
}
