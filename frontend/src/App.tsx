import { useEffect, useState } from "react";
import { ArrowRight, ChartLine, Clock, Database, Wind } from "@phosphor-icons/react";
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
  const powers = run.points.map((point) => point.normalized_power);
  const statistics = [
    { label: "Средняя доля мощности", value: powers.reduce((sum, value) => sum + value, 0) / powers.length },
    { label: "Минимум за период", value: Math.min(...powers) },
    { label: "Максимум за период", value: Math.max(...powers) },
  ];

  return (
    <section className="panel result-panel" aria-labelledby="result-title">
      <div className="section-heading">
        <div>
          <p className="result-kicker"><ChartLine size={18} aria-hidden="true" /> Результат расчёта</p>
          <h2 id="result-title">{turbineName(run.turbine_id)} · {horizonLabel}</h2>
        </div>
        <span className="badge">{pointCountLabel}</span>
      </div>
      <p className="result-note">Нормализованная активная мощность: доля от 0 до 1. Каждая точка относится к часу, заканчивающемуся в указанное время (UTC).</p>
      <dl className="forecast-stats">
        {statistics.map(({ label, value }) => (
          <div key={label}><dt>{label}</dt><dd>{value.toLocaleString("ru-RU", { minimumFractionDigits: 3, maximumFractionDigits: 3 })}<span> / 1</span></dd></div>
        ))}
      </dl>

      <div className="chart-wrap" tabIndex={0} role="region" aria-label="График почасового прогноза">
        <svg className="forecast-chart" viewBox="0 0 760 212" role="img" aria-label={`${turbineName(run.turbine_id)}: ${pointCountLabel}, доля от 0 до 1`}>
          {[1, 0.75, 0.5, 0.25, 0].map((level) => {
            const y = chartTop + (1 - level) * chartHeight;
            return (
              <g key={level}>
                <line className="chart-grid" x1={chartLeft} x2={chartLeft + chartWidth} y1={y} y2={y} />
                <text className="chart-label" x={chartLeft - 12} y={y + 4} textAnchor="end">{level.toLocaleString("ru-RU")}</text>
              </g>
            );
          })}
          <polygon className="chart-area" points={`${chartLeft},${chartTop + chartHeight} ${line} ${chartLeft + chartWidth},${chartTop + chartHeight}`} />
          <polyline className="chart-line" points={line} />
          {coordinates.map(({ x, y }, index) => (
            <circle className="chart-point" key={run.points[index].time} cx={x} cy={y} r="3">
              <title>{formatUtcTime(run.points[index].time)}: {run.points[index].normalized_power}</title>
            </circle>
          ))}
          <text className="chart-label" x={chartLeft} y="207">{formatUtcTime(run.points[0].time)}</text>
          <text className="chart-label" x={chartLeft + chartWidth} y="207" textAnchor="end">{formatUtcTime(run.points[run.points.length - 1].time)}</text>
        </svg>
      </div>

      <h3>Источник и параметры запуска</h3>
      <dl className="metadata-grid">
        <div><dt>Источник погоды</dt><dd>{run.weather_source}</dd></div>
        <div><dt>Инициализация погодной модели</dt><dd><time dateTime={run.weather_run_initialized_at}>{formatUtcTime(run.weather_run_initialized_at)}</time></dd></div>
        <div><dt>Считается доступным после</dt><dd><time dateTime={run.weather_run_usable_after_at}>{formatUtcTime(run.weather_run_usable_after_at)}</time></dd></div>
        <div><dt>Фактическая публикация</dt><dd>{run.weather_actual_publication_at ? formatUtcTime(run.weather_actual_publication_at) : "Неизвестна"}</dd></div>
        <div><dt>ID погодного выпуска</dt><dd className="code-value">{run.weather_run_id}</dd></div>
        <div><dt>Время запуска</dt><dd><time dateTime={run.issued_at}>{formatUtcTime(run.issued_at)}</time></dd></div>
        <div><dt>Данные доступны до</dt><dd><time dateTime={run.input_data_cutoff_at}>{formatUtcTime(run.input_data_cutoff_at)}</time></dd></div>
        <div><dt>Версия модели</dt><dd className="code-value">{run.model_version}</dd></div>
        <div><dt>ID расчёта</dt><dd className="code-value">{run.run_id}</dd></div>
      </dl>
      <p className="result-note">Порог доступности рассчитан как 12 часов после инициализации модели. Архив не сообщает точное время публикации выпуска.</p>

      <h3>Почасовые значения</h3>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Почасовые значения прогноза">
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
      <a className="skip-link" href="#forecast-title">Перейти к запуску прогноза</a>
      <header className="hero">
        <div className="brandline"><span className="brand-mark"><Wind size={24} weight="regular" aria-hidden="true" /></span><span>HackAlem AI <span className="brand-divider">/</span> Ветроэнергетика</span></div>
        <h1>Прогноз выработки ВЭС</h1>
        <p>Выберите турбину и горизонт 24 или 48 часов. Прогноз строится по данным выбранного исторического запуска.</p>
      </header>

      <section className="data-section" aria-labelledby="data-title">
        <div className="section-heading">
          <h2 id="data-title"><Database size={20} aria-hidden="true" />Исходные данные</h2>
          {loadState === "ready" && <span className="connection-status"><span aria-hidden="true" />API подключён</span>}
        </div>
        {loadState === "loading" && <div className="data-loading" role="status"><p>Загрузка данных…</p><div className="loading-track" aria-hidden="true" /></div>}
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
                <div className="card-top"><h3>{turbineName(turbine.id)}</h3><Wind size={28} aria-hidden="true" /></div>
                <p className="observation-count"><strong>{turbine.rows.toLocaleString("ru-RU")}</strong><span>наблюдений с шагом 10 минут</span></p>
                <dl className="data-details">
                  <div><dt>Период наблюдений</dt><dd><time dateTime={turbine.first_observation}>{formatTime(turbine.first_observation)}</time><span className="date-separator"> → </span><time dateTime={turbine.last_observation}>{formatTime(turbine.last_observation)}</time></dd></div>
                  <div className="missing-row"><dt>Пропущено интервалов</dt><dd>{turbine.missing_intervals.toLocaleString("ru-RU")}</dd></div>
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="panel launch-panel" aria-labelledby="forecast-title" aria-busy={runState === "loading"}>
        <h2 id="forecast-title" tabIndex={-1}><ChartLine size={22} aria-hidden="true" />Запуск прогноза</h2>
        <p className="launch-description">Укажите момент запуска с часовым поясом и выберите горизонт расчёта.</p>
        <form className="form-row" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <div className="form-field">
            <label htmlFor="issued-at">Время запуска</label>
            <input
              id="issued-at"
              value={issuedAt}
              disabled={runState === "loading"}
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
            <select value={selected} disabled={runState === "loading"} onChange={(event) => setSelected(event.target.value as TurbineSummary["id"])}>
              <option value="turbine_1">Турбина 1</option>
              <option value="turbine_2">Турбина 2</option>
            </select>
          </label>
          <label>Горизонт
            <select value={horizon} disabled={runState === "loading"} onChange={(event) => setHorizon(Number(event.target.value) as 24 | 48)}>
              <option value={24}>24 часа</option>
              <option value={48}>48 часов</option>
            </select>
          </label>
          <button type="submit" disabled={loadState !== "ready" || turbines.length === 0 || runState === "loading"}>
            {runState === "loading" ? "Запуск…" : "Запустить"}<ArrowRight size={18} aria-hidden="true" />
          </button>
        </form>
        {runState === "idle" && !timeError && <p className="launch-status" role="status"><Clock size={16} aria-hidden="true" />Прогноз ещё не запущен. Выберите параметры и начните расчёт.</p>}
        {runState === "loading" && <div role="status"><p className="launch-status">Получаем почасовой прогноз…</p><div className="loading-track" aria-hidden="true" /></div>}
        {runState === "error" && <p className="error" role="alert">{runError}</p>}
      </section>
      {runState === "ready" && run && <ForecastResult run={run} />}
    </main>
  );
}
