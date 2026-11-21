import React, { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import Selection from "./Selection.jsx";
import Settings from "./Settings.jsx";
import Chips, { Field, ToneChips } from "./Chips.jsx";
import MusicPreview, { musicRoles } from "./MusicPreview.jsx";
import Toggle from "./Toggle.jsx";
import { Toast } from "./App.jsx";

const STEPS = [["transcription", "Transcription des audios et des vidéos"], ["analyse", "Analyse des photos et des vidéos"],
  ["redaction", "Rédaction du compte rendu"], ["montage", "Montage de la vidéo"], ["album", "Mise en page de l'album"]];
const MUSIC_STEPS = [["musique", "Changement de la musique"]];
const ENERGY = { 1: "Calme", 2: "Posé", 3: "Entraînant", 4: "Dynamique", 5: "Survolté" };
const durLabel = (s) => (s < 60 ? `${s} s` : `${Math.round(s / 6) / 10} min`.replace(".", ","));
const VIDEO_KEYS = ["ending", "genres", "energy", "mix", "duration", "subtitles",
  "rhythm", "evolution", "effects", "title_style", "framing"];
const videoOf = (f) => Object.fromEntries(VIDEO_KEYS.map((k) => [k, f[k]]));
// Signature des réglages (tons + vidéo) pour reconnaître le préréglage appliqué.
const sig = (cfg, tones, vs) => JSON.stringify([tones, VIDEO_KEYS.map((k) => (k === "effects"
  ? Object.keys(cfg.effects).map((e) => !!(vs.effects && vs.effects[e])) : vs[k]))]);

export function useJob(slug, onFinish) {
  const [job, setJob] = useState(undefined);
  const prev = useRef(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { job } = await api(`/events/${slug}/job`, { slug });
        if (!alive) return;
        const was = prev.current;
        prev.current = job && job.status;
        setJob(job);
        if (was && ["queued", "running"].includes(was) && job && ["done", "error"].includes(job.status)) onFinish?.(job);
      } catch {}
    };
    tick();
    const t = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [slug]);
  const active = job && ["queued", "running"].includes(job.status);
  return [job, active, setJob];
}

export function JobProgress({ job }) {
  const parts = (job.params && job.params.parts) || [];
  const steps = job.step === "musique" || (parts.length === 1 && parts[0] === "music") ? MUSIC_STEPS : STEPS;
  const idx = steps.findIndex(([k]) => k === job.step);
  return (
    <div className="progress-card" role="status">
      <progress value={job.progress || 0} max="1" />
      <div className="progress-pct">{Math.round((job.progress || 0) * 100)} %</div>
      <ol className="steps">
        {steps.map(([k, label], i) => (
          <li key={k} className={i < idx || job.step === "termine" ? "done" : i === idx ? "now" : ""}>
            {label}{i === idx && job.message ? <span className="muted small"> — {job.message}</span> : null}
          </li>
        ))}
      </ol>
      <p className="muted small">Tu peux fermer cette page : le travail continue sur le serveur.</p>
    </div>
  );
}

// Réglages par défaut du type pour les champs que l'organisateur n'a pas modifiés à la main.
function typeFill(cfg, type, touched, f) {
  const d = cfg.defaults[type] || cfg.defaults.autre;
  const out = {};
  if (!touched.has("tones")) out.tones = [...d.tones];
  if (!touched.has("genres")) out.genres = [...d.genres];
  if (!touched.has("energy")) out.energy = d.energy;
  if (!touched.has("ending")) out.ending = d.ending;
  if (!touched.has("rhythm")) out.rhythm = d.rhythm;
  if (!touched.has("evolution")) out.evolution = d.evolution;
  const fx = { ...(f.effects || {}) }; // effets tous activés, sauf « Effets humoristiques » selon le type
  for (const k of Object.keys(cfg.effects)) if (!touched.has(`effects.${k}`)) fx[k] = k === "humor" ? d.humor_fx !== false : true;
  out.effects = fx;
  return out;
}

export default function Generate({ slug, ev, reload, goReview }) {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState(null); // { type, tones, ...réglages vidéo (VIDEO_KEYS) }
  const [presets, setPresets] = useState(null);
  const [presetName, setPresetName] = useState("");
  const [presetBusy, setPresetBusy] = useState(false);
  const [presetError, setPresetError] = useState("");
  const [wishes, setWishes] = useState("");
  const [music, setMusic] = useState(undefined); // pré-écoute : undefined = en cours
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const touched = useRef(new Set()); // champs modifiés à la main depuis l'ouverture de l'écran
  const evKey = useRef(`${ev.type}|${ev.tone}`);
  const [job, active, setJob] = useJob(slug);

  useEffect(() => {  // reprend les réglages et les consignes de la génération précédente
    Promise.all([api("/config"), api(`/events/${slug}/draft`, { slug })]).then(([c, d]) => {
      setCfg(c);
      setForm({ type: ev.type, tones: [...ev.tones], ...d.video_settings });
      setWishes(d.video_prompt || "");
    }).catch((e) => setError(e.message));
    loadPresets();
  }, [slug]);
  useEffect(() => {  // type ou ton changés ailleurs (carte Réglages) : on les reprend
    const k = `${ev.type}|${ev.tone}`;
    if (k === evKey.current) return;
    const typeChanged = !evKey.current.startsWith(`${ev.type}|`);
    evKey.current = k;
    setForm((f) => (f && cfg ? { ...f, ...(typeChanged ? typeFill(cfg, ev.type, touched.current, f) : {}), type: ev.type, tones: [...ev.tones] } : f));
  }, [ev.type, ev.tone]);

  const set = (k, v) => { touched.current.add(k); setForm((f) => ({ ...f, [k]: v })); };
  const setType = ([t]) => setForm((f) => ({ ...f, type: t, ...typeFill(cfg, t, touched.current, f) }));
  const setEffect = (k, v) => { touched.current.add(`effects.${k}`); setForm((f) => ({ ...f, effects: { ...f.effects, [k]: v } })); };

  const loadPresets = () => api(`/events/${slug}/presets`, { slug }).then(setPresets).catch(() => setPresets((p) => p || []));
  const applyPreset = (p) => {  // tons et réglages vidéo du préréglage (ni le type, ni les consignes)
    const vs = p.video_settings || {};
    const next = {};
    for (const k of VIDEO_KEYS) {
      if (vs[k] === undefined || vs[k] === null) continue;
      next[k] = Array.isArray(vs[k]) ? [...vs[k]] : typeof vs[k] === "object" ? { ...vs[k] } : vs[k];
      touched.current.add(k);
    }
    if (next.effects) Object.keys(next.effects).forEach((e) => touched.current.add(`effects.${e}`));
    if (p.tones && p.tones.length) { next.tones = [...p.tones]; touched.current.add("tones"); }
    setForm((f) => ({ ...f, ...next, effects: { ...f.effects, ...(next.effects || {}) } }));
    setToast(`Préréglage « ${p.name} » appliqué`);
  };
  const deletePreset = async (p) => {
    if (!confirm(`Supprimer le préréglage « ${p.name} » ? Il ne sera plus proposé, pour aucun souvenir.`)) return;
    try {
      await api(`/events/${slug}/presets/${p.id}`, { slug, method: "DELETE" });
      setToast(`Préréglage « ${p.name} » supprimé`);
    } catch (e) { setToast(e.message); }
    loadPresets();
  };
  const savePreset = async (e) => {
    e.preventDefault();
    const name = presetName.trim();
    if (!name) return;
    if ((presets || []).some((p) => p.name === name) && !confirm(`Le préréglage « ${name} » existe déjà : le remplacer par ces réglages ?`)) return;
    setPresetBusy(true); setPresetError("");
    try {
      await api(`/events/${slug}/presets`, { slug, method: "POST", body: { name, tones: form.tones, video_settings: videoOf(form) } });
      setPresetName("");
      setToast(`Préréglage « ${name} » enregistré`);
      await loadPresets();
    } catch (err) { setPresetError(err.message); }
    setPresetBusy(false);
  };
  const off = active || busy;
  const storyChanged = form && (form.type !== ev.type || form.tones.join(",") !== ev.tones.join(","));

  const start = async () => {
    setError(""); setBusy(true);
    try {
      if (storyChanged) {  // le ton (et le type) sont ceux de l'événement : enregistrés avant de générer
        await api(`/events/${slug}/settings`, { slug, method: "PUT", body: {
          name: ev.name, start_date: ev.start_date, end_date: ev.end_date, tz: ev.tz, type: form.type, tone: form.tones } });
        evKey.current = `${form.type}|${form.tones.join(",")}`;
        await reload();
      }
      const body = { video_settings: videoOf(form), video_prompt: wishes, parts: ["text", "video", "album"] };
      if (music && !music.error) body.music = { roles: musicRoles(music) }; // les morceaux entendus, rôle par rôle
      await api(`/events/${slug}/generate`, { slug, method: "POST", body });
      setJob({ status: "queued", step: "", progress: 0, message: "" });
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  if (!form || !cfg) {
    return <div className="narrow-col">{error ? <p className="error">{error}</p> : <p className="muted center">Chargement…</p>}</div>;
  }
  const toneLabel = form.tones.map((t) => cfg.tones[t] || t).join(" + ").toLowerCase();
  const vs = videoOf(form);
  const noMusic = !!(music && !music.error && !(music.tracks && music.tracks.length)); // la pré-écoute n'a rien trouvé
  const current = sig(cfg, form.tones, vs);
  const film = noMusic
    ? (form.subtitles ? "un film sous-titré, sans musique" : "un film sans musique ni sous-titres")
    : (form.subtitles ? "un film avec musique et sous-titres" : "un film avec musique, sans sous-titres");

  return (
    <div className="narrow-col">
      <Settings slug={slug} ev={ev} disabled={off} onSaved={reload} onToast={setToast} story={false} />
      <section className="card gen">
        <h2>Générer le compte rendu</h2>
        <p className="muted">À partir des {ev.count} souvenirs du groupe : un récit sur le ton « {toneLabel} », {film}, et un album photo à imprimer.</p>

        {presets && (
          <Field label="Préréglages" hint={presets.length ? "touche pour appliquer" : undefined}>
            {presets.length ? (
              <div className="chips" role="group" aria-label="Préréglages">
                {presets.map((p) => {
                  const on = sig(cfg, p.tones, { ...vs, ...p.video_settings }) === current;
                  return (
                    <span key={p.id} className={`preset${on ? " on" : ""}`}>
                      <button type="button" className="preset-apply" onClick={() => applyPreset(p)} disabled={off}
                        aria-label={`Appliquer le préréglage « ${p.name} »`} aria-pressed={on}>{p.name}</button>
                      <button type="button" className="preset-x" onClick={() => deletePreset(p)} disabled={off}
                        aria-label={`Supprimer le préréglage « ${p.name} »`}>×</button>
                    </span>
                  );
                })}
              </div>
            ) : <p className="muted small">Aucun préréglage pour l'instant : règle le film à ton goût, puis enregistre-le en bas de l'écran pour le retrouver sur tes prochains souvenirs.</p>}
          </Field>
        )}

        <details open className="sect">
          <summary><h3>Histoire</h3></summary>
          <Field label="Type d'événement">
            <Chips options={Object.entries(cfg.types)} value={[form.type]} max={1} onChange={setType} disabled={off} label="Type d'événement" />
          </Field>
          <ToneChips cfg={cfg} value={form.tones} onChange={(v) => set("tones", v)} disabled={off} />
          <p className="muted small">Le ton s'applique au récit et au film.</p>
          <Field label="Fin du film">
            <Chips options={Object.entries(cfg.endings)} value={[form.ending]} max={1} onChange={([v]) => set("ending", v)} disabled={off} label="Fin du film" />
          </Field>
        </details>

        <details open className="sect">
          <summary><h3>Musique</h3></summary>
          <Field label="Genres" hint="plusieurs possibles">
            <Chips options={Object.entries(cfg.genres)} value={form.genres} min={1} onChange={(v) => set("genres", v)} disabled={off} label="Genres" />
          </Field>
          <Field label="Évolution" hint="un ou plusieurs morceaux enchaînés">
            <Chips options={Object.entries(cfg.evolutions)} value={[form.evolution]} max={1} onChange={([v]) => set("evolution", v)} disabled={off} label="Évolution de la musique" />
          </Field>
          <label className="slider">Énergie : {form.energy} / 5 · {ENERGY[form.energy]}
            <input type="range" min="1" max="5" step="1" value={form.energy} onChange={(e) => set("energy", +e.target.value)} disabled={off}
              aria-valuetext={`${form.energy} sur 5, ${ENERGY[form.energy]}`} />
            <span className="slider-ends muted small"><span>Calme</span><span>Survolté</span></span>
          </label>
          <label className="slider">Mélange : {form.mix} % de musique
            <input type="range" min="0" max="100" step="5" value={form.mix} onChange={(e) => set("mix", +e.target.value)} disabled={off}
              aria-valuetext={`${form.mix} % de musique, ${100 - form.mix} % de sons réels`} />
            <span className="slider-ends muted small"><span>Sons réels</span><span>Musique</span></span>
          </label>
        </details>

        <details open className="sect">
          <summary><h3>Montage</h3></summary>
          <Field label="Rythme">
            <Chips options={Object.entries(cfg.rhythms)} value={[form.rhythm]} max={1} onChange={([v]) => set("rhythm", v)} disabled={off} label="Rythme du montage" />
          </Field>
          <div className="field">
            <div className="field-label">Effets</div>
            <div className="toggles" role="group" aria-label="Effets">
              {Object.entries(cfg.effects).map(([k, l]) => (
                <Toggle key={k} label={l} checked={!!form.effects[k]} onChange={(v) => setEffect(k, v)} disabled={off} />
              ))}
              <Toggle label="Sous-titres des citations" checked={form.subtitles} onChange={(v) => set("subtitles", v)} disabled={off} />
            </div>
          </div>
          <Field label="Style des titres">
            <Chips options={Object.entries(cfg.title_styles)} value={[form.title_style]} max={1} onChange={([v]) => set("title_style", v)} disabled={off} label="Style des titres" />
          </Field>
        </details>

        <details open className="sect">
          <summary><h3>Format</h3></summary>
          <Field label="Durée du film">
            <Chips options={cfg.durations.map((s) => [s, durLabel(s)])} value={[form.duration]} max={1} onChange={([v]) => set("duration", v)} disabled={off} label="Durée du film" />
          </Field>
          <Field label="Cadrage">
            <Chips options={Object.entries(cfg.framings)} value={[form.framing]} max={1} onChange={([v]) => set("framing", v)} disabled={off} label="Cadrage" />
          </Field>
          <label>Consignes pour le film <span className="muted small">(facultatif)</span>
            <textarea rows={6} maxLength={4000} value={wishes} onChange={(e) => setWishes(e.target.value)} disabled={off}
              placeholder="Ex. : commence par l'arrivée au chalet, garde beaucoup de vidéos de la course, mets en avant Léa et Max, finis sur le coucher de soleil." />
          </label>
          <p className="muted small">L'IA suit ces consignes pour choisir les moments, leur ordre, la durée des plans, les cartons et les sous-titres, sans jamais inventer. Réglages et consignes sont gardés pour les prochaines générations (et pour « Régénérer » le film en relecture).</p>
        </details>

        <MusicPreview slug={slug} tones={form.tones} settings={vs} disabled={job === undefined || !!active} onChange={setMusic} />

        <p className="muted small">Chaque génération est gardée comme version (écran Relecture) : tu peux changer les réglages, régénérer et comparer.</p>
        {error && <p className="error">{error}</p>}
        {!active && <button className="btn primary big" onClick={start} disabled={ev.raw_purged || busy || music === undefined}>{busy ? "Lancement…" : "✨ Générer le compte rendu"}</button>}
        {ev.raw_purged && <p className="muted small">Les fichiers bruts ont été supprimés : seuls les résultats publiés sont conservés.</p>}

        <form className="save-preset" onSubmit={savePreset}>
          <label htmlFor="preset-name" className="field-label">Enregistrer comme préréglage</label>
          <p className="muted small" id="preset-hint">Garde les tons et les réglages du film (pas le type ni les consignes) pour tes prochains souvenirs.</p>
          <div className="save-preset-row">
            <input id="preset-name" aria-describedby="preset-hint" value={presetName} maxLength={60} placeholder="Nom, ex. : Week-end ski"
              onChange={(e) => { setPresetName(e.target.value); setPresetError(""); }} disabled={presetBusy} />
            <button type="submit" className="btn" disabled={presetBusy || !presetName.trim()}>{presetBusy ? "Enregistrement…" : "Enregistrer"}</button>
          </div>
          {presetError && <p className="error">{presetError}</p>}
        </form>
      </section>
      {!ev.raw_purged && <Selection slug={slug} ev={ev} disabled={active} onToast={setToast} />}
      {active && <JobProgress job={job} />}
      {job && job.status === "error" && <div className="card"><p className="error">La génération a échoué : {job.message}</p><p className="muted small">Ce qui était déjà fait (transcriptions) est conservé : relance simplement.</p></div>}
      {job && job.status === "done" && (
        <div className="card">
          <h2>C'est prêt 🎉</h2>
          <p className="muted">Relis, corrige ce qui doit l'être, puis publie pour le groupe.</p>
          <button className="btn primary big" onClick={goReview}>Passer à la relecture</button>
        </div>
      )}
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}
