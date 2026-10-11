/** Верхняя панель: проект, статус Ollama, переключатель темы. */

import { Database, Moon, Sun } from "lucide-react";
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTheme } from "../../hooks/useTheme";
import { getOllamaStatus } from "../../services/api";
import { cn } from "../../lib/utils";

export function Topbar() {
  const { dark, toggle } = useTheme();
  const [ollama, setOllama] = useState<{ ok: boolean; model?: string | null } | null>(null);

  useEffect(() => {
    const poll = () => {
      getOllamaStatus()
        .then((s) => setOllama({ ok: s.available, model: s.model }))
        .catch(() => setOllama({ ok: false, model: null }));
    };
    poll();
    const timer = window.setInterval(poll, 15_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-card px-4">
      <Link to="/" className="flex items-center gap-2 lg:hidden">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[hsl(var(--primary)/0.15)] text-primary DEFAULT">
          <Database className="h-4 w-4" />
        </span>
      </Link>
      <div className="min-w-0">
        <h1 className="truncate text-sm font-semibold">RAG Document Indexing Lab</h1>
        <p className="truncate text-xs text-muted-foreground">Индексация документов для Retrieval-Augmented Generation</p>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <div
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
            ollama === null
              ? "border-border text-muted-foreground"
              : ollama.ok
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                : "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300",
          )}
          title={ollama?.ok ? `Ollama: ${ollama.model || ""}` : "Ollama недоступен"}
        >
          <span className={cn("h-1.5 w-1.5 rounded-full", ollama === null ? "bg-muted-foreground" : ollama.ok ? "bg-emerald-500" : "bg-red-500")} />
          <span>Ollama {ollama === null ? "…" : ollama.ok ? "онлайн" : "недоступен"}</span>
        </div>
        <button
          type="button"
          onClick={toggle}
          className="rounded-md p-2 text-muted-foreground hover:bg-accent DEFAULT"
          title="Переключить тему"
          aria-label="Переключить тему"
        >
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </div>
    </header>
  );
}