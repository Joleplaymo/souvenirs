// Pré-écoute de la musique du film (écran Générer et « Changer la musique » en relecture).
// Propose un morceau par rôle (Début, Cœur, Sommet, Final) selon l'évolution choisie ; chaque rôle a son « Autre titre ».
// onChange(r) : undefined pendant la recherche, puis { tracks: [{ role, track }], main, final } ([] si rien) ou { error }.
// initialExclude : { rôle: [ids] } à ne pas proposer d'emblée (ex. les morceaux déjà dans le film) ; pour un rôle
// sans autre morceau, on retombe sur sa liste complète.
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

export const ROLE_LABEL = { intro: "Début", main: "Cœur", peak: "Sommet", final: "Final" };

// { rôle: id } des morceaux proposés (corps « music » de /generate).
export const musicRoles = (m) => Object.fromEntries(((m && m.tracks) || []).map(({ role, track }) => [role, track.id]));

const clean = (ex) => Object.fromEntries(Object.entries(ex || {})
  .map(([r, ids]) => [r, (ids || []).filter((id) => id != null)]).filter(([, ids]) => ids.length));
const copy = (ex) => Object.fromEntries(Object.entries(ex).map(([r, ids]) => [r, [...ids]]));
const pub = (r) => ({ tracks: r.tracks || [], main: r.main, final: r.final });

function Track({ label, t, onOther, disabled }) {
  return (
    <div className="preview-track">
      <div className="muted small">{label}</div>
      <div><strong>{t.title}</strong>{t.artist ? <span className="muted"> · {t.artist}</span> : null}</div>
      <audio key={t.url} controls preload="none" src={`${t.url}#t=0,15`} aria-label={`Écouter 15 s de « ${t.title} »`} />
      <button type="button" className="btn" onClick={onOther} disabled={disabled} aria-label={`Autre titre pour « ${label} »`}>🔀 Autre titre</button>
    </div>
  );
}

export default function MusicPreview({ slug, tones, settings, disabled, onChange, initialExclude = {} }) {
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const seen = useRef({}); // { rôle: ids déjà proposés pendant cette visite }
  const excl = useRef({}); // exclusions de la proposition affichée
  const seq = useRef(0);
  const shown = useRef(null); // réglages de la dernière proposition (pas de nouvelle recherche s'ils n'ont pas changé)
  const key = JSON.stringify([tones, settings.genres, settings.energy, settings.ending, settings.evolution]);

  const call = (exclude) => api(`/events/${slug}/music/pick`, { slug, method: "POST", body: { tones, video_settings: settings, exclude } });
  const pick = async (wanted, first = false) => {
    const n = ++seq.current;
    setLoading(true); setError(""); onChange?.(undefined);
    try {
      let ex = wanted;
      let r = await call(ex);
      const missing = Object.keys(ex).filter((role) => !r.tracks.some((t) => t.role === role));
      if (missing.length) { // plus rien de neuf pour ces rôles : on repart de leur liste complète
        if (n !== seq.current) return;
        ex = { ...ex };
        missing.forEach((role) => { delete ex[role]; seen.current[role] = []; });
        r = await call(ex);
      }
      if (n !== seq.current) return;
      excl.current = ex;
      r.tracks.forEach(({ role, track }) => {
        const s = seen.current[role] || (seen.current[role] = []);
        if (!s.includes(track.id)) s.push(track.id);
      });
      setRes(r); onChange?.(pub(r));
    } catch (e) {
      if (n !== seq.current) return;
      if (first) shown.current = null; // réessai possible (par exemple après une génération en cours)
      setError(e.message); onChange?.({ error: e.message });
    }
    setLoading(false);
  };
  // « Autre titre » pour un rôle : écarte tous ses morceaux déjà entendus, garde les exclusions des autres rôles.
  const other = (role) => pick({ ...excl.current, [role]: [...(seen.current[role] || [])] });

  useEffect(() => { // réglages changés : nouvelle proposition (après 400 ms sans changement)
    if (disabled) return;
    if (key === shown.current) { // revenu aux réglages de la proposition affichée (ou recherche en cours pour eux)
      if (!loading && res) onChange?.(pub(res));
      return;
    }
    seq.current++; // une réponse encore en route pour d'anciens réglages sera ignorée
    if (loading) shown.current = null; // recherche abandonnée : revenir à ces réglages relancera une recherche
    setLoading(false);
    onChange?.(undefined); // la proposition affichée ne correspond plus aux réglages
    const t = setTimeout(() => {
      const start = clean(Array.isArray(initialExclude) ? { main: initialExclude } : initialExclude);
      seen.current = copy(start);
      shown.current = key;
      pick(start, true);
    }, 400);
    return () => clearTimeout(t);
  }, [key, disabled]);
  useEffect(() => () => { seq.current++; }, []);

  const tracks = (res && res.tracks) || [];
  return (
    <div className="preview" aria-live="polite">
      <h3>Pré-écoute</h3>
      {tracks.map(({ role, track }) => (
        <Track key={role} t={track} label={tracks.length === 1 ? "Morceau du film" : ROLE_LABEL[role] || role}
          onOther={() => other(role)} disabled={disabled || loading} />
      ))}
      {res && !tracks.length && <p className="muted">{res.message || "Aucune musique ne correspond à ces réglages : le film sera sans musique."}</p>}
      {loading && <p className="muted small">Recherche de la musique…</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
