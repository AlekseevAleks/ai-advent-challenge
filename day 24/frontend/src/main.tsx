/** Точка входа приложения: маршрутизация и общие провайдеры. */

import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { ToastProvider } from "./components/ui/toast";
import { initTheme } from "./hooks/useTheme";
import "./index.css";
import { ComparisonPage } from "./pages/ComparisonPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { ExperimentPage } from "./pages/ExperimentPage";
import { HistoryPage } from "./pages/HistoryPage";
import { GroundedAnswerPage } from "./pages/GroundedAnswerPage";
import { RagEvalPage } from "./pages/RagEvalPage";
import { IndexingPage } from "./pages/IndexingPage";
import { RerankingPage } from "./pages/RerankingPage";
import { SearchPage } from "./pages/SearchPage";
import { SettingsPage } from "./pages/SettingsPage";

initTheme();

export function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="indexing" element={<IndexingPage />} />
            <Route path="reranking" element={<RerankingPage />} />
            <Route path="experiment" element={<ExperimentPage />} />
            <Route path="answers" element={<GroundedAnswerPage />} />
            <Route path="rag-eval" element={<RagEvalPage />} />
            <Route path="comparison" element={<ComparisonPage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<DashboardPage />} />
          </Route>
        </Routes>
      </ToastProvider>
    </BrowserRouter>
  );
}

const rootEl = document.getElementById("root");
if (rootEl) {
  createRoot(rootEl).render(<App />);
}