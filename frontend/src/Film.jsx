// Lecteur du film, à la forme du cadrage : horizontal 16:9, vertical 9:16 (80 % de la hauteur d'écran au plus) ou carré.
// framing (facultatif) donne la forme avant le chargement ; les dimensions réelles du film la confirment ensuite
// (une version reprise ou publiée peut avoir un autre cadrage que les réglages actuels).
import React, { useEffect, useState } from "react";

const SHAPE = { "16:9": "", "9:16": "tall", "1:1": "square" };
const shapeOf = (w, h) => (w / h < 0.9 ? "tall" : w / h <= 1.1 ? "square" : "");

export default function Film({ src, framing }) {
  const [shape, setShape] = useState(SHAPE[framing] || "");
  useEffect(() => { setShape(SHAPE[framing] || ""); }, [framing, src]);
  const fit = (e) => {
    const v = e.currentTarget;
    if (v.videoWidth && v.videoHeight) setShape(shapeOf(v.videoWidth, v.videoHeight));
  };
  return <video className={`film-video ${shape}`.trim()} controls playsInline preload="metadata" src={src} onLoadedMetadata={fit} />;
}
