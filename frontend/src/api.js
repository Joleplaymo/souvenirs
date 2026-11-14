// Accès à l'API. Les jetons (participant, organisateur) restent dans le navigateur, par événement.
const get = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const set = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} };

export const tokens = {
  admin: (slug) => get(`sv:${slug}:admin`),
  setAdmin: (slug, v) => set(`sv:${slug}:admin`, v),
  participant: (slug) => get(`sv:${slug}:me`),
  setParticipant: (slug, v) => set(`sv:${slug}:me`, v),
  code: () => get("sv:code"),
  setCode: (v) => set("sv:code", v),
};

export function authHeaders(slug) {
  const h = {};
  if (slug && tokens.admin(slug)) h["X-Admin-Token"] = tokens.admin(slug);
  if (slug && tokens.participant(slug)) h["X-Participant-Token"] = tokens.participant(slug);
  return h;
}

export async function api(path, { method = "GET", body, slug, headers = {}, raw, signal } = {}) {
  const opts = { method, headers: { ...authHeaders(slug), ...headers }, signal };
  if (raw !== undefined) opts.body = raw;
  else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  let res;
  try {
    res = await fetch(`/api${path}`, opts);
  } catch (err) {
    if (signal && signal.aborted) throw err;
    const e = new Error("Pas de connexion. Réessaie dans un instant.");
    e.network = true;
    throw e;
  }
  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) {
    const e = new Error((data && data.detail) || `Erreur ${res.status}`);
    e.status = res.status;
    e.data = data;
    throw e;
  }
  return data;
}

export const mediaUrl = (slug, id, variant) => `/api/events/${slug}/media/${id}/${variant}`;

const pad = (n) => String(n).padStart(2, "0");
export function fmtTime(iso) {
  const d = new Date(iso);
  const today = new Date();
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (d.toDateString() === today.toDateString()) return hm;
  return `${d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" })} · ${hm}`;
}
export function fmtDur(s) {
  s = Math.round(s || 0);
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}
export function fmtDates(a, b) {
  const o = { day: "numeric", month: "long", year: "numeric" };
  const da = new Date(a + "T12:00:00"), dbb = new Date(b + "T12:00:00");
  return a === b ? da.toLocaleDateString("fr-FR", o)
    : `${da.toLocaleDateString("fr-FR", { day: "numeric", month: "long" })} – ${dbb.toLocaleDateString("fr-FR", o)}`;
}
export const KIND = {
  dictee: { icon: "🎙️", label: "Dictée" },
  conversation: { icon: "💬", label: "Conversation" },
  video: { icon: "🎥", label: "Vidéo" },
  photo: { icon: "📷", label: "Photo" },
  note: { icon: "✏️", label: "Note" },
};
export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
