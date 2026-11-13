import React, { useEffect, useRef, useState } from "react";
import { api, mediaUrl, fmtTime, fmtDur, KIND, uid } from "./api.js";
import * as queue from "./queue.js";
import { Toast } from "./App.jsx";

function pickMime() {
  const c = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm", "audio/ogg"];
  return c.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
}

function Recorder({ kind, onDone, onCancel }) {
  const [sec, setSec] = useState(0);
  const [err, setErr] = useState("");
  const ref = useRef({});
  useEffect(() => {
    let stopped = false;
    const r = ref.current;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: kind === "conversation" ? { echoCancellation: false, noiseSuppression: false, autoGainControl: true } : true,
        });
        if (stopped) { stream.getTracks().forEach((t) => t.stop()); return; }
        const mime = pickMime();
        const rec = new MediaRecorder(stream, { ...(mime ? { mimeType: mime } : {}), audioBitsPerSecond: kind === "conversation" ? 96000 : 64000 });
        r.stream = stream; r.rec = rec; r.chunks = []; r.start = Date.now(); r.at = new Date().toISOString();
        rec.ondataavailable = (e) => e.data.size && r.chunks.push(e.data);
        rec.start(1000);
        r.timer = setInterval(() => setSec(Math.floor((Date.now() - r.start) / 1000)), 500);
        try { r.lock = await navigator.wakeLock?.request("screen"); } catch {}
      } catch {
        setErr("Impossible d'accéder au micro. Autorise le micro pour ce site dans les réglages du navigateur.");
      }
    })();
    return () => {
      stopped = true;
      clearInterval(r.timer);
      r.lock?.release?.().catch(() => {});
      if (r.rec && r.rec.state !== "inactive") r.rec.stop();
      r.stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const stop = () => {
    const r = ref.current;
    if (!r.rec) return onCancel();
    r.rec.onstop = () => {
      const type = (r.rec.mimeType || "audio/webm").split(";")[0];
      onDone(new Blob(r.chunks, { type }), r.at);
    };
    r.rec.stop();
  };

  return (
    <div className="recorder" role="dialog" aria-label="Enregistrement en cours">
      {err ? (
        <>
          <p className="error">{err}</p>
          <button className="btn big" onClick={onCancel}>Fermer</button>
        </>
      ) : (
        <>
          <div className="rec-light"><span className="dot" />Enregistrement en cours</div>
          <div className="rec-kind">{KIND[kind].icon} {KIND[kind].label}</div>
          <div className="rec-time" aria-live="off">{fmtDur(sec)}</div>
          <p className="rec-hint">{kind === "conversation" ? "Pose le téléphone au milieu du groupe. Préviens les personnes présentes qu'elles sont enregistrées." : "Raconte ce qui se passe, comme à un ami."}</p>
          <button className="rec-stop" onClick={stop}>■ Arrêter et envoyer</button>
          <button className="link light" onClick={onCancel}>Annuler sans garder</button>
        </>
      )}
    </div>
  );
}

function Lightbox({ slug, item, onClose }) {
  return (
    <div className="lightbox" onClick={onClose}>
      {item.kind === "video"
        ? <video src={mediaUrl(slug, item.id, "raw")} controls autoPlay playsInline onClick={(e) => e.stopPropagation()} />
        : <img src={mediaUrl(slug, item.id, "display")} alt={`Photo de ${item.author}`} />}
      <button className="lightbox-close" aria-label="Fermer">✕</button>
    </div>
  );
}

export default function Capture({ slug, ev, onEvent }) {
  const [items, setItems] = useState(null);
  const [rec, setRec] = useState(null);
  const [note, setNote] = useState(null);
  const [pend, setPend] = useState([]);
  const [toast, setToast] = useState("");
  const [view, setView] = useState(null);
  const inputs = { photo: useRef(), video: useRef(), any: useRef() };

  const load = async () => {
    try {
      const r = await api(`/events/${slug}/feed`, { slug });
      setItems(r.items);
      onEvent((e) => ({ ...e, ...r.event, me: e.me }));
    } catch {}
  };
  useEffect(() => {
    load();
    const t = setInterval(() => !document.hidden && load(), 8000);
    const refresh = () => queue.pending(slug).then((p) => { setPend(p); if (!p.length) load(); });
    const un = queue.subscribe(refresh);
    refresh();
    queue.kick();
    return () => { clearInterval(t); un(); };
  }, [slug]);

  const add = async (entry, msg) => {
    await queue.enqueue({ cid: uid(), slug, ...entry });
    setToast(msg);
  };
  const onFiles = (kind) => async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    for (const f of files) {
      const k = kind || (f.type.startsWith("video") ? "video" : f.type.startsWith("image") ? "photo" : f.type.startsWith("audio") ? "dictee" : null);
      if (!k) continue;
      const imported = !kind;
      await add({
        type: "file", kind: k, blob: f, filename: f.name, mime: f.type || (k === "photo" ? "image/jpeg" : "video/mp4"), size: f.size,
        captured_at: new Date(imported && f.lastModified ? f.lastModified : Date.now()).toISOString(),
        source: imported ? "import" : "capture",
      }, files.length > 1 ? `${files.length} fichiers ajoutés` : `${KIND[k].label} ajoutée ✓`);
    }
  };
  const remove = async (it) => {
    if (!confirm("Supprimer définitivement ce souvenir ?")) return;
    try { await api(`/events/${slug}/items/${it.id}`, { slug, method: "DELETE" }); load(); } catch (e) { setToast(e.message); }
  };

  const sending = pend.filter((p) => p.state !== "erreur");
  const failed = pend.filter((p) => p.state === "erreur");
  const total = sending.reduce((a, p) => a + p.size, 0), sent = sending.reduce((a, p) => a + (p.sent || 0), 0);

  return (
    <div className="capture">
      <div className="buttons">
        <button className="cap dictee" onClick={() => setRec("dictee")}><span>🎙️</span>Dictée</button>
        <button className="cap conversation" onClick={() => setRec("conversation")}><span>💬</span>Conversation</button>
        <button className="cap video" onClick={() => inputs.video.current.click()}><span>🎥</span>Vidéo</button>
        <button className="cap photo" onClick={() => inputs.photo.current.click()}><span>📷</span>Photo</button>
        <button className="cap note" onClick={() => setNote("")}><span>✏️</span>Note</button>
      </div>
      <button className="link center" onClick={() => inputs.any.current.click()}>Importer des photos ou vidéos déjà prises</button>
      <input ref={inputs.photo} type="file" accept="image/*" capture="environment" hidden onChange={onFiles("photo")} />
      <input ref={inputs.video} type="file" accept="video/*" capture="environment" hidden onChange={onFiles("video")} />
      <input ref={inputs.any} type="file" accept="image/*,video/*" multiple hidden onChange={onFiles(null)} />

      {sending.length > 0 && (
        <div className="pending" role="status">
          <div>⏫ {sending.length} envoi{sending.length > 1 ? "s" : ""} en cours{navigator.onLine ? "" : " — en attente de réseau"}</div>
          <progress value={total ? sent / total : 0} max="1" />
          <div className="muted small">Tes souvenirs sont gardés sur le téléphone jusqu'à l'envoi complet.</div>
        </div>
      )}
      {failed.map((p) => (
        <div className="pending bad" key={p.cid}>
          <div>⚠️ {KIND[p.kind].label} refusée : {p.error}</div>
          <button className="link" onClick={() => queue.discard(p.cid)}>Abandonner cet envoi</button>
        </div>
      ))}

      <h2 className="feed-title">Derniers souvenirs du groupe</h2>
      {items && items.length === 0 && <p className="muted center">Rien pour l'instant. À toi d'ouvrir le carnet !</p>}
      <ul className="feed">
        {(items || []).map((it) => (
          <li key={it.id} className={`item ${it.kind}`}>
            <div className="item-head">
              <span className="who">{KIND[it.kind].icon} {it.author}</span>
              <span className="muted small">{fmtTime(it.captured_at)}</span>
            </div>
            {it.status === "processing" && <p className="muted small">Préparation en cours…</p>}
            {it.status === "error" && <p className="error small">{it.text}</p>}
            {it.kind === "note" && <p className="note-text">{it.text}</p>}
            {it.has_thumb && (
              <button className="thumb" onClick={() => setView(it)} aria-label={`Ouvrir la ${KIND[it.kind].label.toLowerCase()} de ${it.author}`}>
                <img src={mediaUrl(slug, it.id, "thumb")} alt="" loading="lazy" />
                {it.kind === "video" && <span className="play">▶ {fmtDur(it.duration)}</span>}
              </button>
            )}
            {(it.kind === "dictee" || it.kind === "conversation") && it.status === "ready" && (
              <audio controls preload="none" src={mediaUrl(slug, it.id, "raw")} />
            )}
            {it.mine && <button className="link danger" onClick={() => remove(it)}>Supprimer</button>}
          </li>
        ))}
      </ul>

      {rec && (
        <Recorder kind={rec} onCancel={() => setRec(null)} onDone={(blob, at) => {
          const k = rec;
          setRec(null);
          if (blob.size < 800) return setToast("Enregistrement trop court, rien n'a été gardé.");
          add({ type: "file", kind: k, blob, filename: `${k}.${blob.type.includes("mp4") ? "m4a" : "webm"}`, mime: blob.type, size: blob.size, captured_at: at, source: "capture" }, `${KIND[k].label} ajoutée ✓`);
        }} />
      )}
      {note !== null && (
        <div className="modal" onClick={() => setNote(null)}>
          <form className="sheet" onClick={(e) => e.stopPropagation()} onSubmit={(e) => {
            e.preventDefault();
            if (!note.trim()) return;
            add({ type: "note", kind: "note", text: note.trim(), captured_at: new Date().toISOString() }, "Note ajoutée ✓");
            setNote(null);
          }}>
            <h2>✏️ Note</h2>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={5} autoFocus maxLength={5000} placeholder="Une anecdote, un chrono, une phrase entendue…" />
            <div className="row">
              <button type="button" className="btn big" onClick={() => setNote(null)}>Annuler</button>
              <button className="btn primary big" disabled={!note.trim()}>Ajouter</button>
            </div>
          </form>
        </div>
      )}
      {view && <Lightbox slug={slug} item={view} onClose={() => setView(null)} />}
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}
