// File d'attente d'envoi : chaque souvenir est d'abord gardé sur le téléphone (IndexedDB), puis envoyé
// par morceaux avec reprise. Rien n'est perdu si le réseau coupe ou si l'application est fermée.
import { api, tokens } from "./api.js";

const CHUNK = 4 * 1024 * 1024;
let dbp = null;
const listeners = new Set();
const live = new Map(); // cid → { sent, size, state, error }
let running = false;
let memory = []; // repli si IndexedDB est indisponible (navigation privée)

function open() {
  if (!dbp) {
    dbp = new Promise((resolve, reject) => {
      const r = indexedDB.open("souvenirs-envois", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("q", { keyPath: "cid" });
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    }).catch(() => null);
  }
  return dbp;
}
async function tx(mode, fn) {
  const db = await open();
  if (!db) return fn(null);
  return new Promise((resolve, reject) => {
    const t = db.transaction("q", mode);
    const out = fn(t.objectStore("q"));
    t.oncomplete = () => resolve(out && out.result !== undefined ? out.result : out);
    t.onerror = () => reject(t.error);
  });
}
const all = async () => (await tx("readonly", (s) => (s ? s.getAll() : memory))) || [];
const put = (e) => tx("readwrite", (s) => (s ? s.put(e) : (memory = [...memory.filter((m) => m.cid !== e.cid), e])));
const del = (cid) => tx("readwrite", (s) => (s ? s.delete(cid) : (memory = memory.filter((m) => m.cid !== cid))));

function emit() { listeners.forEach((f) => f()); }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export async function pending(slug) {
  const list = (await all()).filter((e) => e.slug === slug);
  return list.map((e) => ({
    cid: e.cid, kind: e.kind, size: e.size || 0,
    ...(live.get(e.cid) || { sent: 0, state: "attente" }),
  }));
}

export async function enqueue(entry) {
  await put(entry);
  live.set(entry.cid, { sent: 0, state: "attente" });
  emit();
  kick();
}

export async function discard(cid) { await del(cid); live.delete(cid); emit(); }

async function sendOne(e) {
  const opt = { slug: e.slug };
  if (e.type === "note") {
    await api(`/events/${e.slug}/notes`, { ...opt, method: "POST", body: { text: e.text, captured_at: e.captured_at, client_id: e.cid } });
    return;
  }
  const start = await api(`/events/${e.slug}/uploads`, {
    ...opt, method: "POST",
    body: { kind: e.kind, filename: e.filename, mime: e.mime, size: e.blob.size, captured_at: e.captured_at, source: e.source, client_id: e.cid },
  });
  if (start.done) return;
  let offset = start.received;
  const headers = { "X-Participant-Token": tokens.participant(e.slug) };
  while (offset < e.blob.size) {
    live.set(e.cid, { sent: offset, state: "envoi" });
    emit();
    try {
      const r = await api(`/uploads/${start.id}?offset=${offset}`, { method: "PUT", raw: e.blob.slice(offset, offset + CHUNK), headers });
      offset = r.received;
    } catch (err) {
      if (err.status === 409 && err.data) offset = err.data.received; // reprise là où le serveur en est
      else throw err;
    }
  }
  await api(`/uploads/${start.id}/complete`, { method: "POST", headers });
}

export async function kick() {
  if (running) return;
  running = true;
  try {
    let delay = 2000;
    for (;;) {
      const list = (await all()).sort((a, b) => (a.captured_at < b.captured_at ? -1 : 1));
      if (!list.length) break;
      let progressed = false;
      for (const e of list) {
        if (!tokens.participant(e.slug)) continue;
        try {
          await sendOne(e);
          await del(e.cid);
          live.delete(e.cid);
          progressed = true;
        } catch (err) {
          const fatal = err.status && [400, 401, 404, 413].includes(err.status);
          live.set(e.cid, { sent: 0, state: fatal ? "erreur" : "attente", error: err.message });
          if (fatal && err.status !== 401) { /* gardé en file : l'utilisateur peut l'abandonner */ }
        }
        emit();
      }
      const left = (await all()).filter((e) => (live.get(e.cid) || {}).state !== "erreur");
      if (!left.length) break;
      if (!progressed) {
        await new Promise((r) => setTimeout(r, delay));
        delay = Math.min(delay * 2, 30000);
      } else delay = 2000;
    }
  } finally {
    running = false;
    emit();
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("online", () => kick());
  document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(); });
}
