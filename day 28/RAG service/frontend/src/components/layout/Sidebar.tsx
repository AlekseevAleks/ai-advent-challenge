/** Левое боковое меню. */

import {
  BarChart3,
  FileText,
  GitCompare,
  History,
  LayoutDashboard,
  Search,
  Settings,
  SlidersHorizontal,
  TestTube,
  Bot,
  Gauge,
  MessageSquare,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { cn } from "../../lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Обзор", icon: LayoutDashboard, end: true },
  { to: "/documents", label: "Документы", icon: FileText },
  { to: "/indexing", label: "Индексация", icon: BarChart3 },
  { to: "/reranking", label: "Reranking & Filtering", icon: SlidersHorizontal },
  { to: "/answers", label: "Ответы", icon: Bot },
  { to: "/chat", label: "Чат", icon: MessageSquare },
  { to: "/rag-eval", label: "Оценка RAG", icon: Gauge },
  { to: "/experiment", label: "Эксперимент", icon: TestTube },
  { to: "/comparison", label: "Сравнение стратегий", icon: GitCompare },
  { to: "/search", label: "Поиск по индексу", icon: Search },
  { to: "/history", label: "История запусков", icon: History },
  { to: "/settings", label: "Настройки", icon: Settings },
];

export function Sidebar() {
  return (
    <aside className="h-full w-60 shrink-0 border-r border-border bg-card lg:flex lg:flex-col">
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-3">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-[hsl(var(--primary)/0.14)] text-foreground"
                  : "text-muted-foreground hover:bg-accent DEFAULT hover:text-foreground",
              )
            }
          >
            {({ isActive }) => (
              <>
                <item.icon className="h-4 w-4" />
                <span className="flex-1">{item.label}</span>
                {isActive ? (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary DEFAULT" aria-hidden="true" />
                ) : null}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-border px-4 py-3">
        <p className="text-[11px] text-muted-foreground leading-snug">
          Локальное обучение RAG: FAISS + Ollama. Не отправляет данные наружу.
        </p>
      </div>
    </aside>
  );
}