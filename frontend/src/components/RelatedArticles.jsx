import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function RelatedArticles({ category, ageMonths, title = "📖 Artikel Terkait" }) {
  const [articles, setArticles] = useState([]);
  const [expandedId, setExpandedId] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .listArticles(category, ageMonths)
      .then(setArticles)
      .finally(() => setLoading(false));
  }, [category, ageMonths]);

  if (loading || articles.length === 0) return null;

  return (
    <div className="mb-4">
      <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono mb-2 px-1">
        {title}
      </p>
      <div className="space-y-2">
        {articles.map((a) => {
          const isExternal = !!a.source_url;

          if (isExternal) {
            return (
              <div
                key={a.id}
                className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3"
              >
                <p className="text-sm text-ink font-medium">{a.title}</p>
                <p className="text-xs text-ink-faint mt-1">{a.summary}</p>
                <div className="flex items-center justify-between mt-2">
                  {a.source && <p className="text-[11px] text-ink-faint">Sumber: {a.source}</p>}
                  <a
                    href={a.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-feed font-medium whitespace-nowrap"
                  >
                    Baca Selengkapnya →
                  </a>
                </div>
              </div>
            );
          }

          const isOpen = expandedId === a.id;
          return (
            <div
              key={a.id}
              className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 cursor-pointer"
              onClick={() => setExpandedId(isOpen ? null : a.id)}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm text-ink font-medium">{a.title}</p>
                <span className="text-ink-faint text-xs flex-shrink-0">{isOpen ? "▲" : "▼"}</span>
              </div>
              {!isOpen && <p className="text-xs text-ink-faint mt-1">{a.summary}</p>}
              {isOpen && (
                <div className="mt-2">
                  <p className="text-sm text-ink-muted leading-relaxed whitespace-pre-line">{a.body}</p>
                  {a.source && (
                    <p className="text-[11px] text-ink-faint mt-3">Referensi umum: {a.source}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}