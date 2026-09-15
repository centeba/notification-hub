import { useState } from "react";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { RulesPage } from "./pages/RulesPage";
import { PreferencesPage } from "./pages/PreferencesPage";

type Tab = "dashboard" | "history" | "rules" | "preferences";

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "history", label: "History" },
  { id: "rules", label: "Rules" },
  { id: "preferences", label: "Preferences" },
];

export function App() {
  const [tab, setTab] = useState<Tab>("dashboard");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Notification&nbsp;Hub</div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "tab tab-active" : "tab"}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="content">
        {tab === "dashboard" && <DashboardPage />}
        {tab === "history" && <HistoryPage />}
        {tab === "rules" && <RulesPage />}
        {tab === "preferences" && <PreferencesPage />}
      </main>
    </div>
  );
}
