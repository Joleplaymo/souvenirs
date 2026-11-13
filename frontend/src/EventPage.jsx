import React, { useCallback, useEffect, useState } from "react";
import { api, tokens, fmtDates } from "./api.js";
import Capture from "./Capture.jsx";
import Generate from "./Generate.jsx";
import Review from "./Review.jsx";
import Published from "./Published.jsx";
import { ShareRow } from "./App.jsx";

export default function EventPage({ slug }) {
  const [ev, setEv] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(null);
  const [name, setName] = useState("");
  const [share, setShare] = useState(false);

  const load = useCallback(async () => {
    try {
      const e = await api(`/events/${slug}`, { slug });
      setEv(e);
      document.title = e.name;
      setTab((t) => t || (e.published && !e.is_admin ? "souvenir" : "capture"));
      if (!e.is_admin && tokens.admin(slug)) tokens.setAdmin(slug, null);
    } catch (err) { if (!err.network || !ev) setError(err.message); }
  }, [slug]);
  useEffect(() => { load(); }, [load]);

  const join = async (e) => {
    e.preventDefault();
    try {
      const r = await api(`/events/${slug}/join`, { method: "POST", body: { name } });
      tokens.setParticipant(slug, r.token);
      load();
    } catch (err) { setError(err.message); }
  };

  if (error && !ev) return <main className="page narrow"><div className="card"><h2>Oups</h2><p>{error}</p></div></main>;
  if (!ev) return <main className="page narrow"><p className="muted center">Chargement…</p></main>;

  if (!ev.me) {
    return (
      <main className="page narrow">
        <header className="hero">
          <div className="hero-mark">📔</div>
          <h1>{ev.name}</h1>
          <p className="muted">{fmtDates(ev.start_date, ev.end_date)} · {ev.type_label}</p>
        </header>
        <form className="card" onSubmit={join}>
          <h2>Bienvenue !</h2>
          <p className="muted">Pas de compte à créer. Dis-nous juste comment tu t'appelles : ton prénom signera tes photos, vidéos et dictées.</p>
          <label>Ton prénom
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} required autoFocus autoComplete="given-name" />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary big">Rejoindre</button>
          <p className="muted small">Ce que tu ajoutes est visible par le groupe et servira au compte rendu. Tu peux supprimer tes propres ajouts à tout moment.</p>
        </form>
      </main>
    );
  }

  const tabs = [["capture", "📸", "Capturer"], ...(ev.is_admin ? [["generer", "✨", "Générer"], ["relecture", "📝", "Relecture"]] : []), ["souvenir", "📖", "Souvenir"]];
  const counter = ev.phase === "pendant" ? `Jour ${ev.day}` : ev.phase === "avant" ? `J-${1 - ev.day}` : "Terminé";
  const base = `${location.origin}/e/${slug}`;

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>{ev.name}</h1>
          <div className="counter">{counter} · {ev.count} souvenir{ev.count > 1 ? "s" : ""}{ev.is_admin ? " · organisateur" : ""}</div>
        </div>
        <button className="btn ghost" onClick={() => setShare(true)} aria-label="Partager le lien">Inviter</button>
      </header>
      <nav className="tabs" aria-label="Sections">
        {tabs.map(([id, icon, label]) => (
          <button key={id} className={tab === id ? "on" : ""} onClick={() => setTab(id)} aria-current={tab === id}>
            <span aria-hidden>{icon}</span>{label}
          </button>
        ))}
      </nav>
      <main className="content">
        {tab === "capture" && <Capture slug={slug} ev={ev} onEvent={setEv} />}
        {tab === "generer" && ev.is_admin && <Generate slug={slug} ev={ev} goReview={() => setTab("relecture")} />}
        {tab === "relecture" && ev.is_admin && <Review slug={slug} ev={ev} reload={load} goGenerate={() => setTab("generer")} />}
        {tab === "souvenir" && <Published slug={slug} ev={ev} />}
      </main>
      {share && (
        <div className="modal" onClick={() => setShare(false)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <h2>Inviter des amis</h2>
            <ShareRow label="Lien participants" url={base} hint="Privé et non référencé. Tes amis l'ouvrent sur leur téléphone, sans rien installer." />
            {ev.is_admin && <ShareRow label="Ton lien organisateur" url={`${base}/admin/${tokens.admin(slug)}`} hint="À garder pour toi (pour retrouver tes droits sur un autre appareil)." />}
            <p className="muted small">Astuce : dans le menu du navigateur, « Ajouter à l'écran d'accueil » installe le carnet comme une application.</p>
            <button className="btn big" onClick={() => setShare(false)}>Fermer</button>
          </div>
        </div>
      )}
    </div>
  );
}
