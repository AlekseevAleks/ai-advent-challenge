/** Главный layout: сайдбар, верхняя панель, рабочая область, мобильная навигация. */

import { BarChart3, Bot, FileText, Gauge, GitCompare, History, LayoutDashboard, MessageSquare, Search, Settings, SlidersHorizontal, TestTube } from "lucide-react";
import React from "react";
import { NavLink, Outlet } from "react-router-dom";
import { cn } from "../../lib/utils";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const MOBILE_NAV = [
  { to: "/", label: "Обзор", icon: LayoutDashboard, end: true },
  { to: "/documents", label: "Документы", icon: FileText },
  { to: "/indexing", label: "Индексация", icon: BarChart3 },
  { to: "/reranking", label: "Rerank", icon: SlidersHorizontal },
  { to: "/answers", label: "Ответы", icon: Bot },
  { to: "/chat", label: "Чат", icon: MessageSquare },
  { to: "/rag-eval", label: "Оценка RAG", icon: Gauge },
  { to: "/experiment", label: "Эксперимент", icon: TestTube },
  { to: "/comparison", label: "Сравнение", icon: GitCompare },
  { to: "/search", label: "Поиск", icon: Search },
  { to: "/history", label: "История", icon: History },
  { to: "/settings", label: "Настройки", icon: Settings },
];

export function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <Topbar />
      {/* Мобильная навигация */}
      <nav className="flex gap-1 overflow-x-auto border-b border-border bg-card px-2 py-1 lg:hidden">
        {MOBILE_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium",
                isActive ? "bg-[hsl(var(--primary)/0.14)] text-foreground" : "text-muted-foreground",
              )
            }
          >
            <item.icon className="h-3.5 w-3.5" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="flex flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto p-5">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}