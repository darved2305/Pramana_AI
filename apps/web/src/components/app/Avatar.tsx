/** Initials on a colour derived from the name, so the same person always looks the same. */
export function Avatar({ name, size = 40 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <span
      aria-hidden
      className="grid shrink-0 place-items-center rounded-full text-[13px] font-semibold text-black/80"
      style={{ width: size, height: size, background: `hsl(${hue} 70% 72%)` }}
    >
      {initials}
    </span>
  );
}
