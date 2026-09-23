"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowRight, Check, CircleHelp, Clock3, Database, LoaderCircle, Radio, SlidersHorizontal, Sparkles, Wind, X } from "lucide-react";
import { LanguageSwitcher, useLanguage } from "./i18n";
import type { Translate } from "./messages";
import { AssistantPanel } from "./AssistantPanel";
import { ForecastResult } from "./ForecastResult";
import { ApiError, createForecastRun, getHealth, getTurbines, type ForecastRunResponse, type TurbineSummary } from "./api";

type LoadState = "loading" | "ready" | "error";
type RunState = "idle" | "loading" | "ready" | "error";
const DEMO_ISSUED_AT = "2026-02-01T12:00:00Z";

function validateIssuedAt(value: string, t: Translate): string {
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!parts || !Number.isFinite(Date.parse(value))) {
    return t("Введите время в ISO 8601 с часовым поясом, например 2026-02-01T12:00:00Z");
  }
  const [, year, month, day, hour, minute, second = "0"] = parts;
  const calendarDay = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (calendarDay.getUTCFullYear() !== Number(year) || calendarDay.getUTCMonth() + 1 !== Number(month) ||
      calendarDay.getUTCDate() !== Number(day) || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59) {
    return t("Укажите существующую дату и время");
  }
  if (Date.parse(value) % 3_600_000 !== 0) {
    return t("Запуск должен приходиться на начало часа по UTC");
  }
  return "";
}


function turbineName(id: TurbineSummary["id"], t: Translate): string {
  return id === "turbine_1" ? t("Турбина 1") : t("Турбина 2");
}

function DataDialog({ turbines, open, onClose }: { turbines: TurbineSummary[]; open: boolean; onClose: () => void }) {
  const { t, locale } = useLanguage();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current?.close();
  }, [open]);
  return (
    <dialog className="data-dialog" ref={dialog} onClose={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} aria-labelledby="data-title">
      <div className="dialog-header"><div><p className="eyebrow">HackAlem AI</p><h2 id="data-title">{t("Исходные данные")}</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label={t("Закрыть")}><X size={20} /></button></div>
      <div className="source-cards">
        {turbines.map((turbine) => (
          <article className="source-card" key={turbine.id}>
            <h3><Wind size={18} aria-hidden="true" />{turbineName(turbine.id, t)}</h3>
            <p className="source-count">{turbine.rows.toLocaleString(locale)}</p><p className="muted">{t("наблюдений с шагом 10 минут")}</p>
            <dl><div><dt>{t("Период наблюдений")}</dt><dd><time dateTime={turbine.first_observation}>{turbine.first_observation.replace("T", " ")}</time><span> — </span><time dateTime={turbine.last_observation}>{turbine.last_observation.replace("T", " ")}</time></dd></div><div><dt>{t("Пропущено интервалов")}</dt><dd>{turbine.missing_intervals.toLocaleString(locale)}</dd></div></dl>
          </article>
        ))}
      </div>
      <p className="source-note"><Clock3 size={17} aria-hidden="true" />{t("Часовой пояс исходных наблюдений не подтверждён.")}</p>
      <div className="method-note"><h3>{t("Как это работает")}</h3><p>{t("Модель преобразует погодный прогноз в почасовую долю мощности. Вы выбираете турбину, момент запуска и горизонт расчёта.")}</p><p>{t("Порог доступности рассчитан как 12 часов после инициализации модели. Архив не сообщает точное время публикации выпуска.")}</p></div>
    </dialog>
  );
}

export function App() {
  const { t, locale } = useLanguage();
  const [setupMode, setSetupMode] = useState<"manual" | "assistant">("manual");
  const manualTab = useRef<HTMLButtonElement>(null);
  const assistantTab = useRef<HTMLButtonElement>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [turbines, setTurbines] = useState<TurbineSummary[]>([]);
  const [selected, setSelected] = useState<TurbineSummary["id"]>("turbine_1");
  const [horizon, setHorizon] = useState<24 | 48>(48);
  const [issuedAt, setIssuedAt] = useState(DEMO_ISSUED_AT);
  const [timeTouched, setTimeTouched] = useState(false);
  const [runError, setRunError] = useState<ApiError | null>(null);
  const [runState, setRunState] = useState<RunState>("idle");
  const [run, setRun] = useState<ForecastRunResponse | null>(null);
  const [dataOpen, setDataOpen] = useState(false);
  const timeError = timeTouched ? validateIssuedAt(issuedAt, t) : "";
  const selectedTurbine = turbines.find((turbine) => turbine.id === selected);
  const changed = run && (run.turbine_id !== selected || run.horizon_hours !== horizon || Date.parse(run.issued_at) !== Date.parse(issuedAt));

  function switchSetupMode(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "manual" : event.key === "End" ? "assistant" : setupMode === "manual" ? "assistant" : "manual";
    setSetupMode(next);
    (next === "manual" ? manualTab : assistantTab).current?.focus();
  }

  async function load() {
    setLoadState("loading");
    setLoadError(null);
    try {
      await getHealth();
      const result = await getTurbines();
      setTurbines(result.turbines);
      if (result.turbines.length && !result.turbines.some((turbine) => turbine.id === selected)) setSelected(result.turbines[0].id);
      setLoadState("ready");
    } catch (error) {
      setLoadError(error instanceof ApiError ? error : new ApiError("Не удалось загрузить данные"));
      setLoadState("error");
    }
  }

  useEffect(() => { void load(); }, []);

  async function submit() {
    setTimeTouched(true);
    if (validateIssuedAt(issuedAt, t)) return;
    setRun(null);
    setRunState("loading");
    setRunError(null);
    try {
      const result = await createForecastRun({ turbine_id: selected, issued_at: issuedAt, horizon_hours: horizon });
      setRun(result);
      setRunState("ready");
    } catch (error) {
      setRunError(error instanceof ApiError ? error : new ApiError("Не удалось создать прогноз"));
      setRunState("error");
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#forecast-title">{t("Перейти к запуску прогноза")}</a>
      <header className="app-header">
        <div className="brand"><span className="brand-symbol"><Wind size={24} aria-hidden="true" /></span><span>HackAlem<span className="brand-ai"> AI</span></span><span className="brand-divider" /><span className="brand-context">{t("Энергия ветра")}</span></div>
        <div className="header-tools"><button type="button" className="data-button" aria-label={t("Данные")} onClick={() => setDataOpen(true)} disabled={loadState !== "ready" || !turbines.length}><Database size={16} aria-hidden="true" /><span>{t("Данные")}</span></button><LanguageSwitcher /></div>
      </header>

      <main className="workspace">
        <div className="workspace-heading"><div><p className="eyebrow">{t("Прогноз мощности")}</p><h1>{t("Ветер под наблюдением.")}</h1></div><div className={`connection-status ${loadState}`} role="status"><span />{loadState === "ready" ? t("API подключён") : loadState === "loading" ? t("Загрузка данных…") : t("Нет подключения")}</div></div>
        <div className="workspace-grid">
          <section className="control-panel" aria-labelledby="forecast-title">
            <div className="panel-heading"><SlidersHorizontal size={17} aria-hidden="true" /><h2 id="forecast-title" tabIndex={-1}>{t("Параметры прогноза")}</h2></div>
            <div className="setup-modes" role="tablist" aria-label={t("Способ ввода")} onKeyDown={switchSetupMode}>
              <button type="button" id="setup-manual-tab" ref={manualTab} role="tab" aria-selected={setupMode === "manual"} aria-controls="setup-manual-panel" tabIndex={setupMode === "manual" ? 0 : -1} onClick={() => setSetupMode("manual")}><SlidersHorizontal size={14} aria-hidden="true" />{t("Вручную")}</button>
              <button type="button" id="setup-assistant-tab" ref={assistantTab} role="tab" aria-selected={setupMode === "assistant"} aria-controls="setup-assistant-panel" tabIndex={setupMode === "assistant" ? 0 : -1} onClick={() => setSetupMode("assistant")}><Sparkles size={14} aria-hidden="true" />{t("Спросить ИИ")}</button>
            </div>
            <div id="setup-manual-panel" role="tabpanel" aria-labelledby="setup-manual-tab" hidden={setupMode !== "manual"}>
              <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
                <fieldset disabled={runState === "loading"}>
                  <legend className="sr-only">{t("Параметры прогноза")}</legend>
                  <div className="control-section"><p className="control-label" id="turbine-label"><span>01</span>{t("Турбина")}</p>
                    <div className="turbine-picker" role="group" aria-labelledby="turbine-label">
                      {(["turbine_1", "turbine_2"] as const).map((id, index) => (
                        <button type="button" className={`turbine-option ${selected === id ? "selected" : ""}`} aria-pressed={selected === id} key={id} onClick={() => setSelected(id)} disabled={loadState !== "ready" || !turbines.some((turbine) => turbine.id === id)}>
                          <img src={index === 0 ? "/images/wind-sunset.jpg" : "/images/wind-dusk.jpg"} alt="" width="160" height="120" />
                          <span className="turbine-check">{selected === id ? <Check size={13} aria-hidden="true" /> : <Wind size={13} aria-hidden="true" />}</span>
                          <span className="turbine-name">{turbineName(id, t)}</span>
                        </button>
                      ))}
                    </div>
                    {selectedTurbine && <p className="observation-caption"><Database size={12} aria-hidden="true" /><strong>{selectedTurbine.rows.toLocaleString(locale)}</strong> {t("наблюдений")}</p>}
                  </div>
                  <div className="control-section"><label className="control-label" htmlFor="issued-at"><span>02</span>{t("Время запуска")}</label>
                    <input id="issued-at" value={issuedAt} onChange={(event) => setIssuedAt(event.target.value)} onBlur={() => setTimeTouched(true)} placeholder={DEMO_ISSUED_AT} aria-label={t("Время запуска в ISO 8601 с часовым поясом")} aria-invalid={Boolean(timeError)} aria-describedby={timeError ? "issued-at-error" : "time-hint"} />
                    {timeError ? <p className="field-error" id="issued-at-error" role="alert">{timeError}</p> : <p id="time-hint" className="field-hint">{t("Исторический запуск · ISO 8601")}</p>}
                  </div>
                  <div className="control-section"><p className="control-label" id="horizon-label"><span>03</span>{t("Горизонт")}</p><div className="horizon-picker" role="group" aria-labelledby="horizon-label">{([24, 48] as const).map((hours) => <button type="button" key={hours} aria-pressed={horizon === hours} onClick={() => setHorizon(hours)}>{t(hours === 24 ? "24 часа" : "48 часов")}</button>)}</div></div>
                  <button className="run-button" type="submit" disabled={loadState !== "ready" || !selectedTurbine || runState === "loading"}>{runState === "loading" ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Wind size={18} aria-hidden="true" />}<span>{runState === "loading" ? t("Запуск…") : t("Построить прогноз")}</span>{runState !== "loading" && <ArrowRight size={17} aria-hidden="true" />}</button>
                </fieldset>
              </form>
              {loadState === "error" && <div className="load-error" role="alert"><p>{loadError && t(loadError.messageKey)}{loadError?.status && ` (HTTP ${loadError.status})`}</p><button type="button" className="text-button" onClick={() => void load()}>{t("Повторить")}</button></div>}
              {loadState === "ready" && !turbines.length && <p className="load-error">{t("Файлы турбин не найдены.")}</p>}
              <p className="control-footnote"><CircleHelp size={14} aria-hidden="true" />{t("Результат — доля мощности от 0 до 1.")}</p>
            </div>
            <div id="setup-assistant-panel" role="tabpanel" aria-labelledby="setup-assistant-tab" hidden={setupMode !== "assistant"}>
              <AssistantPanel request={{ turbine_id: selected, issued_at: issuedAt, horizon_hours: horizon }} run={run && !changed ? run : null} />
            </div>
          </section>

          <section className="forecast-workspace" aria-label={t("Результат расчёта")} aria-busy={runState === "loading"}>
            {runState === "ready" && run ? <>{changed && <p className="draft-notice" role="status"><SlidersHorizontal size={14} aria-hidden="true" />{t("Параметры изменены. Запустите новый расчёт.")}</p>}<ForecastResult key={run.run_id} run={run} /></> : (
              <div className={`forecast-stage ${runState === "loading" ? "is-loading" : ""}`}>
                <img className="stage-image" src="/images/wind-dusk.jpg" alt={t("Ряд ветрогенераторов на фоне сумеречного неба")} width="800" height="500" />
                <div className="stage-top"><span><Radio size={15} aria-hidden="true" />{t("Рабочая область")}</span><span>{turbineName(selected, t)} <span className="stage-dot">·</span> {t(horizon === 24 ? "24 часа" : "48 часов")}</span></div>
                <div className="stage-content">
                  {runState === "loading" ? <><span className="stage-emblem"><LoaderCircle className="spin" size={30} aria-hidden="true" /></span><h2>{t("Считаем следующий час.")}</h2><p role="status">{t("Получаем почасовой прогноз…")}</p></> : runState === "error" ? <><span className="stage-emblem"><CircleHelp size={28} aria-hidden="true" /></span><h2>{t("Расчёт недоступен.")}</h2><p className="stage-error" role="alert">{runError && t(runError.messageKey)}{runError?.status && ` (HTTP ${runError.status})`}</p><p>{t("Проверьте параметры и повторите запуск.")}</p></> : <><span className="stage-emblem"><Wind size={30} aria-hidden="true" /></span><h2>{t("От ветра")}<br /><span>{t("к решению.")}</span></h2><p>{t("Выберите турбину и запустите расчёт. Здесь появится почасовая картина мощности.")}</p></>}
                </div>
                <div className="stage-bottom"><span>{t("Архивная погода")}</span><span>{t("Почасовой шаг")} <span className="stage-dot">/</span> UTC</span></div>
              </div>
            )}
          </section>
        </div>
        <footer className="workspace-footer"><span>HackAlem AI <span className="footer-separator">/</span> {t("Прогноз мощности")}</span><span>{t("Реальные данные. Проверяемый результат.")}</span></footer>
      </main>
      <DataDialog turbines={turbines} open={dataOpen} onClose={() => setDataOpen(false)} />
    </div>
  );
}
