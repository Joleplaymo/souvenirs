// Versions enregistrées du souvenir (organisateur) : chaque génération en crée une ; on peut en garder
// d'autres, les comparer (aperçu sans toucher au brouillon), reprendre l'une d'elles, la renommer ou la supprimer.
import React, { useEffect, useState } from "react";
import { api, tokens } from "./api.js";
import Markdown from "./Markdown.jsx";

function when(iso) {
  return new Date(iso).toLocaleString("fr-FR", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
const ORIGIN = { generation: "générée", manual: "enregistrée", auto: "sauvegarde auto", publish: "à la publication" };

export default function Versions({ slug, busy, refresh, beforeSave, onRestored, onToast }) {
  const [data, setData] = useState(null);
  const [view, setView] = useState(null); // version ouverte en aperçu (avec son texte)
  const [working, setWorking] = useState(false);
  const k = encodeURIComponent(tokens.admin(slug) || "");

  const load = async () => {
    try { setData(await api(`/events/${slug}/versions`, { slug })); } catch (e) { onToast(e.message); }
  };
  useEffect(() => { load(); }, [slug, refresh]);

  const run = async (fn, msg) => {
    setWorking(true);
    try { await fn(); if (msg) onToast(msg); await load(); } catch (e) { onToast(e.message); }
    setWorking(false);
  };
  const save = () => {
    const label = prompt("Nom de cette version (par exemple « Version drôle pour le groupe ») :", "");
    if (label === null) return;
    run(async () => { await beforeSave(); await api(`/events/${slug}/versions`, { slug, method: "POST", body: { label } }); }, "Version enregistrée");
  };
  const restore = (v) => {
    if (data.dirty && !confirm("Le brouillon a des modifications qui ne sont dans aucune version. Les remplacer par cette version ?\n\n(Annule puis « Enregistrer comme version » pour les garder.)")) return;
    run(async () => {
      await api(`/events/${slug}/versions/${v.id}/restore`, { slug, method: "POST" });
      setView(null);
      await onRestored();
    }, `« ${v.label} » reprise dans le brouillon (ton : ${v.tone_label.toLowerCase()})`);
  };
  const rename = (v) => {
    const label = prompt("Nouveau nom :", v.label);
    if (!label || label === v.label) return;
    run(() => api(`/events/${slug}/versions/${v.id}`, { slug, method: "PUT", body: { label } }), "Version renommée");
  };
  const remove = (v) => {
    if (!confirm(`Supprimer la version « ${v.label} » ? Son texte, son film et son album seront effacés.${v.published ? "\n\nCe que voit le groupe ne change pas." : ""}`)) return;
    run(() => api(`/events/${slug}/versions/${v.id}`, { slug, method: "DELETE" }), "Version supprimée");
  };
  const open = (v) => run(async () => setView(await api(`/events/${slug}/versions/${v.id}`, { slug })));

  if (!data) return null;
  const file = (v, name) => `/api/events/${slug}/versions/${v.id}/${name}?k=${k}`;
  const off = busy || working;

  return (
    <section className="card">
      <div className="card-head">
        <h2>Versions ({data.versions.length})</h2>
        <button className="btn" onClick={save} disabled={off || !data.has_draft}>💾 Enregistrer comme version</button>
      </div>
      <p className="muted small">
        Chaque génération est gardée ici. Pour essayer un autre ton : change-le dans les réglages (écran Générer), régénère, puis compare.
        « Reprendre » remet une version dans le brouillon, avec son ton ; c'est le brouillon qui est publié.
        {data.dirty ? " Le brouillon actuel a des modifications qui ne sont dans aucune version : elles seront gardées automatiquement avant une nouvelle génération ou une publication." : ""}
      </p>
      {data.versions.length === 0 && <p className="muted">Aucune version pour l'instant.</p>}
      <ul className="versions">
        {data.versions.map((v) => (
          <li key={v.id} className={v.current ? "current" : ""}>
            <div className="v-main">
              <strong>{v.label}</strong>
              <span className="muted small">
                {v.tone_label} · {when(v.created_at)} · {ORIGIN[v.origin] || v.origin}
                {v.has_video ? " · 🎬" : ""}{v.has_album ? " · 📕" : ""}
              </span>
              <span className="v-badges">
                {v.current && <span className="badge">{data.dirty ? "Brouillon (modifié depuis)" : "Dans le brouillon"}</span>}
                {v.published && <span className="badge ok">Publiée</span>}
              </span>
            </div>
            <div className="row">
              <button className="btn" onClick={() => open(v)} disabled={working}>Aperçu</button>
              {!(v.current && !data.dirty) && <button className="btn" onClick={() => restore(v)} disabled={off}>Reprendre</button>}
              <button className="link" onClick={() => rename(v)} disabled={working}>Renommer</button>
              <button className="link danger" onClick={() => remove(v)} disabled={off}>Supprimer</button>
            </div>
          </li>
        ))}
      </ul>
      {view && (
        <div className="modal" onClick={() => setView(null)}>
          <div className="sheet wide" onClick={(e) => e.stopPropagation()}>
            <div className="card-head">
              <h2>{view.label}</h2>
              <button className="btn" onClick={() => setView(null)}>Fermer</button>
            </div>
            <p className="muted small">{view.tone_label} · {view.type_label} · {when(view.created_at)}</p>
            {view.has_video && <video controls playsInline preload="metadata" src={file(view, "video.mp4") + "#t=1.2"} />}
            {view.has_album && <p><a className="btn" href={file(view, "album.pdf")} target="_blank" rel="noreferrer">📕 Ouvrir l'album (PDF)</a></p>}
            <div className="v-text"><Markdown text={view.text_md} /></div>
            <div className="row">
              {!(view.current && !data.dirty) && <button className="btn primary big" onClick={() => restore(view)} disabled={off}>Reprendre cette version</button>}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
