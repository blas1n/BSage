import { Brain, Network, Search, Puzzle, Leaf } from "lucide-react";
import { useAuth } from "../../hooks/useAuth";

const features = [
  {
    icon: Network,
    title: "Knowledge Graph",
    description:
      "Visualize connections between your ideas with an interactive ontology-powered graph.",
  },
  {
    icon: Search,
    title: "Smart Search",
    description:
      "AI-powered search that understands context and surfaces relevant insights instantly.",
  },
  {
    icon: Puzzle,
    title: "Plugin Ecosystem",
    description:
      "Extend your brain with plugins — collect data, automate workflows, sync everywhere.",
  },
];

export function LandingPage() {
  const { login, signup } = useAuth();

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-gray-950 px-4 overflow-hidden">
      {/* Emerald gradient glow */}
      <div
        className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full opacity-[0.07]"
        style={{
          background:
            "radial-gradient(circle, #10b981 0%, transparent 70%)",
        }}
      />

      <div className="relative z-10 w-full max-w-md space-y-10 text-center">
        {/* Logo + Branding */}
        <div className="flex flex-col items-center gap-4">
          <div className="relative flex items-center justify-center w-16 h-16 rounded-xl bg-accent/10 border border-accent/20">
            <Brain className="w-8 h-8 text-accent" />
            <Leaf className="absolute -bottom-1 -right-1 w-4 h-4 text-accent-light" />
          </div>
          <div>
            <h1 className="text-4xl font-bold text-gray-50 tracking-tight">
              BSage
            </h1>
            <p className="mt-2 text-gray-400 text-base leading-relaxed">
              Your AI-powered second brain.
              <br />
              Organize knowledge, surface insights, grow ideas.
            </p>
          </div>
        </div>

        {/* Feature Highlights */}
        <div className="grid grid-cols-1 gap-3">
          {features.map((f) => (
            <div
              key={f.title}
              className="flex items-start gap-3 rounded-lg bg-gray-900 border border-gray-700/50 p-4 text-left"
            >
              <div className="flex-shrink-0 flex items-center justify-center w-9 h-9 rounded-md bg-accent/10">
                <f.icon className="w-[18px] h-[18px] text-accent" />
              </div>
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-gray-100">
                  {f.title}
                </h3>
                <p className="mt-0.5 text-xs text-gray-500 leading-relaxed">
                  {f.description}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Sign In Button */}
        <div className="space-y-3">
          <button
            onClick={login}
            className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white hover:bg-accent-dark focus:outline-none focus:ring-2 focus:ring-accent/50 focus:ring-offset-2 focus:ring-offset-gray-950 transition-colors cursor-pointer"
          >
            Sign in with BSVibe
          </button>
          <p className="text-sm text-gray-500">
            Don't have an account?{" "}
            <button
              onClick={signup}
              className="text-accent hover:text-accent-light font-medium transition-colors"
            >
              Sign up
            </button>
          </p>
        </div>

        {/* Footer */}
        <p className="text-xs text-gray-600">
          Powered by{" "}
          <span className="text-gray-500 font-medium">BSVibe</span>
        </p>
      </div>
    </div>
  );
}
