const CATEGORY_STYLES: Record<string, string> = {
  input: "bg-secondary-container/10 text-secondary",
  process: "bg-accent-light/10 text-accent-light",
  output: "bg-tertiary-container/10 text-tertiary",
};

interface BadgeProps {
  category: string;
}

export function Badge({ category }: BadgeProps) {
  const style = CATEGORY_STYLES[category] ?? "bg-surface-container-high text-gray-400";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase ${style}`}>
      {category}
    </span>
  );
}
