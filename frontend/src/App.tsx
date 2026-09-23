import { useEffect, useState } from "react";
import {
  createForecastRun,
  getHealth,
  getTurbines,
  type ForecastRunResponse,
  type TurbineSummary,
} from "./api";

type LoadState = "loading" | "ready" | "error";
type RunState = "idle" | "loading" | "ready" | "error";
const DEMO_ISSUED_AT = "2026-02-01T12:00:00Z";

function validateIssuedAt(value: string): string {
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!parts || !Number.isFinite(Date.parse(value))) {
    return "Введите время в ISO 8601 с часовым поясом, например 2026-02-01T12:00:00Z";
  }
  const [, year, month, day, hour, minute, second = "0"] = parts;
  const calendarDay = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (calendarDay.getUTCFullYear() !== Number(year) || calendarDay.getUTCMonth() + 1 !== Number(month) ||
      calendarDay.getUTCDate() !== Number(day) || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59) {
    return "Укажите существующую дату и время";
  }
  if (Date.parse(value) % 3_600_000 !== 0) {
    return "Запуск должен приходиться на начало часа по UTC";
  }
  return "";
}

function formatTime(value: string): string {
  return value.replace("T", " ");
}

function formatUtcTime(value: string): string {
  return `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function turbineName(id: TurbineSummary["id"]): string {
  return id === "turbine_1" ? "Турбина 1" : "Турбина 2";
}

function ForecastResult({ run }: { run: ForecastRunResponse }) {
  const horizonLabel = run.horizon_hours === 24 ? "24 часа" : "48 часов";
  const pointCountLabel = run.points.length === 24 ? "24 почасовые точки" : "48 почасовых точек";
  const chartWidth = 688;
  const chartHeight = 164;
  const chartLeft = 48;
  const chartTop = 18;
  const coordinates = run.points.map((point, index) => ({
    x: chartLeft + (index * chartWidth) / (run.points.length - 1),
    y: chartTop + (1 - point.normalized_power) * chartHeight,
  }));
  const line = coordinates.map(({ x, y }) => `${x},${y}`).join(" ");

  return (
    <section className="panel result-panel" aria-labelledby="result-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Результат расчёта</p>
          <h2 id="result-title">{turbineName(run.turbine_id)} · {horizonLabel}</h2>
        </div>
        <span className="badge">{pointCountLabel}</span>
      </div>
      <p className="result-note">Нормализованная активная мощность — доля от 0 до 1. Каждая точка относится к часу, заканчивающемуся в указанное время (UTC).</p>

      <div className="chart-wrap">
        <svg className="forecast-chart" viewBox="0 0 760 212" role="img" aria-label={`${turbineName(run.turbine_id)}: ${pointCountLabel}, доля от 0 до 1`}>
          {[1, 0.5, 0].map((level) => {
            const y = chartTop + (1 - level) * chartHeight;
            return (
              <g key={level}>
                <line className="chart-grid" x1={chartLeft} x2={chartLeft + chartWidth} y1={y} y2={y} />
                <text className="chart-label" x={chartLeft - 12} y={y + 4} textAnchor="end">{level.toFixed(1)}</text>
              </g>
            );
          })}
          <polyline className="chart-line" points={line} />
          {coordinates.map(({ x, y }, index) => (
            <circle className="chart-point" key={run.points[index].time} cx={x} cy={y} r="3" />
          ))}
          <text className="chart-label" x={chartLeft} y="207">{formatUtcTime(run.points[0].time)}</text>
          <text className="chart-label" x={chartLeft + chartWidth} y="207" textAnchor="end">{formatUtcTime(run.points[run.points.length - 1].time)}</text>
        </svg>
      </div>

      <h3>Источник и параметры запуска</h3>
      <dl className="metadata-grid">
        <div><dt>Источник погоды</dt><dd>{run.weather_source}</dd></div>
        <div><dt>Время погодного цикла</dt><dd><time dateTime={run.weather_run_issued_at}>{formatUtcTime(run.weather_run_issued_at)}</time></dd></div>
        <div><dt>ID погодного выпуска</dt><dd className="code-value">{run.weather_run_id}</dd></div>
        <div><dt>Время запуска</dt><dd><time dateTime={run.issued_at}>{formatUtcTime(run.issued_at)}</time></dd></div>
        <div><dt>Данные доступны до</dt><dd><time dateTime={run.input_data_cutoff_at}>{formatUtcTime(run.input_data_cutoff_at)}</time></dd></div>
        <div><dt>Версия модели</dt><dd className="code-value">{run.model_version}</dd></div>
        <div><dt>ID расчёта</dt><dd className="code-value">{run.run_id}</dd></div>
      </dl>
      <p className="result-note">Время погодного цикла не подтверждает точное время публикации архивного прогноза.</p>

      <h3>Почасовые значения</h3>
      <div className="table-wrap">
        <table className="forecast-table">
          <thead><tr><th scope="col">№</th><th scope="col">Конец часа (UTC)</th><th scope="col">Доля мощности (0–1)</th></tr></thead>
          <tbody>
            {run.points.map((point, index) => (
              <tr key={point.time}>
                <td>{index + 1}</td>
                <td><time dateTime={point.time}>{formatUtcTime(point.time)}</time></td>
                <td>{point.normalized_power.toString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function App() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState("");
  const [turbines, setTurbines] = useState<TurbineSummary[]>([]);
  const [selected, setSelected] = useState<TurbineSummary["id"]>("turbine_1");
  const [horizon, setHorizon] = useState<24 | 48>(48);
  const [issuedAt, setIssuedAt] = useState(DEMO_ISSUED_AT);
  const [timeTouched, setTimeTouched] = useState(false);
  const [runError, setRunError] = useState("");
  const [runState, setRunState] = useState<RunState>("idle");
  const [run, setRun] = useState<ForecastRunResponse | null>(null);
  const timeError = timeTouched ? validateIssuedAt(issuedAt) : "";

  async function load() {
    setLoadState("loading");
    setLoadError("");
    try {
      await getHealth();
      const result = await getTurbines();
      setTurbines(result.turbines);
      setLoadState("ready");
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Не удалось загрузить данные");
      setLoadState("error");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function submit() {
    setTimeTouched(true);
    if (validateIssuedAt(issuedAt)) {
      setRun(null);
      setRunState("idle");
      setRunError("");
      return;
    }
    setRun(null);
    setRunState("loading");
    setRunError("");
    try {
      const result = await createForecastRun({
        turbine_id: selected,
        issued_at: issuedAt,
        horizon_hours: horizon,
      });
      setRun(result);
      setRunState("ready");
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Не удалось создать прогноз");
      setRunState("error");
    }
  }

  return (
    <main className="page">
      <header className="hero">
        <p className="eyebrow">HackAlem AI · почасовой прогноз</p>
        <h1>Прогноз выработки ВЭС</h1>
        <p>Выберите турбину и горизонт 24 или 48 часов. Прогноз строится по данным выбранного исторического запуска.</p>
      </header>

      <section className="panel" aria-labelledby="data-title">
        <div className="section-heading">
          <h2 id="data-title">Исходные данные</h2>
          {loadState === "ready" && <span className="badge">API подключён</span>}
        </div>
        {loadState === "loading" && <p>Загрузка данных…</p>}
        {loadState === "error" && (
          <div role="alert">
            <p className="error">{loadError}</p>
            <button type="button" onClick={() => void load()}>Повторить</button>
          </div>
        )}
        {loadState === "ready" && turbines.length === 0 && <p>Файлы турбин не найдены.</p>}
        {loadState === "ready" && turbines.length > 0 && (
          <div className="cards">
            {turbines.map((turbine) => (
              <article className="card" key={turbine.id}>
                <h3>{turbine.id === "turbine_1" ? "Турбина 1" : "Турбина 2"}</h3>
                <p><strong>{turbine.rows.toLocaleString("ru-RU")}</strong> наблюдений</p>
                <p>Период: {formatTime(turbine.first_observation)} — {formatTime(turbine.last_observation)}</p>
                <p>Пропущено десятиминутных интервалов: {turbine.missing_intervals.toLocaleString("ru-RU")}</p>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="panel" aria-labelledby="forecast-title">
        <h2 id="forecast-title">Запуск прогноза</h2>
        <p>Укажите момент запуска с часовым поясом. Результат появится после успешного ответа API.</p>
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="issued-at">Время запуска</label>
            <input
              id="issued-at"
              value={issuedAt}
              onChange={(event) => setIssuedAt(event.target.value)}
              onBlur={() => setTimeTouched(true)}
              placeholder={DEMO_ISSUED_AT}
              aria-label="Время запуска в ISO 8601 с часовым поясом"
              aria-invalid={Boolean(timeError)}
              aria-describedby={timeError ? "issued-at-error" : undefined}
            />
            {timeError && <p className="field-error" id="issued-at-error" role="alert">{timeError}</p>}
          </div>
          <label>Турбина
            <select value={selected} onChange={(event) => setSelected(event.target.value as TurbineSummary["id"])}>
              <option value="turbine_1">Турбина 1</option>
              <option value="turbine_2">Турбина 2</option>
            </select>
          </label>
          <label>Горизонт
            <select value={horizon} onChange={(event) => setHorizon(Number(event.target.value) as 24 | 48)}>
              <option value={24}>24 часа</option>
              <option value={48}>48 часов</option>
            </select>
          </label>
          <button type="button" disabled={loadState !== "ready" || runState === "loading"} onClick={() => void submit()}>
            {runState === "loading" ? "Запуск…" : "Запустить"}
          </button>
        </div>
        {runState === "idle" && !timeError && <p className="result-note" role="status">Прогноз ещё не запущен.</p>}
        {runState === "loading" && <p className="result-note" role="status">Получаем почасовой прогноз…</p>}
        {runState === "error" && <p className="error" role="alert">{runError}</p>}
      </section>
      {runState === "ready" && run && <ForecastResult run={run} />}
    </main>
  );
}
