import { Brain, FolderOpen, GitBranch, LayoutDashboard, LogOut, MessageSquare, Settings } from "lucide-react";
import { useAuth } from "../../hooks/useAuth";

const NAV_ITEMS = [
  { hash: "#/", icon: MessageSquare, label: "Chat" },
  { hash: "#/graph", icon: GitBranch, label: "Graph" },
  { hash: "#/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { hash: "#/vault", icon: FolderOpen, label: "Vault" },
  { hash: "#/settings", icon: Settings, label: "Settings" },
];

interface SidebarProps {
  currentHash: string;
}

export function Sidebar({ currentHash }: SidebarProps) {
  const active = currentHash || "#/";
  const { signOut } = useAuth();

  return (
    <aside className="flex flex-col w-56 bg-gray-900 border-r border-gray-800">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-800">
        <Brain className="w-6 h-6 text-accent" />
        <span className="text-lg font-bold text-gray-100">BSage</span>
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
                  ? "bg-accent/15 text-accent-light font-medium"
                  : "text-gray-400 hover:bg-gray-800 hover:text-gray-300"
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </a>
          );
        })}
      </nav>
      <div className="border-t border-gray-800 px-4 py-3">
        <button
          onClick={() => signOut()}
          className="flex items-center gap-2 text-sm text-gray-500 hover:text-red-400 transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" />
          Sign out
        </button>
      </div>
    </aside>
  );
}
