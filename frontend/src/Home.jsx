import React, { useEffect, useState } from "react";
import { api, tokens, fmtDates } from "./api.js";
import { ShareRow } from "./App.jsx";

const today = () => new Date().toISOString().slice(0, 10);

export default function Home() {
  const [cfg, setCfg] = useState(null);
  const [code, setCode] = useState(tokens.code() || "");
  const [events, setEvents] = useState(null);
  const [form, setForm] = useState({ name: "", start_date: today(), end_date: today(), type: "weekend", tone: "detendu" });
  const [created, setCreated] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api("/config").then(setCfg).catch(() => {}); }, []);
  const load = async (c = code) => {
    setError("");
    try {
      setEvents(await api("/admin/events", { headers: { "X-Admin-Code": c } }));
      tokens.setCode(c);
    } catch (e) { setEvents(null); if (c) setError(e.message); }
  };
  useEffect(() => { if (code) load(code); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const r = await api("/events", { method: "POST", body: { ...form, tz }, headers: { "X-Admin-Code": code } });
      tokens.setAdmin(r.slug, r.admin_token);
      setCreated({ ...r, name: form.name });
      load();
    } catch (err) { setError(err.message); }
    setBusy(false);
  };
  const up = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value, ...(k === "start_date" && f.end_date < e.target.value ? { end_date: e.target.value } : {}) }));
  const link = (slug) => `${location.origin}/e/${slug}`;

  return (
    <main className="page narrow">
      <header className="hero">
        <div className="hero-mark">📔</div>
        <h1>Souvenirs</h1>
        <p className="muted">Le carnet de vos week-ends, courses et virées entre amis : un récit, un film et un album, à partir de ce que chacun enregistre.</p>
      </header>

      {!events && (
        <form className="card" onSubmit={(e) => { e.preventDefault(); load(); }}>
          <h2>Espace organisateur</h2>
          <p className="muted">Tu as reçu un lien d'événement ? Ouvre-le directement, il n'y a rien à saisir ici.</p>
          <label>Code administrateur
            <input type="password" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="current-password" required />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary big">Continuer</button>
        </form>
      )}

      {events && created && (
        <section className="card">
          <h2>« {created.name} » est prêt 🎉</h2>
          <ShareRow label="Lien à partager aux participants" url={link(created.slug)} hint="Privé et non référencé : seuls ceux qui le reçoivent peuvent entrer." />
          <ShareRow label="Ton lien organisateur" url={`${link(created.slug)}/admin/${created.admin_token}`} hint="À garder pour toi : il donne le droit de générer, corriger et publier." />
          <div className="row">
            <a className="btn primary big" href={`/e/${created.slug}`}>Ouvrir l'événement</a>
            <button className="btn" onClick={() => setCreated(null)}>Créer un autre événement</button>
          </div>
        </section>
      )}

      {events && !created && cfg && (
        <form className="card" onSubmit={submit}>
          <h2>Nouvel événement</h2>
          <label>Nom
            <input value={form.name} onChange={up("name")} placeholder="Week-end entre copains" required maxLength={120} />
          </label>
          <div className="grid2">
            <label>Du<input type="date" value={form.start_date} onChange={up("start_date")} required /></label>
            <label>Au<input type="date" value={form.end_date} min={form.start_date} onChange={up("end_date")} required /></label>
          </div>
          <label>Type d'événement
            <select value={form.type} onChange={up("type")}>{Object.entries(cfg.types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          </label>
          <label>Ton du compte rendu
            <select value={form.tone} onChange={up("tone")}>{Object.entries(cfg.tones).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary big" disabled={busy}>{busy ? "Création…" : "Créer l'événement"}</button>
        </form>
      )}

      {events && events.length > 0 && (
        <section className="card">
          <h2>Mes événements</h2>
          <ul className="event-list">
            {events.map((e) => (
              <li key={e.slug}>
                <a href={`/e/${e.slug}/admin/${e.admin_token}`}>
                  <strong>{e.name}</strong>
                  <span className="muted small">{fmtDates(e.start_date, e.end_date)}{e.is_demo ? " · démonstration" : ""}{e.published ? " · publié" : ""}</span>
                </a>
              </li>
            ))}
          </ul>
          <p><a href="/musiques">Musiques</a> <span className="muted small">· ajouter tes propres morceaux</span></p>
          <button className="link" onClick={() => { tokens.setCode(null); setEvents(null); setCode(""); }}>Se déconnecter de cet appareil</button>
        </section>
      )}
    </main>
  );
}
