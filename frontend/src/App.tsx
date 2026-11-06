import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router";
import { onAuthChange, refreshSession } from "@/api/client";
import { useSession } from "@/api/hooks";
import { Layout } from "@/components/Layout";
import { Empty, Spinner } from "@/components/ui";
import { BacktestDetailPage, BacktestsPage } from "@/pages/BacktestsPage";
import { CoinPage } from "@/pages/CoinPage";
import { LoginPage } from "@/pages/LoginPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { PaperPage } from "@/pages/PaperPage";
import { PipelinePage } from "@/pages/PipelinePage";
import { PortfolioPage } from "@/pages/PortfolioPage";
import { ReportDetailPage, ReportsPage } from "@/pages/ReportsPage";
import { ScannerPage } from "@/pages/ScannerPage";
import { SettingsPage } from "@/pages/SettingsPage";

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => localStorage.getItem("ls-theme") ?? "dark");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("ls-theme", theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

export function App() {
  const session = useSession();
  const [theme, toggleTheme] = useTheme();
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    const off = onAuthChange(() => void session.refetch());
    return () => {
      off();
    };
  }, [session]);

  // Password mode: restore the session from the HttpOnly refresh cookie once.
  useEffect(() => {
    if (session.data?.auth_mode === "password" && !session.data.authenticated && !restored) {
      setRestored(true);
      void refreshSession();
    }
  }, [session.data, restored]);

  if (session.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (!session.data) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <Empty>
          Cannot reach the Lodestar API ({session.error?.message}). In local development start it with{" "}
          <code>make migrate seed</code>, <code>make dev-api</code> and <code>make dev-worker</code>; with Docker, run{" "}
          <code>make up</code> and open port 8080.
        </Empty>
      </div>
    );
  }
  if (!session.data.authenticated) return <LoginPage />;

  return (
    <Routes>
      <Route element={<Layout session={session.data} theme={theme} onToggleTheme={toggleTheme} />}>
        <Route index element={<OverviewPage />} />
        <Route path="coins/:assetId" element={<CoinPage theme={theme} />} />
        <Route path="pipeline" element={<PipelinePage />} />
        <Route path="pipeline/:runId" element={<PipelinePage />} />
        <Route path="scanner" element={<ScannerPage />} />
        <Route path="backtests" element={<BacktestsPage />} />
        <Route path="backtests/:backtestId" element={<BacktestDetailPage theme={theme} />} />
        <Route path="paper" element={<PaperPage theme={theme} />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/:reportId" element={<ReportDetailPage />} />
        <Route path="settings" element={<SettingsPage theme={theme} onToggleTheme={toggleTheme} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
