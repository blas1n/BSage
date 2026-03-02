import { CATEGORY_COLORS } from "../../utils/constants";

interface BadgeProps {
  category: string;
}

export function Badge({ category }: BadgeProps) {
  const color = CATEGORY_COLORS[category] ?? "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {category}
    </span>
  );
}
