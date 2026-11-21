import React, { useEffect, useState } from "react";
import { api, fmtDates, mediaUrl } from "./api.js";
import Markdown from "./Markdown.jsx";
import Film from "./Film.jsx";

// Crédit des morceaux du film (licence CC BY : obligatoire), sous le lecteur.
export function MusicCredits({ credits }) {
  if (!credits || !credits.length) return null;
  return <p className="credits muted small">{credits.map((c) => <span key={c}>{c}</span>)}</p>;
}

export default function Published({ slug, ev }) {
  const [pub, setPub] = useState(null);
  const [view, setView] = useState(null);
  const [pick, setPick] = useState(() => { try { return +localStorage.getItem(`sv:${slug}:version`) || 0; } catch { return 0; } });
  const [alt, setAlt] = useState(null); // contenu d'une autre version proposée au groupe
  useEffect(() => {
    const load = () => api(`/events/${slug}/published`).then(setPub).catch(() => {});
    load();
    const t = setInterval(() => !document.hidden && load(), 30000);
    return () => clearInterval(t);
  }, [slug]);

  const options = (pub && pub.versions) || [];
  const chosen = options.some((o) => o.id === pick) ? pick : 0;
  useEffect(() => {
    try { localStorage.setItem(`sv:${slug}:version`, String(chosen)); } catch {}
    setAlt(null);
    if (chosen) api(`/events/${slug}/published/versions/${chosen}`).then(setAlt).catch(() => setPick(0));
  }, [slug, chosen]);

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
  // contenu affiché : la version publiée, ou une autre version proposée au groupe
  const c = chosen && alt ? {
    text_md: alt.text_md, has_video: alt.has_video, has_album: alt.has_album, credits: alt.music_credits || [],
    video: `${base}/published/versions/${alt.id}/video.mp4`, album: `${base}/published/versions/${alt.id}/album.pdf`,
    photos: alt.photos.map((id) => ({ id, thumb: mediaUrl(slug, id, "thumb"), full: mediaUrl(slug, id, "display") })),
  } : {
    text_md: pub.text_md, has_video: pub.has_video, has_album: pub.has_album, credits: pub.music_credits || [],
    video: `${base}/out/published/video.mp4${v}`, album: `${base}/out/published/album.pdf${v}`,
    photos: pub.photos.map((id) => ({ id, thumb: `${base}/published/photos/${id}_t.jpg${v}`, full: `${base}/published/photos/${id}.jpg${v}` })),
  };
  return (
    <div className="souvenir">
      <p className="kicker">{fmtDates(ev.start_date, ev.end_date)} · {ev.type_label}</p>
      {options.length > 1 && (
        <nav className="version-pick" aria-label="Choisir une version du souvenir">
          <span className="muted small">Plusieurs versions : choisis la tienne</span>
          <div className="chips">
            {options.map((o) => (
              <button key={o.id} className={`chip${o.id === chosen ? " on" : ""}`} aria-pressed={o.id === chosen} onClick={() => setPick(o.id)}>
                {o.label}{o.main ? " ★" : ""}
              </button>
            ))}
          </div>
        </nav>
      )}
      {chosen !== 0 && !alt ? <p className="muted center">Chargement de la version…</p> : <>
      {c.has_video && (
        <section className="film">
          <Film key={c.video} src={`${c.video}#t=1.2`} />
          <MusicCredits credits={c.credits} />
        </section>
      )}
      <Markdown text={c.text_md} />
      {c.has_album && (
        <section className="album-cta">
          <div>
            <h2>L'album photo</h2>
            <p className="muted">Un PDF A4 paysage, prêt à imprimer ou à feuilleter.</p>
          </div>
          <a className="btn primary big" href={c.album} download>📕 Télécharger l'album (PDF)</a>
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
      {c.photos.length > 0 && (
        <section>
          <h2>Les photos</h2>
          <div className="gallery">
            {c.photos.map((p) => (
              <button key={p.id} onClick={() => setView(p.full)} aria-label="Agrandir la photo">
                <img src={p.thumb} alt="" loading="lazy" />
              </button>
            ))}
          </div>
        </section>
      )}
      </>}
      {view && (
        <div className="lightbox" onClick={() => setView(null)}>
          <img src={view} alt="" />
          <button className="lightbox-close" aria-label="Fermer">✕</button>
        </div>
      )}
    </div>
  );
}
