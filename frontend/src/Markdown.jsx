import React, { useMemo } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";

export default function Markdown({ text }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text || "", { breaks: true })), [text]);
  return <article className="prose" dangerouslySetInnerHTML={{ __html: html }} />;
}
