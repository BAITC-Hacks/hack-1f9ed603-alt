'use client';

import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { ChartNoAxesCombined, Check, ChevronDown, Database, Table2 } from "lucide-react";
import type { ForecastRunResponse } from "./api";
import { useLanguage } from "./i18n";
import "./ForecastResult.css";

function utcTime(value: string): string {
  return `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function ForecastResult({ run }: { run: ForecastRunResponse }) {
  const { t, locale, formatPower } = useLanguage();
  const [view, setView] = useState<"chart" | "table">("chart");
  const [selectedHour, setSelectedHour] = useState(0);
  const chartTab = useRef<HTMLButtonElement>(null);
  const tableTab = useRef<HTMLButtonElement>(null);
  const id = useId();
  const index = Math.min(selectedHour, run.points.length - 1);
  const point = run.points[index];
  const turbine = run.turbine_id === "turbine_1" ? t("Турбина 1") : t("Турбина 2");
  const horizon = run.horizon_hours === 24 ? t("24 часа") : t("48 часов");
  const pointCount = run.points.length === 24 ? t("24 почасовые точки") : t("48 почасовых точек");
  const powers = run.points.map((item) => item.normalized_power);
  const statistics = [
    { label: t("Среднее"), fullLabel: t("Средняя доля мощности"), value: powers.reduce((total, value) => total + value, 0) / powers.length },
    { label: t("Минимум"), fullLabel: t("Минимум за период"), value: Math.min(...powers) },
    { label: t("Максимум"), fullLabel: t("Максимум за период"), value: Math.max(...powers) },
  ];
  const chartWidth = 624;
  const chartHeight = 190;
  const chartLeft = 54;
  const chartTop = 16;
  const coordinates = run.points.map((item, hour) => ({
    x: chartLeft + (hour * chartWidth) / (run.points.length - 1),
    y: chartTop + (1 - item.normalized_power) * chartHeight,
  }));
  const line = coordinates.map(({ x, y }) => `${x},${y}`).join(" ");
  const position = coordinates[index];

  useEffect(() => {
    setSelectedHour(0);
    setView("chart");
  }, [run.run_id]);

  function switchTab(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "chart" : event.key === "End" ? "table" : view === "chart" ? "table" : "chart";
    setView(next);
    (next === "chart" ? chartTab : tableTab).current?.focus();
  }

  function inspectPoint(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 700;
    setSelectedHour(Math.max(0, Math.min(run.points.length - 1, Math.round(((x - chartLeft) / chartWidth) * (run.points.length - 1)))));
  }

  return (
    <section className="result-workspace" aria-labelledby={`${id}-title`}>
      <header className="result-header">
        <div>
          <p className="result-status"><Check size={13} aria-hidden="true" />{t("Прогноз готов")}</p>
          <h2 id={`${id}-title`}>{turbine} <span>· {horizon}</span></h2>
        </div>
        <div className="result-tabs" role="tablist" aria-label={t("Вид результата")} onKeyDown={switchTab}>
          <button type="button" id={`${id}-chart-tab`} ref={chartTab} role="tab" aria-selected={view === "chart"} aria-controls={`${id}-chart`} tabIndex={view === "chart" ? 0 : -1} onClick={() => setView("chart")}><ChartNoAxesCombined size={15} aria-hidden="true" />{t("График")}</button>
          <button type="button" id={`${id}-table-tab`} ref={tableTab} role="tab" aria-selected={view === "table"} aria-controls={`${id}-table`} tabIndex={view === "table" ? 0 : -1} onClick={() => setView("table")}><Table2 size={15} aria-hidden="true" />{t("Таблица")}</button>
        </div>
      </header>

      <dl className="result-statistics">
        {statistics.map(({ label, fullLabel, value }) => <div key={label}><dt title={fullLabel}>{label}</dt><dd>{value.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}<span> / 1</span></dd></div>)}
      </dl>

      <div id={`${id}-chart`} role="tabpanel" aria-labelledby={`${id}-chart-tab`} hidden={view !== "chart"} className="result-chart-panel">
        <div className="result-inspection">
          <div><p>{t("Доля мощности")}</p><output htmlFor={`${id}-hour`} className="result-selected-power">{formatPower(point.normalized_power)}<span> / 1</span></output></div>
          <div className="result-selected-time"><span>{t("Час")} {index + 1} / {run.horizon_hours}</span><time dateTime={point.time}>{utcTime(point.time)}</time></div>
        </div>
        <svg className="result-chart" viewBox="0 0 700 224" role="img" aria-label={`${turbine}: ${pointCount}, ${t("доля от 0 до 1")}`} onPointerMove={inspectPoint} onPointerDown={inspectPoint}>
          <defs><linearGradient id={`${id}-area`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity="0.2" /><stop offset="100%" stopColor="var(--accent)" stopOpacity="0.01" /></linearGradient></defs>
          {[1, 0.75, 0.5, 0.25, 0].map((level) => {
            const y = chartTop + (1 - level) * chartHeight;
            return <g key={level} className={level === 0.25 || level === 0.75 ? "result-quarter-tick" : undefined}><line className="result-grid-line" x1={chartLeft} x2={chartLeft + chartWidth} y1={y} y2={y} /><text className="result-axis-label" x={chartLeft - 10} y={y} dominantBaseline="middle" textAnchor="end">{level.toLocaleString(locale)}</text></g>;
          })}
          <polygon fill={`url(#${id}-area)`} points={`${chartLeft},${chartTop + chartHeight} ${line} ${chartLeft + chartWidth},${chartTop + chartHeight}`} />
          <polyline className="result-chart-line" points={line} />
          {coordinates.map(({ x, y }, hour) => <circle className="result-point" key={run.points[hour].time} cx={x} cy={y} r="2"><title>{utcTime(run.points[hour].time)}: {formatPower(run.points[hour].normalized_power)}</title></circle>)}
          <line className="result-inspection-line" x1={position.x} x2={position.x} y1={chartTop} y2={chartTop + chartHeight} />
          <circle className="result-selected-halo" cx={position.x} cy={position.y} r="9" />
          <circle className="result-selected-point" cx={position.x} cy={position.y} r="4" />
        </svg>
        <div className="result-chart-endpoints"><time dateTime={run.points[0].time}>{utcTime(run.points[0].time)}</time><time dateTime={run.points[run.points.length - 1].time}>{utcTime(run.points[run.points.length - 1].time)}</time></div>
        <div className="result-hour-control">
          <label htmlFor={`${id}-hour`}>{t("Выберите час")}<span>{String(index + 1).padStart(2, "0")} / {run.horizon_hours}</span></label>
          <input id={`${id}-hour`} type="range" min="0" max={run.points.length - 1} step="1" value={index} onChange={(event) => setSelectedHour(Number(event.target.value))} aria-valuetext={`${utcTime(point.time)}, ${t("Доля мощности")}: ${formatPower(point.normalized_power)}`} />
        </div>
      </div>

      <div id={`${id}-table`} role="tabpanel" aria-labelledby={`${id}-table-tab`} hidden={view !== "table"} className="result-table-panel">
        <div className="result-table-wrap" tabIndex={0} role="region" aria-label={t("Почасовые значения прогноза")}>
          <table className="result-table">
            <caption>{pointCount}</caption>
            <thead><tr><th scope="col">№</th><th scope="col">{t("Конец часа (UTC)")}</th><th scope="col">{t("Доля мощности (0–1)")}</th></tr></thead>
            <tbody>{run.points.map((item, hour) => <tr key={item.time}><td>{hour + 1}</td><td><time dateTime={item.time}>{utcTime(item.time)}</time></td><td>{formatPower(item.normalized_power)}</td></tr>)}</tbody>
          </table>
        </div>
      </div>

      <p className="result-unit-note">{t("Нормализованная активная мощность: доля от 0 до 1. Каждая точка относится к часу, заканчивающемуся в указанное время (UTC).")}</p>
      <details className="result-provenance">
        <summary><Database size={16} aria-hidden="true" /><span>{t("Источник и параметры запуска")}</span><ChevronDown className="result-disclosure-icon" size={17} aria-hidden="true" /></summary>
        <dl className="result-metadata">
          <div><dt>{t("Источник погоды")}</dt><dd>{run.weather_source}</dd></div>
          <div><dt>{t("Инициализация погодной модели")}</dt><dd><time dateTime={run.weather_run_initialized_at}>{utcTime(run.weather_run_initialized_at)}</time></dd></div>
          <div><dt>{t("Считается доступным после")}</dt><dd><time dateTime={run.weather_run_usable_after_at}>{utcTime(run.weather_run_usable_after_at)}</time></dd></div>
          <div><dt>{t("Фактическая публикация")}</dt><dd>{run.weather_actual_publication_at ? <time dateTime={run.weather_actual_publication_at}>{utcTime(run.weather_actual_publication_at)}</time> : t("Неизвестна")}</dd></div>
          <div><dt>{t("ID погодного выпуска")}</dt><dd>{run.weather_run_id}</dd></div>
          <div><dt>{t("Время запуска")}</dt><dd><time dateTime={run.issued_at}>{utcTime(run.issued_at)}</time></dd></div>
          <div><dt>{t("Данные доступны до")}</dt><dd><time dateTime={run.input_data_cutoff_at}>{utcTime(run.input_data_cutoff_at)}</time></dd></div>
          <div><dt>{t("Версия модели")}</dt><dd>{run.model_version}</dd></div>
          <div><dt>{t("ID расчёта")}</dt><dd>{run.run_id}</dd></div>
        </dl>
        <p className="result-source-note">{t("Порог доступности рассчитан как 12 часов после инициализации модели. Архив не сообщает точное время публикации выпуска.")}</p>
      </details>
    </section>
  );
}
