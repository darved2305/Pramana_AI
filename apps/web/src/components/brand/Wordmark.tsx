import { clsx } from "clsx";

/**
 * Pramana mark: a solid disc (what someone observed) beside a half disc (what can be
 * inferred from it), sharing one baseline. Together they read as a "P" at small sizes.
 */
export function PramanaMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 66 36"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      fill="currentColor"
    >
      <circle cx="18" cy="18" r="18" />
      <path d="M40 0h4a18 18 0 0 1 0 36h-4z" />
      <rect x="58.5" y="0" width="7.5" height="36" rx="0" />
    </svg>
  );
}

/**
 * Wordmark. Inter Light with negative tracking, optically centred under the mark the way
 * the reference stacks its logo in the header.
 */
export function Wordmark({
  stacked = false,
  className,
  markClassName,
}: {
  stacked?: boolean;
  className?: string;
  markClassName?: string;
}) {
  if (stacked) {
    return (
      <span className={clsx("inline-flex flex-col items-center gap-[7px] leading-none", className)}>
        <PramanaMark className={clsx("h-[34px] w-auto", markClassName)} />
        <span className="font-inter text-[21px] font-light tracking-[-0.035em] leading-none [font-feature-settings:'ss01']">
          Pramana
        </span>
      </span>
    );
  }
  return (
    <span className={clsx("inline-flex items-center gap-[10px] leading-none", className)}>
      <PramanaMark className={clsx("h-[22px] w-auto", markClassName)} />
      <span className="font-inter text-[22px] font-light tracking-[-0.035em] leading-none translate-y-[-1px]">
        Pramana
      </span>
    </span>
  );
}
