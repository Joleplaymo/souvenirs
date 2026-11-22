import React, { useEffect, useState } from "react";
import { api, tokens, fmtDur } from "./api.js";
import Chips, { Field } from "./Chips.jsx";

const EMPTY = { title: "", artist: "", genres: [], energy: 3, mood: "joyeux", license: "" };
const MAX_MB = 30;

export default function Music() {
  const code = tokens.code() || "";
  const [cfg, setCfg] = useState(null);
  const [tracks, setTracks] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [file, setFile] = useState(null);
  const [fileKey, setFileKey] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const headers = { "X-Admin-Code": code };

  const load = async () => {
    try { setTracks(await api("/music", { headers })); }
    catch (e) { setTracks(null); setError(e.message); }
  };
  useEffect(() => {
    api("/config").then(setCfg).catch(() => {});
    if (code) load(); else setError("Reconnecte-toi depuis l'accueil avec le code administrateur.");
  }, []);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const moodLabel = (m) => (cfg && cfg.moods && cfg.moods[m]) || m;
  const genreLabel = (g) => (cfg && cfg.genres[g]) || g;

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (!file) return setError("Choisis un fichier MP3.");
    if (file.size > MAX_MB * 1024 * 1024) return setError(`Fichier trop volumineux (maximum ${MAX_MB} Mo).`);
    if (!form.genres.length) return setError("Choisis au moins un genre.");
    setBusy(true);
    try {
      const qs = new URLSearchParams({ title: form.title, artist: form.artist, genres: form.genres.join(","),
        energy: String(form.energy), mood: form.mood, license: form.license });
      await api(`/music?${qs}`, { method: "POST", raw: file, headers });
      setForm(EMPTY); setFile(null); setFileKey((k) => k + 1);
      await load();
    } catch (err) { setError(err.message); }
    setBusy(false);
  };

  const remove = async (t) => {
    if (!confirm(`Supprimer « ${t.title} » du catalogue ?`)) return;
    setError("");
    try { await api(`/music/${t.id}`, { method: "DELETE", headers }); await load(); }
    catch (err) { setError(err.message); }
  };

  return (
    <main className="page narrow">
      <p><a href="/">← Accueil</a></p>
      <h1>Musiques</h1>
      <p className="muted">Le catalogue utilisé pour les films. Tu peux y ajouter tes propres morceaux.</p>
      {error && <p className="error">{error}</p>}

      {tracks && cfg && (
        <>
          <form className="card" onSubmit={submit}>
            <h2>Ajouter un morceau</h2>
            <label>Fichier MP3 (30 Mo maximum)
              <input key={fileKey} type="file" accept="audio/mpeg,.mp3" onChange={(e) => setFile(e.target.files[0] || null)} required />
            </label>
            <div className="grid2">
              <label>Titre<input value={form.title} onChange={(e) => set("title", e.target.value)} required maxLength={200} /></label>
              <label>Artiste<input value={form.artist} onChange={(e) => set("artist", e.target.value)} maxLength={200} /></label>
            </div>
            <Field label="Genres">
              <Chips options={Object.entries(cfg.genres)} value={form.genres} onChange={(v) => set("genres", v)} label="Genres" />
            </Field>
            <div className="grid2">
              <label>Énergie : {form.energy} / 5
                <input type="range" min="1" max="5" step="1" value={form.energy} onChange={(e) => set("energy", Number(e.target.value))} />
              </label>
              <label>Humeur
                <select value={form.mood} onChange={(e) => set("mood", e.target.value)}>
                  {Object.entries(cfg.moods || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
            </div>
            <label>Licence
              <input value={form.license} onChange={(e) => set("license", e.target.value)} placeholder="Ex. : CC BY 4.0, libre de droits, ma composition" required maxLength={300} />
            </label>
            <p className="muted small">Tu dois avoir le droit d'utiliser ce morceau dans une vidéo partagée.</p>
            <button className="btn primary big" disabled={busy}>{busy ? "Envoi…" : "Ajouter au catalogue"}</button>
          </form>

          <section className="card">
            <h2>Catalogue ({tracks.length})</h2>
            {tracks.length === 0 && <p className="muted">Aucun morceau pour l'instant.</p>}
            <ul className="event-list">
              {tracks.map((t) => (
                <li key={t.id} className="track">
                  <div className="track-head">
                    <strong>{t.title}</strong>
                    <span className="muted small">{t.artist}{t.duration ? ` · ${fmtDur(t.duration)}` : ""}</span>
                  </div>
                  <div className="chips">
                    {t.genres.map((g) => <span key={g} className="badge">{genreLabel(g)}</span>)}
                    <span className="badge">Énergie {t.energy}/5</span>
                    <span className="badge">{moodLabel(t.mood)}</span>
                    <span className="badge">{t.origin === "upload" ? "Ajouté par toi" : "Bibliothèque"}</span>
                  </div>
                  <audio controls preload="none" src={t.url} />
                  {t.origin === "upload" && <button className="link" onClick={() => remove(t)}>Supprimer</button>}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </main>
  );
}
