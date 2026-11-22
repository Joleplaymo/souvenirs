import React, { useEffect, useState } from "react";
import Home from "./Home.jsx";
import EventPage from "./EventPage.jsx";
import Music from "./Music.jsx";
import { tokens } from "./api.js";

function parse() {
  if (location.pathname === "/musiques") return { page: "music" };
  const m = location.pathname.match(/^\/e\/([\w-]+)(?:\/admin\/([\w-]+))?/);
  if (!m) return { page: "home" };
  if (m[2]) {
    // lien organisateur : on mémorise le jeton puis on le retire de la barre d'adresse
    tokens.setAdmin(m[1], m[2]);
    history.replaceState(null, "", `/e/${m[1]}`);
  }
  return { page: "event", slug: m[1] };
}

export default function App() {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const f = () => setRoute(parse());
    window.addEventListener("popstate", f);
    return () => window.removeEventListener("popstate", f);
  }, []);
  if (route.page === "music") return <Music />;
  return route.page === "event" ? <EventPage key={route.slug} slug={route.slug} /> : <Home />;
}

export function Toast({ msg, onDone }) {
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(onDone, 3500);
    return () => clearTimeout(t);
  }, [msg]);
  return msg ? <div className="toast" role="status">{msg}</div> : null;
}

export function ShareRow({ label, url, hint }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(url); } catch {
      const i = document.createElement("input");
      i.value = url; document.body.appendChild(i); i.select(); document.execCommand("copy"); i.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="share">
      <div className="share-label">{label}</div>
      {hint && <div className="muted small">{hint}</div>}
      <div className="share-row">
        <input readOnly value={url} onFocus={(e) => e.target.select()} aria-label={label} />
        <button className="btn" onClick={copy}>{copied ? "Copié ✓" : "Copier"}</button>
        {navigator.share && <button className="btn" onClick={() => navigator.share({ url }).catch(() => {})}>Partager</button>}
      </div>
    </div>
  );
}
