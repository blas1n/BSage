import { Brain, LayoutDashboard, MessageSquare, ScrollText, Settings } from "lucide-react";

const NAV_ITEMS = [
  { hash: "#/", icon: MessageSquare, label: "Chat" },
  { hash: "#/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { hash: "#/actions", icon: ScrollText, label: "Actions" },
  { hash: "#/settings", icon: Settings, label: "Settings" },
];

interface SidebarProps {
  currentHash: string;
}

export function Sidebar({ currentHash }: SidebarProps) {
  const active = currentHash || "#/";
  return (
    <aside className="flex flex-col w-56 bg-gray-50 dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 dark:border-gray-700">
        <Brain className="w-6 h-6 text-green-600 dark:text-green-400" />
        <span className="text-lg font-bold text-gray-800 dark:text-gray-100">BSage</span>
      </div>
      <nav className="flex-1 py-2">
        {NAV_ITEMS.map(({ hash, icon: Icon, label }) => {
          const isActive = active === hash || (hash !== "#/" && active.startsWith(hash));
          return (
            <a
              key={hash}
              href={hash}
              className={`flex items-center gap-3 px-4 py-2.5 mx-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300 font-medium"
                  : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </a>
          );
        })}
      </nav>
    </aside>
  );
}
