"use client";

import { useId, useState, type FormEvent } from "react";
import { MessageSquare, Send, Sparkles } from "lucide-react";
import type { ForecastRunRequest, ForecastRunResponse } from "./api";
import { useLanguage } from "./i18n";
import "./AssistantPanel.css";

type AssistantPanelProps = {
  request: ForecastRunRequest;
  run: ForecastRunResponse | null;
};

type PreparedQuestion = { text: string; request: ForecastRunRequest };

export function AssistantPanel({ request, run }: AssistantPanelProps) {
  const { t, locale } = useLanguage();
  const id = useId();
  const [draft, setDraft] = useState("");
  const [preparedQuestion, setPreparedQuestion] = useState<PreparedQuestion | null>(null);
  const hasResult = run !== null && run.turbine_id === request.turbine_id &&
    run.horizon_hours === request.horizon_hours && Date.parse(run.issued_at) === Date.parse(request.issued_at);

  function contextLabel(context: ForecastRunRequest) {
    return `${t(context.turbine_id === "turbine_1" ? "Турбина 1" : "Турбина 2")} · ${t(context.horizon_hours === 24 ? "24 часа" : "48 часов")}`;
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question) return;
    setPreparedQuestion({ text: question, request: { ...request } });
    setDraft("");
  }

  return (
    <div className="assistant-panel">
      <div className="assistant-context" aria-label={t("Контекст вопроса")}>
        <p><Sparkles size={14} aria-hidden="true" /><span>{contextLabel(request)}</span></p>
        <span className="assistant-timestamp">{request.issued_at}</span>
        <span className="assistant-context-note">{hasResult ? t("Результат прогноза выбран") : t("Параметры из ручного ввода")}</span>
      </div>

      <div className="assistant-demo" id={`${id}-demo`}><span className="assistant-demo-badge">{t("Демо-режим")}</span><p>{t("Сервис ИИ ещё не подключён. Это демонстрация интерфейса.")}</p></div>

      <form className="assistant-form" onSubmit={submit}>
        <label htmlFor={`${id}-question`}>{t("Вопрос о прогнозе")}</label>
        <textarea id={`${id}-question`} value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={4000} rows={5} placeholder={t("Например: в какие часы прогнозируется наибольшая мощность?")} aria-describedby={`${id}-limit ${id}-demo`} />
        <div className="assistant-input-meta" id={`${id}-limit`}><span>{t("До 4 000 символов")}</span><span>{draft.length.toLocaleString(locale)} / {(4000).toLocaleString(locale)}</span></div>

        <button className="assistant-submit" type="submit" disabled={!draft.trim()} aria-describedby={`${id}-demo`}>
          <Send size={16} aria-hidden="true" /><span>{t("Отправить вопрос")}</span>
        </button>
      </form>

      <div className="assistant-answer-region" aria-live="polite" aria-atomic="true">
        {preparedQuestion && <div className="assistant-exchange">
          <p className="assistant-answer-context">{contextLabel(preparedQuestion.request)}<span className="assistant-timestamp">{preparedQuestion.request.issued_at}</span></p>
          <div className="assistant-message assistant-question"><h3><MessageSquare size={13} aria-hidden="true" />{t("Вопрос подготовлен")}</h3><p>{preparedQuestion.text}</p></div>
          <div className="assistant-message"><h3><Sparkles size={13} aria-hidden="true" />{t("Место для ответа ИИ")}</h3><p>{t("Ответ ИИ появится здесь после подключения сервиса.")}</p></div>
        </div>}
      </div>
    </div>
  );
}
