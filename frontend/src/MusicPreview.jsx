// Pré-écoute de la musique du film (écran Générer et « Changer la musique » en relecture).
// Propose le morceau (et celui de la séquence finale) pour ces réglages ; « Autre titre » en cherche un autre.
// onChange(r) : undefined pendant la recherche, puis { main, final } (null si rien) ou { error }.
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

function Track({ label, t }) {
  return (
    <div className="preview-track">
      <div className="muted small">{label}</div>
      <div><strong>{t.title}</strong>{t.artist ? <span className="muted"> · {t.artist}</span> : null}</div>
      <audio key={t.url} controls preload="none" src={`${t.url}#t=0,15`} aria-label={`Écouter 15 s de « ${t.title} »`} />
    </div>
  );
}

export default function MusicPreview({ slug, tones, settings, disabled, onChange }) {
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const seen = useRef([]); // morceaux principaux déjà proposés pendant cette visite
  const seq = useRef(0);
  const shown = useRef(null); // réglages de la dernière proposition (pas de nouvelle recherche s'ils n'ont pas changé)
  const key = JSON.stringify([tones, settings.genres, settings.energy, settings.ending]);

  const call = (exclude) => api(`/events/${slug}/music/pick`, { slug, method: "POST", body: { tones, video_settings: settings, exclude } });
  const pick = async (exclude) => {
    const n = ++seq.current;
    setLoading(true); setError(""); onChange?.(undefined);
    try {
      let r = await call(exclude);
      if (!r.main && exclude.length) { // plus rien de neuf : on repart de zéro
        if (n !== seq.current) return;
        seen.current = [];
        r = await call([]);
      }
      if (n !== seq.current) return;
      if (r.main && !seen.current.includes(r.main.id)) seen.current.push(r.main.id);
      setRes(r); onChange?.({ main: r.main, final: r.final });
    } catch (e) {
      if (n !== seq.current) return;
      if (!exclude.length) shown.current = null; // réessai possible (par exemple après une génération en cours)
      setError(e.message); onChange?.({ error: e.message });
    }
    setLoading(false);
  };

  useEffect(() => { // réglages changés : nouvelle proposition (après 400 ms sans changement)
    if (disabled) return;
    if (key === shown.current) { // revenu aux réglages de la proposition affichée (ou recherche en cours pour eux)
      if (!loading && res) onChange?.({ main: res.main, final: res.final });
      return;
    }
    onChange?.(undefined); // la proposition affichée ne correspond plus aux réglages
    const t = setTimeout(() => { seen.current = []; shown.current = key; pick([]); }, 400);
    return () => clearTimeout(t);
  }, [key, disabled]);
  useEffect(() => () => { seq.current++; }, []);

  return (
    <div className="preview" aria-live="polite">
      <h3>Pré-écoute</h3>
      {res && res.main && <Track label="Morceau du film" t={res.main} />}
      {res && res.final && <Track label="Séquence finale" t={res.final} />}
      {res && !res.main && <p className="muted">{res.message || "Aucune musique ne correspond à ces réglages : le film sera sans musique."}</p>}
      {loading && <p className="muted small">Recherche d'un morceau…</p>}
      {error && <p className="error">{error}</p>}
      <button type="button" className="btn" onClick={() => pick([...seen.current])} disabled={disabled || loading || !(res && res.main)}>🔀 Autre titre</button>
    </div>
  );
}
