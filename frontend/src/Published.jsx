import React, { useEffect, useState } from "react";
import { api, fmtDates } from "./api.js";
import Markdown from "./Markdown.jsx";

export default function Published({ slug, ev }) {
  const [pub, setPub] = useState(null);
  const [view, setView] = useState(null);
  useEffect(() => {
    const load = () => api(`/events/${slug}/published`).then(setPub).catch(() => {});
    load();
    const t = setInterval(() => !document.hidden && load(), 30000);
    return () => clearInterval(t);
  }, [slug]);

  if (!pub) return <p className="muted center">Chargement…</p>;
  if (!pub.published) {
    return (
      <div className="narrow-col"><div className="card center">
        <div className="hero-mark">⏳</div>
        <h2>Le souvenir n'est pas encore publié</h2>
        <p className="muted">{ev.is_admin ? "Génère le compte rendu, relis-le, puis publie-le : il apparaîtra ici pour tout le groupe." : "L'organisateur le prépare. Reviens avec le même lien : le récit, le film et l'album apparaîtront ici."}</p>
      </div></div>
    );
  }
  const base = `/api/events/${slug}`;
  const v = `?v=${pub.version}`;
  return (
    <div className="souvenir">
      <p className="kicker">{fmtDates(ev.start_date, ev.end_date)} · {ev.type_label}</p>
      {pub.has_video && (
        <section className="film">
          <video controls playsInline preload="metadata" src={`${base}/out/published/video.mp4${v}#t=1.2`} />
        </section>
      )}
      <Markdown text={pub.text_md} />
      {pub.has_album && (
        <section className="album-cta">
          <div>
            <h2>L'album photo</h2>
            <p className="muted">Un PDF A4 paysage, prêt à imprimer ou à feuilleter.</p>
          </div>
          <a className="btn primary big" href={`${base}/out/published/album.pdf${v}`} download>📕 Télécharger l'album (PDF)</a>
        </section>
      )}
      {!ev.raw_purged && (
        <section className="album-cta">
          <div>
            <h2>Tous les fichiers du souvenir</h2>
            <p className="muted">
              Les photos, vidéos, dictées et conversations d'origine, les notes et transcriptions, avec le récit, le film et l'album, dans une seule archive ZIP.
              {ev.raw_purge_on && ` Les fichiers d'origine seront effacés du serveur le ${new Date(ev.raw_purge_on + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })} : pense à les récupérer avant.`}
            </p>
          </div>
          <a className="btn big" href={`${base}/download-souvenir`} download>📦 Télécharger tout (ZIP)</a>
        </section>
      )}
      {pub.photos.length > 0 && (
        <section>
          <h2>Les photos</h2>
          <div className="gallery">
            {pub.photos.map((id) => (
              <button key={id} onClick={() => setView(id)} aria-label="Agrandir la photo">
                <img src={`${base}/published/photos/${id}_t.jpg${v}`} alt="" loading="lazy" />
              </button>
            ))}
          </div>
        </section>
      )}
      {view && (
        <div className="lightbox" onClick={() => setView(null)}>
          <img src={`${base}/published/photos/${view}.jpg${v}`} alt="" />
          <button className="lightbox-close" aria-label="Fermer">✕</button>
        </div>
      )}
    </div>
  );
}
