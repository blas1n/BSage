interface IconProps {
  name: string;
  className?: string;
  filled?: boolean;
  size?: number;
  weight?: number;
}

export function Icon({ name, className = "", filled = false, size, weight }: IconProps) {
  const style: React.CSSProperties = {};
  const settings: string[] = [];
  if (filled) settings.push("'FILL' 1");
  if (weight) settings.push(`'wght' ${weight}`);
  if (settings.length > 0) {
    style.fontVariationSettings = settings.join(", ");
  }
  if (size) {
    style.fontSize = `${size}px`;
  }
  return (
    <span className={`material-symbols-outlined ${className}`} style={style}>
      {name}
    </span>
  );
}
