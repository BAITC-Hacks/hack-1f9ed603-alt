import { useEffect, useState } from "react";
import { createForecastRun, getHealth, getTurbines, type TurbineSummary } from "./api";

type LoadState = "loading" | "ready" | "error";

function formatTime(value: string): string {
  return value.replace("T", " ");
}

export function App() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState("");
  const [turbines, setTurbines] = useState<TurbineSummary[]>([]);
  const [selected, setSelected] = useState<TurbineSummary["id"]>("turbine_1");
  const [horizon, setHorizon] = useState<24 | 48>(48);
  const [issuedAt, setIssuedAt] = useState("");
  const [runError, setRunError] = useState("");
  const [submitting, setSubmitting] = useState(false);

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
    if (!/(Z|[+-]\d{2}:\d{2})$/.test(issuedAt) || Number.isNaN(Date.parse(issuedAt))) {
      setRunError("Введите время запуска в ISO 8601 с часовым поясом");
      return;
    }
    setSubmitting(true);
    setRunError("");
    try {
      await createForecastRun({
        turbine_id: selected,
        issued_at: issuedAt,
        horizon_hours: horizon,
      });
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Не удалось создать прогноз");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <header className="hero">
        <p className="eyebrow">HackAlem AI · каркас проекта</p>
        <h1>Прогноз выработки ВЭС</h1>
        <p>Две турбины, почасовой горизонт 24–48 часов. Интерфейс показывает реальные данные из CSV и состояние подключения прогнозной модели.</p>
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
        <p>Укажите исторический момент запуска и его часовой пояс. Пока модель и архивный погодный источник не подключены, сервер вернёт явную ошибку.</p>
        <div className="form-row">
          <label>Время запуска
            <input
              value={issuedAt}
              onChange={(event) => setIssuedAt(event.target.value)}
              placeholder="2026-01-31T00:00:00+05:00"
              aria-label="Время запуска в ISO 8601 с часовым поясом"
            />
          </label>
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
          <button type="button" disabled={loadState !== "ready" || submitting} onClick={() => void submit()}>
            {submitting ? "Запуск…" : "Запустить"}
          </button>
        </div>
        {runError && <p className="error" role="alert">{runError}</p>}
      </section>
    </main>
  );
}
