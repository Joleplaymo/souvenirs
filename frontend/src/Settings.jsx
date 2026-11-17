// Réglages du souvenir modifiables après sa création (organisateur) : nom, dates, type, ton, fuseau horaire.
import React, { useEffect, useState } from "react";
import { api, fmtDates } from "./api.js";

const FIELDS = ["name", "start_date", "end_date", "type", "tone", "tz"];
const pick = (ev) => Object.fromEntries(FIELDS.map((k) => [k, ev[k] || ""]));

function zones(current) {
  let list = [];
  try { list = Intl.supportedValuesOf("timeZone"); } catch {}
  return list.length && !list.includes(current) ? [current, ...list] : list;
}

export default function Settings({ slug, ev, disabled, onSaved, onToast }) {
  const [cfg, setCfg] = useState(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(pick(ev));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/config").then(setCfg).catch(() => {}); }, []);
  useEffect(() => { if (!open) setForm(pick(ev)); }, [ev, open]);

  const up = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value, ...(k === "start_date" && f.end_date < e.target.value ? { end_date: e.target.value } : {}) }));
  const changed = FIELDS.filter((k) => form[k] !== (ev[k] || ""));
  const tzList = open ? zones(form.tz) : [];

  const save = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await api(`/events/${slug}/settings`, { slug, method: "PUT", body: form });
      setOpen(false);
      await onSaved();
      onToast(changed.some((k) => k !== "name") || ev.published
        ? "Réglages enregistrés : relance la génération pour les appliquer"
        : "Réglages enregistrés");
    } catch (err) { setError(err.message); }
    setBusy(false);
  };

  return (
    <section className="card">
      <div className="card-head">
        <h2>Réglages du souvenir</h2>
        {!open && <button className="btn" onClick={() => setOpen(true)} disabled={disabled || !cfg}>Modifier</button>}
      </div>
      {!open && (
        <dl className="settings-sum">
          <dt>Nom</dt><dd>{ev.name}</dd>
          <dt>Dates</dt><dd>{fmtDates(ev.start_date, ev.end_date)}</dd>
          <dt>Type</dt><dd>{ev.type_label}</dd>
          <dt>Ton</dt><dd>{ev.tone_label}</dd>
          <dt>Fuseau</dt><dd>{ev.tz}</dd>
        </dl>
      )}
      {open && cfg && (
        <form onSubmit={save}>
          <label>Nom
            <input value={form.name} onChange={up("name")} required maxLength={120} />
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
          <label>Fuseau horaire de l'événement
            {tzList.length
              ? <select value={form.tz} onChange={up("tz")}>{tzList.map((z) => <option key={z} value={z}>{z.replaceAll("_", " ")}</option>)}</select>
              : <input value={form.tz} onChange={up("tz")} required placeholder="Europe/Paris" />}
          </label>
          <p className="muted small">
            Le nouveau ton, le type et les dates s'appliquent à la prochaine génération : le récit, le film (et sa musique) et l'album
            sont refaits avec ces réglages. Le fuseau sert à afficher et à raconter les heures des souvenirs.
            {ev.published ? " Ce que voit le groupe ne change qu'après avoir publié à nouveau." : ""}
          </p>
          {error && <p className="error">{error}</p>}
          <div className="row">
            <button type="button" className="btn big" onClick={() => { setOpen(false); setError(""); }}>Annuler</button>
            <button className="btn primary big" disabled={busy || !changed.length}>{busy ? "Enregistrement…" : "Enregistrer"}</button>
          </div>
        </form>
      )}
    </section>
  );
}
