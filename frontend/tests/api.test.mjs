import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Compile this standalone API module with the project's existing TypeScript
// dependency so the tests also run on the supported Node.js 20 runtime.
const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
});
const { ApiError, createForecastRun, getAssistantForecastParameters, issuedAtError } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const defaults = { turbine_id: "turbine_2", issued_at: "2026-02-01T12:00:00Z", horizon_hours: 48 };
const resolved = { ...defaults, issued_at: "2026-02-22T17:00:00Z" };
const input = { message: "22 февраля 17:00 2026 года", defaults, language: "ru" };
const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

// Synthetic contract fixture; production values always come from forecast-runs.
function forecastResult(request) {
  return {
    run_id: "test-run", status: "completed", ...request, unit: "normalized_power",
    input_data_cutoff_at: "2026-01-31T23:00:00Z", weather_source: "test-weather",
    weather_run_id: "test-weather-run", weather_run_issued_at: "2026-02-22T00:00:00Z",
    weather_run_initialized_at: "2026-02-22T00:00:00Z",
    weather_run_usable_after_at: "2026-02-22T12:00:00Z", weather_actual_publication_at: null,
    model_version: "test-model",
    points: Array.from({ length: request.horizon_hours }, (_, i) => ({
      time: new Date(Date.parse(request.issued_at) + (i + 1) * 3_600_000).toISOString(),
      normalized_power: (i + 1) / request.horizon_hours,
    })),
  };
}

test("AI sends trimmed text with current defaults/language and returns only forecast parameters", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async (path, options) => {
    assert.equal(path, "/api/assistant/forecast-parameters");
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), { ...input, language: "kk" });
    return json({ status: "ready", request: resolved, message: null });
  });
  assert.deepEqual(await getAssistantForecastParameters({ ...input, message: `  ${input.message}  `, language: "kk" }), {
    status: "ready", request: resolved, message: null,
  });
  assert.equal(fetch.mock.calls.length, 1);
});

test("AI parameters and equivalent manual parameters use the same forecast endpoint and result contract", async (t) => {
  const posts = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    if (path === "/api/assistant/forecast-parameters") return json({ status: "ready", request: resolved, message: null });
    assert.equal(path, "/api/forecast-runs");
    posts.push(JSON.parse(options.body));
    return json(forecastResult(resolved), 201);
  });
  const answer = await getAssistantForecastParameters(input);
  const assistantRun = await createForecastRun(answer.request);
  const manualRun = await createForecastRun(resolved);
  assert.deepEqual(posts, [resolved, resolved]);
  assert.deepEqual(assistantRun, manualRun);
  assert.equal(assistantRun.points.length, 48);
});

test("clarification is returned without starting a forecast", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async (path) => {
    assert.equal(path, "/api/assistant/forecast-parameters");
    return json({ status: "clarification", request: null, message: "  Какой год?  " });
  });
  assert.deepEqual(await getAssistantForecastParameters(input), {
    status: "clarification", request: null, message: "Какой год?",
  });
  assert.equal(fetch.mock.calls.length, 1);
});

test("rejects invalid AI response variants and calendar/full-hour parameters", async (t) => {
  const responses = [
    null, [], {},
    { status: "ready", request: resolved, message: "extra text" },
    { status: "ready", request: { ...resolved, turbine_id: "turbine_3" }, message: null },
    { status: "ready", request: { ...resolved, horizon_hours: 72 }, message: null },
    { status: "ready", request: { ...resolved, horizon_hours: "48" }, message: null },
    { status: "ready", request: { ...resolved, normalized_power: 0.6 }, message: null },
    { status: "ready", request: { ...resolved, issued_at: "2026-02-30T17:00:00Z" }, message: null },
    { status: "ready", request: { ...resolved, issued_at: "2026-02-22T17:30:00Z" }, message: null },
    { status: "ready", request: { ...resolved, issued_at: "2026-02-22T17:00:00.0001Z" }, message: null },
    { status: "ready", request: { ...resolved, issued_at: "2026-02-22T17:00:00" }, message: null },
    { status: "clarification", request: resolved, message: "Какой год?" },
    { status: "clarification", request: null, message: " " },
    { status: "clarification", request: null, message: "x".repeat(4001) },
    { status: "complete", request: resolved, message: null },
  ];
  t.mock.method(globalThis, "fetch", async () => json(responses.shift()));
  while (responses.length) {
    await assert.rejects(getAssistantForecastParameters(input), (error) =>
      error instanceof ApiError && error.messageKey === "Сервис ИИ вернул некорректный ответ");
  }
});

test("shared time validation accepts real whole UTC hours and rejects impossible dates", () => {
  for (const value of [
    "2026-02-22T17:00:00Z", "2024-02-29T17:00Z", "2026-02-22T22:00:00+05:00",
    "2026-02-22T22:30:00+05:30", "2026-02-22T17:00:00.0000Z", "0099-02-22T17:00:00Z",
  ]) assert.equal(issuedAtError(value), null, value);
  for (const value of [
    "2026-02-29T17:00:00Z", "2026-04-31T17:00:00Z", "2026-00-22T17:00:00Z",
    "2026-02-22T24:00:00Z", "2026-02-22T17:00:00+25:00", "2026-02-22T17:00:00+00:60",
    "2026-02-22T17:30:00Z", "2026-02-22T17:00:01Z", "2026-02-22T17:00:00.0001Z",
    "2026-02-22T17:00:00", "0000-02-22T17:00:00Z", "nonsense",
  ]) assert.notEqual(issuedAtError(value), null, value);
});

test("invalid text and defaults are rejected before sending a request", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", () => { throw new Error("unexpected fetch"); });
  for (const payload of [
    { ...input, message: "  " }, { ...input, message: "x".repeat(4001) },
    { ...input, defaults: { ...defaults, issued_at: "2026-02-30T17:00:00Z" } },
    { ...input, language: "unknown" },
  ]) await assert.rejects(getAssistantForecastParameters(payload), ApiError);
  assert.equal(fetch.mock.calls.length, 0);
});

test("known AI service failures preserve translated keys and HTTP status", async (t) => {
  for (const detail of [
    "Сервис ИИ не настроен", "Ключ сервиса ИИ отклонён", "Лимит сервиса ИИ исчерпан",
    "Сервис ИИ временно недоступен", "Сервис ИИ вернул некорректный ответ",
  ]) {
    const fetch = t.mock.method(globalThis, "fetch", async () => json({ error: detail }, 503));
    await assert.rejects(getAssistantForecastParameters(input), (error) =>
      error instanceof ApiError && error.messageKey === detail && error.status === 503);
    fetch.mock.restore();
  }
});

test("unexpected server text, malformed JSON and network failures stay readable", async (t) => {
  const replies = [
    () => json({ error: "unrecognized upstream details" }, 502),
    () => new Response("not JSON", { status: 200 }),
    () => { throw new TypeError("Failed to fetch"); },
  ];
  t.mock.method(globalThis, "fetch", async () => replies.shift()());
  for (const expected of [
    "Внутренняя ошибка сервера", "Сервер вернул некорректный ответ",
    "Не удалось связаться с сервером. Проверьте подключение и повторите попытку.",
  ]) await assert.rejects(getAssistantForecastParameters(input), (error) => error.messageKey === expected);
});
