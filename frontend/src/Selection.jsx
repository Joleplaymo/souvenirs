// Vérification avant génération : l'organisateur retire des photos ou des vidéos et contrôle leur date.
// Un élément retiré n'est utilisé ni pour le récit, ni pour le film, ni pour l'album (il reste dans le fil).
import React, { useEffect, useMemo, useState } from "react";
import { api, mediaUrl, fmtDur, KIND } from "./api.js";

// Date et heure d'un instant à l'heure de l'événement (et non du téléphone qui consulte).
function inTz(iso, tz) {
  const p = {};
  new Intl.DateTimeFormat("fr-FR", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(iso)).forEach(({ type, value }) => { p[type] = value; });
  return { day: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}`, local: `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}` };
}
function dayLabel(day) {
  return new Date(`${day}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

export default function Selection({ slug, ev, disabled, onToast }) {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(0);
  const [editing, setEditing] = useState(null); // { it, value }
  const [open, setOpen] = useState(false);
  const tz = ev.tz || "Europe/Paris";

  const load = async () => {
    try {
      const r = await api(`/events/${slug}/draft`, { slug });
      setItems(r.items.filter((it) => (it.kind === "photo" || it.kind === "video") && it.status === "ready"));
    } catch (e) { onToast(e.message); }
  };
  useEffect(() => { load(); }, [slug]);

  const days = useMemo(() => {
    const out = new Map();
    for (const it of [...(items || [])].sort((a, b) => (a.captured_at < b.captured_at ? -1 : a.captured_at > b.captured_at ? 1 : a.id - b.id))) {
      const t = inTz(it.captured_at, tz);
      if (!out.has(t.day)) out.set(t.day, []);
      out.get(t.day).push({ ...it, t });
    }
    return [...out.entries()];
  }, [items, tz]);

  if (!items || !items.length) return null;
  const kept = items.filter((it) => !it.excluded).length;
  const outside = (day) => day < ev.start_date || day > ev.end_date;
  const nOutside = days.filter(([day]) => outside(day)).reduce((a, [, list]) => a + list.length, 0);

  const toggle = async (it) => {
    setBusy(it.id);
    try {
      await api(`/events/${slug}/items/${it.id}/exclude`, { slug, method: "POST", body: { excluded: !it.excluded } });
      setItems((list) => list.map((x) => (x.id === it.id ? { ...x, excluded: !it.excluded } : x)));
    } catch (e) { onToast(e.message); }
    setBusy(0);
  };
  const saveTime = async (e) => {
    e.preventDefault();
    const { it, value } = editing;
    try {
      const r = await api(`/events/${slug}/items/${it.id}/time`, { slug, method: "POST", body: { local: value } });
      setItems((list) => list.map((x) => (x.id === it.id ? { ...x, captured_at: r.captured_at } : x)));
      setEditing(null);
      onToast("Date corrigée");
    } catch (err) { onToast(err.message); }
  };

  return (
    <section className="card">
      <div className="card-head">
        <h2>Photos et vidéos ({kept}/{items.length})</h2>
        <button className="btn" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Fermer" : "Vérifier et trier"}</button>
      </div>
      <p className="muted small">
        Retire ce qui ne doit pas servir : une photo ou une vidéo retirée n'est utilisée ni dans le récit, ni dans le film, ni dans l'album
        (elle reste visible dans le fil du groupe). Vérifie aussi les dates : elles décident de l'ordre du film. Touche une date pour la corriger.
      </p>
      {nOutside > 0 && <p className="error small">⚠️ {nOutside} élément{nOutside > 1 ? "s" : ""} daté{nOutside > 1 ? "s" : ""} hors des jours de l'événement : vérifie {nOutside > 1 ? "leurs dates" : "sa date"}.</p>}
      {open && days.map(([day, list]) => (
        <div key={day} className="sel-day">
          <h3 className={outside(day) ? "error" : ""}>{dayLabel(day)}{outside(day) ? " — hors de l'événement" : ""}</h3>
          <ul className="sel-grid">
            {list.map((it) => (
              <li key={it.id} className={it.excluded ? "off" : ""}>
                <div className="sel-thumb">
                  <img src={mediaUrl(slug, it.id, "thumb")} alt={`${KIND[it.kind].label} de ${it.author}`} loading="lazy" />
                  {it.kind === "video" && <span className="sel-dur">▶ {fmtDur(it.duration)}</span>}
                  {it.excluded && <span className="sel-badge">Retirée</span>}
                </div>
                <button className="sel-time" onClick={() => setEditing({ it, value: it.t.local })} disabled={disabled}
                  aria-label={`Corriger la date, actuellement ${dayLabel(it.t.day)} à ${it.t.time}`}>
                  🕑 {it.t.time} <span aria-hidden>✎</span>
                </button>
                <div className="muted small sel-who">{it.author}</div>
                <button className={`link ${it.excluded ? "" : "danger"}`} onClick={() => toggle(it)} disabled={disabled || busy === it.id}>
                  {it.excluded ? "Remettre" : "Retirer"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {editing && (
        <div className="modal" onClick={() => setEditing(null)}>
          <form className="sheet" onClick={(e) => e.stopPropagation()} onSubmit={saveTime}>
            <h2>Date et heure</h2>
            <img className="sel-preview" src={mediaUrl(slug, editing.it.id, "thumb")} alt="" />
            <label>Prise le (heure de l'événement)
              <input type="datetime-local" value={editing.value} required autoFocus
                onChange={(e) => setEditing({ ...editing, value: e.target.value })} />
            </label>
            <p className="muted small">Actuellement : {dayLabel(editing.it.t.day)} à {editing.it.t.time}. Le changement compte à la prochaine génération.</p>
            <div className="row">
              <button type="button" className="btn big" onClick={() => setEditing(null)}>Annuler</button>
              <button className="btn primary big" disabled={!editing.value}>Enregistrer</button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
