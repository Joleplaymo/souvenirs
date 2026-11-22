// Interrupteur marche/arrêt accessible : un bouton role="switch" (Espace ou Entrée le basculent).
import React from "react";

export default function Toggle({ label, checked, onChange, disabled }) {
  return (
    <button type="button" role="switch" aria-checked={!!checked} className={`toggle${checked ? " on" : ""}`}
      onClick={() => onChange(!checked)} disabled={disabled}>
      <span className="toggle-label">{label}</span>
      <span className="toggle-track" aria-hidden="true"><span className="toggle-thumb" /></span>
    </button>
  );
}
