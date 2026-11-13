import React, { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const STEPS = [["transcription", "Transcription des audios et des vidéos"], ["analyse", "Analyse des photos et des vidéos"],
  ["redaction", "Rédaction du compte rendu"], ["montage", "Montage de la vidéo"], ["album", "Mise en page de l'album"]];
const DURATIONS = [[60, "1 minute"], [120, "2 minutes"], [180, "3 minutes"], [300, "5 minutes"]];

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
  const idx = STEPS.findIndex(([k]) => k === job.step);
  return (
    <div className="progress-card" role="status">
      <progress value={job.progress || 0} max="1" />
      <div className="progress-pct">{Math.round((job.progress || 0) * 100)} %</div>
      <ol className="steps">
        {STEPS.map(([k, label], i) => (
          <li key={k} className={i < idx || job.step === "termine" ? "done" : i === idx ? "now" : ""}>
            {label}{i === idx && job.message ? <span className="muted small"> — {job.message}</span> : null}
          </li>
        ))}
      </ol>
      <p className="muted small">Tu peux fermer cette page : le travail continue sur le serveur.</p>
    </div>
  );
}

export default function Generate({ slug, ev, goReview }) {
  const [duration, setDuration] = useState(120);
  const [error, setError] = useState("");
  const [job, active, setJob] = useJob(slug);

  const start = async () => {
    setError("");
    try {
      await api(`/events/${slug}/generate`, { slug, method: "POST", body: { video_duration: duration, parts: ["text", "video", "album"] } });
      setJob({ status: "queued", step: "", progress: 0, message: "" });
    } catch (e) { setError(e.message); }
  };

  return (
    <div className="narrow-col">
      <section className="card">
        <h2>Générer le compte rendu</h2>
        <p className="muted">À partir des {ev.count} souvenirs du groupe : un récit sur le ton « {ev.tone_label.toLowerCase()} », un film avec musique et sous-titres, et un album photo à imprimer.</p>
        <label>Durée du film
          <select value={duration} onChange={(e) => setDuration(+e.target.value)} disabled={active}>
            {DURATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        {error && <p className="error">{error}</p>}
        {!active && <button className="btn primary big" onClick={start} disabled={ev.raw_purged}>✨ Générer le compte rendu</button>}
        {ev.raw_purged && <p className="muted small">Les fichiers bruts ont été supprimés : seuls les résultats publiés sont conservés.</p>}
      </section>
      {active && <JobProgress job={job} />}
      {job && job.status === "error" && <div className="card"><p className="error">La génération a échoué : {job.message}</p><p className="muted small">Ce qui était déjà fait (transcriptions) est conservé : relance simplement.</p></div>}
      {job && job.status === "done" && (
        <div className="card">
          <h2>C'est prêt 🎉</h2>
          <p className="muted">Relis, corrige ce qui doit l'être, puis publie pour le groupe.</p>
          <button className="btn primary big" onClick={goReview}>Passer à la relecture</button>
        </div>
      )}
    </div>
  );
}
