import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, mediaUrl, tokens, fmtTime, fmtDur, KIND } from "./api.js";
import Markdown from "./Markdown.jsx";
import Versions from "./Versions.jsx";
import { useJob, JobProgress } from "./Generate.jsx";
import MusicPreview from "./MusicPreview.jsx";
import { Toast } from "./App.jsx";

const SEG = { title: "🔤 Titre", photo: "📷 Photo", video: "🎥 Extrait" };

export default function Review({ slug, ev, reload, goGenerate }) {
  const [d, setD] = useState(null);
  const [text, setText] = useState("");
  const [saved, setSaved] = useState(true);
  const [preview, setPreview] = useState(false);
  const [adding, setAdding] = useState(false);
  const [toast, setToast] = useState("");
  const [stamp, setStamp] = useState(Date.now());
  const [changing, setChanging] = useState(false); // « Changer la musique » ouvert
  const [newMusic, setNewMusic] = useState(undefined);
  const timer = useRef();
  const k = encodeURIComponent(tokens.admin(slug) || "");

  const load = useCallback(async (keepText) => {
    try {
      const r = await api(`/events/${slug}/draft`, { slug });
      setD(r);
      if (!keepText) { setText(r.text_md); setSaved(true); }
    } catch (e) { setToast(e.message); }
  }, [slug]);
  const [job, active] = useJob(slug, () => { setStamp(Date.now()); load(false); });
  useEffect(() => { load(false); }, [load]);

  const save = async (value = text) => {
    clearTimeout(timer.current);
    try { await api(`/events/${slug}/draft`, { slug, method: "PUT", body: { text_md: value } }); setSaved(true); }
    catch (e) { setToast(e.message); }
  };
  const edit = (v) => {
    setText(v); setSaved(false);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => save(v), 1500);
  };
  const act = async (fn, okMsg) => {
    try { if (!saved) await save(); await fn(); if (okMsg) setToast(okMsg); await load(true); }
    catch (e) { setToast(e.message); }
  };
  const regen = (part, label) => {
    if (part === "text" && !confirm("Régénérer le texte remplacera tes corrections. Continuer ?")) return;
    act(() => api(`/events/${slug}/generate`, { slug, method: "POST", body: { parts: [part], video_duration: d.video_duration } }), `${label} : régénération lancée`);
  };
  const changeMusic = () => {
    const body = { parts: ["music"] };
    if (newMusic && !newMusic.error) body.music = { main_id: newMusic.main ? newMusic.main.id : null, final_id: newMusic.final ? newMusic.final.id : null };
    setChanging(false);
    act(() => api(`/events/${slug}/generate`, { slug, method: "POST", body }), "Musique : changement lancé");
  };
  const select = (id, selected) => act(() => api(`/events/${slug}/draft/selection`, { slug, method: "POST", body: { item_id: id, selected } }),
    selected ? "Photo ajoutée, l'album se met à jour" : "Photo retirée, l'album et le film se mettent à jour");
  const exclude = (it) => act(() => api(`/events/${slug}/items/${it.id}/exclude`, { slug, method: "POST", body: { excluded: !it.excluded } }),
    it.excluded ? "Passage réintégré (régénère pour l'utiliser)" : "Passage écarté");
  const publish = () => act(async () => { await api(`/events/${slug}/publish`, { slug, method: "POST" }); reload(); }, "Publié ! Le groupe voit cette version avec le même lien.");

  if (!d) return <p className="muted center">Chargement…</p>;
  if (!d.text_md && !active && !d.segments.length) {
    return (
      <div className="narrow-col"><div className="card center">
        <div className="hero-mark">📝</div>
        <h2>Rien à relire pour l'instant</h2>
        <p className="muted">Lance d'abord la génération du compte rendu.</p>
        <button className="btn primary big" onClick={goGenerate}>Aller à la génération</button>
      </div></div>
    );
  }
  const busy = active || d.busy;
  const byId = Object.fromEntries(d.items.map((i) => [i.id, i]));
  const selected = d.selection.map((id) => byId[id]).filter(Boolean);
  const others = d.items.filter((i) => i.kind === "photo" && i.status === "ready" && !d.selection.includes(i.id));
  const spoken = d.items.filter((i) => i.kind !== "photo");
  const out = (name) => `/api/events/${slug}/out/draft/${name}?k=${k}&t=${stamp}`;

  return (
    <div className="review">
      {busy && job && <JobProgress job={job} />}
      {job && job.status === "error" && <div className="card"><p className="error">La dernière génération a échoué : {job.message}</p></div>}
      {d.ai_mode === "local" && <div className="card warn">Aucune clé API Claude n'est configurée : ce brouillon a été assemblé sans IA (simple mise bout à bout). Ajoute <code>ANTHROPIC_API_KEY</code> puis régénère.</div>}

      <Versions slug={slug} busy={busy} onToast={setToast} published={ev.published}
        refresh={`${stamp}|${saved}|${d.pub_version}|${d.selection.join(",")}|${d.segments.length}`}
        beforeSave={() => (saved ? null : save())}
        onRestored={async () => { await load(false); setStamp(Date.now()); reload(); }} />

      <div className="review-grid">
        <section className="card">
          <div className="card-head">
            <h2>Le texte</h2>
            <div className="row">
              <span className="muted small">{saved ? "Enregistré" : "Modifications en cours…"}</span>
              <button className="btn" onClick={() => setPreview(!preview)}>{preview ? "Modifier" : "Aperçu"}</button>
              <button className="btn" onClick={() => regen("text", "Texte")} disabled={busy}>Régénérer</button>
            </div>
          </div>
          {preview ? <Markdown text={text} /> : (
            <textarea className="editor" value={text} onChange={(e) => edit(e.target.value)} onBlur={() => !saved && save()} spellCheck lang="fr" aria-label="Texte du compte rendu" />
          )}
          <p className="muted small">Mise en forme : <code># Titre</code>, <code>## Section</code>, <code>**gras**</code>, <code>&gt; citation</code>.</p>
        </section>

        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h2>Le film</h2>
              <button className="btn" onClick={() => regen("video", "Film")} disabled={busy}>Régénérer</button>
            </div>
            {d.video_prompt && <p className="muted small">Consignes : « {d.video_prompt.length > 160 ? d.video_prompt.slice(0, 160) + "…" : d.video_prompt} » <button className="link" onClick={goGenerate}>Modifier</button></p>}
            {d.video_ready ? <video key={stamp} controls playsInline preload="metadata" src={out("video.mp4") + "#t=1.2"} /> : <p className="muted">{busy ? "Montage en cours…" : "Pas encore de film."}</p>}
            {d.video_ready && !changing && (
              <p><button className="btn" onClick={() => { setNewMusic(undefined); setChanging(true); }} disabled={busy}>🎵 Changer la musique</button></p>
            )}
            {changing && (
              <div className="change-music">
                <MusicPreview slug={slug} tones={ev.tones} settings={d.video_settings} disabled={busy} onChange={setNewMusic} />
                <p className="muted small">Seule la bande-son change : les plans, le texte et l'album restent les mêmes. Pour changer de genre, d'énergie ou de fin, passe par l'écran Générer.</p>
                <div className="row">
                  <button className="btn" onClick={() => setChanging(false)}>Annuler</button>
                  <button className="btn primary" onClick={changeMusic} disabled={busy || newMusic === undefined}>Utiliser cette musique</button>
                </div>
              </div>
            )}
            {d.segments.length > 0 && (
              <details>
                <summary>Plan de montage ({d.segments.length} plans, {fmtDur(d.segments.reduce((a, s) => a + s.duration, 0))})</summary>
                <ol className="segments">
                  {d.segments.map((s) => (
                    <li key={s.index}>
                      {s.item_id && byId[s.item_id]?.has_thumb ? <img src={mediaUrl(slug, s.item_id, "thumb")} alt="" loading="lazy" /> : <span className="seg-title">T</span>}
                      <div>
                        <div>{SEG[s.type]} · {s.duration.toFixed(1)} s{s.author ? ` · ${s.author}` : ""}</div>
                        {s.text && <div className="muted small">{s.text}</div>}
                      </div>
                      <button className="link danger" onClick={() => act(() => api(`/events/${slug}/draft/segments/${s.index}/remove`, { slug, method: "POST" }), "Plan retiré, le film se met à jour")} disabled={busy}>Retirer</button>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>L'album</h2>
              <button className="btn" onClick={() => regen("album", "Album")} disabled={busy}>Régénérer</button>
            </div>
            {d.album_ready
              ? <p><a className="btn" href={out("album.pdf")} target="_blank" rel="noreferrer">📕 Ouvrir l'aperçu PDF</a> <span className="muted small">{d.album_pages} pages · A4 paysage</span></p>
              : <p className="muted">{busy ? "Mise en page en cours…" : "Pas encore d'album."}</p>}
            {d.album_ready && <iframe className="pdf" key={stamp} title="Aperçu de l'album" src={out("album.pdf") + "#view=FitH"} />}
          </section>
        </div>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Photos retenues ({selected.length})</h2>
          {others.length > 0 && <button className="btn" onClick={() => setAdding(!adding)}>{adding ? "Fermer" : `Ajouter des photos (${others.length})`}</button>}
        </div>
        <p className="muted small">Ces photos composent l'album et la galerie publiée. Retirer une photo l'enlève aussi du film.</p>
        <div className="gallery edit">
          {selected.map((it) => (
            <figure key={it.id}>
              <img src={mediaUrl(slug, it.id, "thumb")} alt={`Photo de ${it.author}`} loading="lazy" />
              <figcaption>{it.author}<button className="link danger" onClick={() => select(it.id, false)} disabled={busy}>Retirer</button></figcaption>
            </figure>
          ))}
        </div>
        {adding && (
          <>
            <h3>Photos non retenues</h3>
            <div className="gallery edit">
              {others.map((it) => (
                <figure key={it.id} className={it.excluded ? "off" : ""}>
                  <img src={mediaUrl(slug, it.id, "thumb")} alt={`Photo de ${it.author}`} loading="lazy" />
                  <figcaption>{it.author}<button className="link" onClick={() => select(it.id, true)} disabled={busy}>Ajouter</button></figcaption>
                </figure>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="card">
        <details>
          <summary><h2 className="inline">Paroles, notes et vidéos ({spoken.length})</h2></summary>
          <p className="muted small">Écarte un passage pour qu'il ne soit plus utilisé : il est retiré du film tout de suite, et du texte à la prochaine régénération.</p>
          <ul className="passages">
            {spoken.map((it) => (
              <li key={it.id} className={it.excluded ? "off" : ""}>
                <div className="item-head">
                  <span className="who">{KIND[it.kind].icon} {it.author}{it.duration ? ` · ${fmtDur(it.duration)}` : ""}</span>
                  <span className="muted small">{fmtTime(it.captured_at)}</span>
                </div>
                <p>{it.kind === "note" ? it.text : it.transcript || <span className="muted">(pas encore transcrit)</span>}</p>
                <button className={`link ${it.excluded ? "" : "danger"}`} onClick={() => exclude(it)}>{it.excluded ? "Réintégrer" : "Écarter ce passage"}</button>
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section className="card">
        <h2>Conservation</h2>
        <p className="muted">
          {ev.raw_purged ? "Les fichiers bruts ont été supprimés. Le récit, le film et l'album publiés sont conservés sans limite."
            : ev.raw_purge_on ? `Les fichiers bruts (photos, vidéos et audios d'origine) seront supprimés automatiquement le ${new Date(ev.raw_purge_on + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })}. Le récit, le film et l'album sont conservés sans limite.`
            : "Les fichiers bruts sont supprimés automatiquement 3 mois après la publication ; les résultats sont conservés sans limite."}
        </p>
        {!ev.raw_purged && <a className="btn" href={`/api/events/${slug}/download-all?k=${k}`}>⬇️ Tout télécharger (ZIP)</a>}
      </section>

      <div className="publish-bar">
        <div>
          <strong>{d.published ? `Publié · version ${d.pub_version}` : "Brouillon — visible par toi seul"}</strong>
          <div className="muted small">{d.published ? "Publie à nouveau pour mettre à jour ce que voit le groupe." : "Le groupe ne voit rien avant la publication."}</div>
        </div>
        <button className="btn primary big" onClick={publish} disabled={busy || !text.trim()}>{d.published ? "Publier les modifications" : "Publier"}</button>
      </div>
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}
