// Puces de choix : options = [[clé, libellé]], value = [clés choisies].
// max=1 : choix unique (toucher une autre puce la remplace). Au maximum atteint, une nouvelle puce
// remplace la dernière choisie (la première, celle qui domine, reste). min : nombre de puces qu'on ne peut pas retirer.
import React from "react";

export default function Chips({ options, value, max = Infinity, min = 0, onChange, disabled, label }) {
  const tap = (k) => {
    if (value.includes(k)) {
      if (max === 1 || value.length <= min) return;
      onChange(value.filter((x) => x !== k));
    } else if (max === 1) onChange([k]);
    else if (value.length >= max) onChange([...value.slice(0, max - 1), k]);
    else onChange([...value, k]);
  };
  return (
    <div className="chips" role="group" aria-label={label}>
      {options.map(([k, l]) => {
        const on = value.includes(k);
        return (
          <button type="button" key={k} className={`chip${on ? " on" : ""}`} aria-pressed={on} onClick={() => tap(k)} disabled={disabled}>
            {l}
          </button>
        );
      })}
    </div>
  );
}

// Tons du type d'événement (config.defaults), ou [] si inconnus.
export const typeTones = (cfg, type) => [...((cfg && cfg.defaults[type] && cfg.defaults[type].tones) || [])];

// Libellé + puces d'un champ.
export function Field({ label, hint, children }) {
  return (
    <div className="field">
      <div className="field-label">{label}{hint && <span className="muted small"> · {hint}</span>}</div>
      {children}
    </div>
  );
}

// Choix du ton : 2 au maximum, le premier choisi domine ; au moins un.
export function ToneChips({ cfg, value, onChange, disabled }) {
  return (
    <Field label="Ton" hint="2 au maximum, le premier choisi domine">
      <Chips options={Object.entries(cfg.tones)} value={value} max={2} min={1} onChange={onChange} disabled={disabled} label="Ton" />
    </Field>
  );
}
