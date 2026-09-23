"use client";

import { useId } from "react";
import { Check, Database, Wind } from "lucide-react";
import type { TurbineSummary } from "./api";
import { useLanguage } from "./i18n";

type TurbineSelectorProps = {
  turbines: TurbineSummary[];
  value: TurbineSummary["id"];
  onChange: (value: TurbineSummary["id"]) => void;
  disabled: boolean;
};

export function TurbineSelector({ turbines, value, onChange, disabled }: TurbineSelectorProps) {
  const { t, locale } = useLanguage();
  const labelId = useId();
  const selected = turbines.find((turbine) => turbine.id === value);
  return (
    <div className="control-section">
      <p className="control-label" id={labelId}><span>01</span>{t("Турбина")}</p>
      <div className="turbine-picker" role="group" aria-labelledby={labelId}>
        {(["turbine_1", "turbine_2"] as const).map((id, index) => (
          <button type="button" className={`turbine-option ${value === id ? "selected" : ""}`} aria-pressed={value === id} key={id} onClick={() => onChange(id)} disabled={disabled || !turbines.some((turbine) => turbine.id === id)}>
            <img src={index === 0 ? "/images/wind-sunset.jpg" : "/images/wind-dusk.jpg"} alt="" width="160" height="120" />
            <span className="turbine-check">{value === id ? <Check size={13} aria-hidden="true" /> : <Wind size={13} aria-hidden="true" />}</span>
            <span className="turbine-name">{t(id === "turbine_1" ? "Турбина 1" : "Турбина 2")}</span>
          </button>
        ))}
      </div>
      {selected && <p className="observation-caption"><Database size={12} aria-hidden="true" /><strong>{selected.rows.toLocaleString(locale)}</strong> {t("наблюдений")}</p>}
    </div>
  );
}

type HorizonSelectorProps = {
  value: 24 | 48;
  onChange: (value: 24 | 48) => void;
  disabled: boolean;
  step: "02" | "03";
};

export function HorizonSelector({ value, onChange, disabled, step }: HorizonSelectorProps) {
  const { t } = useLanguage();
  const labelId = useId();
  return (
    <div className="control-section">
      <p className="control-label" id={labelId}><span>{step}</span>{t("Горизонт")}</p>
      <div className="horizon-picker" role="group" aria-labelledby={labelId}>
        {([24, 48] as const).map((hours) => <button type="button" key={hours} aria-pressed={value === hours} disabled={disabled} onClick={() => onChange(hours)}>{t(hours === 24 ? "24 часа" : "48 часов")}</button>)}
      </div>
    </div>
  );
}
