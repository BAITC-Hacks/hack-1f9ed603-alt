"use client";

import { useId, useState, type FormEvent } from "react";
import { LoaderCircle, MessageSquare, Send, Sparkles } from "lucide-react";
import type { ApiError, ForecastRunRequest, ForecastRunResponse } from "./api";
import { useLanguage } from "./i18n";
import "./AssistantPanel.css";

export type AssistantFeedback = { question: string } & (
  | { status: "clarification"; message: string }
  | { status: "ready"; request: ForecastRunRequest }
  | { status: "error"; error: ApiError }
);

type AssistantPanelProps = {
  request: ForecastRunRequest;
  defaultTimeFallback: boolean;
  run: ForecastRunResponse | null;
  busy: boolean;
  interpreting: boolean;
  disabled: boolean;
  feedback: AssistantFeedback | null;
  onSubmit: (message: string) => Promise<void>;
};

export function AssistantPanel({ request, defaultTimeFallback, run, busy, interpreting, disabled, feedback, onSubmit }: AssistantPanelProps) {
  const { t, locale } = useLanguage();
  const id = useId();
  const [draft, setDraft] = useState("");
  const hasResult = run !== null && run.turbine_id === request.turbine_id &&
    run.horizon_hours === request.horizon_hours && Date.parse(run.issued_at) === Date.parse(request.issued_at);

  function contextLabel(context: ForecastRunRequest) {
    return `${t(context.turbine_id === "turbine_1" ? "Турбина 1" : "Турбина 2")} · ${t(context.horizon_hours === 24 ? "24 часа" : "48 часов")}`;
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || busy || disabled) return;
    // Preserve the draft so errors and clarification can be corrected in place.
    void onSubmit(question);
  }

  return (
    <div className="assistant-panel" aria-busy={busy}>
      <div className="assistant-context" aria-label={t("Контекст запроса")}>
        <p><Sparkles size={14} aria-hidden="true" /><span>{contextLabel(request)}</span></p>
        <span className="assistant-timestamp">{request.issued_at}</span>
        <span className="assistant-context-note">{hasResult ? t("Результат прогноза выбран") : t("Параметры из ручного ввода")}</span>
        {defaultTimeFallback && <span className="assistant-context-note">{t("В ручном вводе некорректная дата. В контексте сохранена последняя корректная дата; укажите новую в запросе.")}</span>}
      </div>

      <div className="assistant-help" id={`${id}-help`}><span className="assistant-help-badge">{t("Ввод с ИИ")}</span><p>{t("Опишите дату, время, турбину и горизонт. ИИ заполнит параметры и запустит расчёт той же прогнозной модели.")}</p><p>{t("Часы сохраняются без сдвига. Если турбина или горизонт не указаны, используются выбранные значения.")}</p></div>

      <form className="assistant-form" onSubmit={submit}>
        <label htmlFor={`${id}-question`}>{t("Запрос для прогноза")}</label>
        <textarea id={`${id}-question`} value={draft} onChange={(event) => setDraft(event.target.value)} disabled={busy} maxLength={4000} rows={5} placeholder={t("Например: 22 февраля 17:00 2026 года")} aria-describedby={`${id}-limit ${id}-help`} />
        <div className="assistant-input-meta" id={`${id}-limit`}><span>{t("До 4 000 символов")}</span><span>{draft.length.toLocaleString(locale)} / {(4000).toLocaleString(locale)}</span></div>

        <button className="assistant-submit" type="submit" disabled={!draft.trim() || busy || disabled}>
          {busy ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : <Send size={16} aria-hidden="true" />}<span>{busy ? t(interpreting ? "Распознаём параметры…" : "Получаем почасовой прогноз…") : t("Распознать и построить прогноз")}</span>
        </button>
      </form>

      <div className="assistant-answer-region" aria-live="polite" aria-atomic="true">
        {feedback && <div className="assistant-exchange">
          {feedback.status === "ready" && <p className="assistant-answer-context">{contextLabel(feedback.request)}<span className="assistant-timestamp">{feedback.request.issued_at}</span></p>}
          <div className="assistant-message assistant-question"><h3><MessageSquare size={13} aria-hidden="true" />{t("Ваш запрос")}</h3><p>{feedback.question}</p></div>
          <div className="assistant-message">
            <h3><Sparkles size={13} aria-hidden="true" />{t(feedback.status === "ready" ? "Прогноз готов" : feedback.status === "clarification" ? "Уточните запрос" : "Не удалось выполнить запрос")}</h3>
            {feedback.status === "error" ? <p role="alert">{t(feedback.error.messageKey)}{feedback.error.status && ` (HTTP ${feedback.error.status})`}</p>
              : feedback.status === "clarification" ? <><p>{feedback.message}</p><p>{t("Дополните запрос выше и отправьте снова.")}</p></>
              : <p>{t("Прогноз рассчитан. График, таблица и источники доступны в результатах.")}</p>}
          </div>
        </div>}
      </div>
    </div>
  );
}
