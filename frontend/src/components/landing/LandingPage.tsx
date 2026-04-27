import { Brain, Network, Search, Puzzle, Leaf } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../hooks/useAuth";

export function LandingPage() {
  const { t } = useTranslation();
  const { login, signup } = useAuth();

  const features = [
    {
      icon: Network,
      title: t("landing.features.graph.title"),
      description: t("landing.features.graph.description"),
    },
    {
      icon: Search,
      title: t("landing.features.search.title"),
      description: t("landing.features.search.description"),
    },
    {
      icon: Puzzle,
      title: t("landing.features.plugins.title"),
      description: t("landing.features.plugins.description"),
    },
  ];

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
              {t("landing.tagline")}
              <br />
              {t("landing.subtitle")}
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
            {t("landing.signIn")}
          </button>
          <p className="text-sm text-gray-500">
            {t("landing.noAccount")}{" "}
            <button
              onClick={signup}
              className="text-accent hover:text-accent-light font-medium transition-colors"
            >
              {t("landing.signUp")}
            </button>
          </p>
        </div>

        {/* Footer */}
        <p className="text-xs text-gray-600">
          {t("landing.poweredBy")}{" "}
          <span className="text-gray-500 font-medium">BSVibe</span>
        </p>
      </div>
    </div>
  );
}
