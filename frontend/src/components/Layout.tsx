import { FileText, FlaskConical, LayoutDashboard, LineChart, LogOut, Moon, Radar, Settings, Sun, TestTubes, Wallet, Workflow } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router";
import { useLogout } from "@/api/hooks";
import type { Session } from "@/api/types";
import { AssetSearch } from "./AssetSearch";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/scanner", label: "Scanner", icon: Radar },
  { to: "/pipeline", label: "Pipeline", icon: Workflow },
  { to: "/backtests", label: "Backtests", icon: LineChart },
  { to: "/paper", label: "Paper trading", icon: TestTubes },
  { to: "/portfolio", label: "Portfolio", icon: Wallet },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function DemoBanner() {
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 px-4 py-1.5 text-xs font-medium text-black"
      style={{ background: "var(--warning)" }}
    >
      <FlaskConical size={14} aria-hidden />
      Demo data: prices and metrics are synthetic, not real market data.
      <Link to="/settings" className="underline">
        Connect live data
      </Link>
    </div>
  );
}

export function Layout({ session, theme, onToggleTheme }: { session: Session; theme: string; onToggleTheme: () => void }) {
  const logout = useLogout();
  return (
    <div className="flex min-h-screen flex-col">
      {session.demo && <DemoBanner />}
      <div className="flex flex-1">
        <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line bg-surface p-4 md:flex">
          <div className="mb-8 flex items-center gap-2 px-2">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <span className="text-lg font-semibold tracking-tight">Lodestar</span>
          </div>
          <nav className="flex flex-1 flex-col gap-1" aria-label="Main">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-surface-2 text-ink" : "text-ink-2 hover:bg-surface-2"}`
                }
              >
                <Icon size={16} aria-hidden /> {label}
              </NavLink>
            ))}
          </nav>
          <p className="mb-3 px-3 text-[11px] leading-snug text-muted">Read-only research and paper trading. Never holds keys, never places orders.</p>
          {session.auth_mode === "password" && (
            <button
              type="button"
              onClick={() => logout.mutate()}
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-ink-2 hover:bg-surface-2"
            >
              <LogOut size={16} aria-hidden /> Sign out
            </button>
          )}
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-page/90 px-6 py-3 backdrop-blur">
            <AssetSearch />
            <nav className="flex gap-1 md:hidden" aria-label="Main (compact)">
              {NAV.map(({ to, label, icon: Icon }) => (
                <NavLink key={to} to={to} end={to === "/"} aria-label={label} className="rounded-md p-2 text-ink-2 hover:bg-surface-2">
                  <Icon size={16} />
                </NavLink>
              ))}
            </nav>
            <button
              type="button"
              onClick={onToggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              className="ml-auto rounded-lg border border-line p-2 text-ink-2 hover:bg-surface-2"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
