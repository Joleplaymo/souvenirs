// File d'attente d'envoi : chaque souvenir est d'abord gardé sur le téléphone (IndexedDB), puis envoyé
// par morceaux avec reprise. Rien n'est perdu si le réseau coupe ou si l'application est fermée.
import { api, tokens } from "./api.js";

const CHUNK = 4 * 1024 * 1024;
let dbp = null;
const listeners = new Set();
const live = new Map(); // cid → { sent, size, state, error }
let running = false;
let current = null; // { cid, ctrl } : l'envoi en cours, pour pouvoir l'interrompre
const cancelled = new Set(); // envois retirés par l'utilisateur pendant cette session
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
  return list.sort((a, b) => (a.captured_at < b.captured_at ? -1 : 1)).map((e) => ({
    cid: e.cid, kind: e.kind, size: e.size || 0, blob: e.blob, mime: e.mime, filename: e.filename, text: e.text,
    ...(live.get(e.cid) || { sent: 0, state: "attente" }),
  }));
}

export async function enqueue(entry) {
  await put(entry);
  live.set(entry.cid, { sent: 0, state: "attente" });
  emit();
  kick();
}

// Retire un souvenir de la file : il n'est plus envoyé, l'envoi en cours est interrompu et ce qui était
// déjà arrivé sur le serveur (morceaux, ou souvenir complet si l'envoi venait de finir) est effacé.
export async function discard(cid) {
  const entry = (await all()).find((e) => e.cid === cid);
  cancelled.add(cid);
  if (current && current.cid === cid) current.ctrl.abort();
  await del(cid);
  live.delete(cid);
  emit();
  if (entry) forget(entry);
}

export async function discardAll(slug) {
  for (const e of await pending(slug)) await discard(e.cid);
}

function forget(e) {
  if (!tokens.participant(e.slug)) return;
  api(`/events/${e.slug}/uploads/${encodeURIComponent(e.cid)}`, { slug: e.slug, method: "DELETE" }).catch(() => {});
}

async function sendOne(e, signal) {
  const opt = { slug: e.slug, signal };
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
    if (signal.aborted) throw new DOMException("Envoi annulé", "AbortError");
    live.set(e.cid, { sent: offset, state: "envoi" });
    emit();
    try {
      const r = await api(`/uploads/${start.id}?offset=${offset}`, { method: "PUT", raw: e.blob.slice(offset, offset + CHUNK), headers, signal });
      offset = r.received;
    } catch (err) {
      if (err.status === 409 && err.data) offset = err.data.received; // reprise là où le serveur en est
      else throw err;
    }
  }
  if (signal.aborted) throw new DOMException("Envoi annulé", "AbortError");
  await api(`/uploads/${start.id}/complete`, { method: "POST", headers, signal });
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
        if (!tokens.participant(e.slug) || cancelled.has(e.cid)) continue;
        const ctrl = new AbortController();
        current = { cid: e.cid, ctrl };
        try {
          await sendOne(e, ctrl.signal);
          if (cancelled.has(e.cid)) forget(e); // arrivé juste avant l'annulation : on l'efface du serveur
          await del(e.cid);
          live.delete(e.cid);
          progressed = true;
        } catch (err) {
          if (cancelled.has(e.cid)) continue;
          const fatal = err.status && [400, 401, 404, 413].includes(err.status);
          live.set(e.cid, { sent: 0, state: fatal ? "erreur" : "attente", error: err.message });
          if (fatal && err.status !== 401) { /* gardé en file : l'utilisateur peut l'abandonner */ }
        } finally {
          current = null;
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
