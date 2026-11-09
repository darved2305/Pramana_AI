"use client";

import Link from "next/link";
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { clsx } from "clsx";
import { describeError, ApiError } from "@/lib/api/http";
import type { Tone } from "@/lib/data/derive";
import { IconAlert, IconClose } from "./icons";

/* ---------- Buttons ---------- */

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const btnBase =
  "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition-[background-color,color,border-color,transform,opacity] duration-300 ease-out disabled:cursor-not-allowed disabled:opacity-45 active:scale-[.98]";
const btnVariant: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:brightness-110",
  secondary: "border-[0.8px] border-line-strong text-fg hover:bg-white/[.06]",
  ghost: "text-fg-2 hover:bg-white/[.06] hover:text-fg",
  danger: "border-[0.8px] border-bad/50 text-bad hover:bg-bad/10",
};
const btnSize: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-[38px] px-4 text-[14px]",
  lg: "h-12 px-5 text-[16px]",
};

export function buttonClass(variant: Variant = "secondary", size: Size = "md", className?: string) {
  return clsx(btnBase, btnVariant[variant], btnSize[size], className);
}

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }
>(function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      className={buttonClass(variant, size, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
});

export function ButtonLink({
  href,
  variant = "secondary",
  size = "md",
  className,
  children,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)}>
      {children}
    </Link>
  );
}

export function IconButton({
  label,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={clsx(
        "grid h-[42px] w-[42px] shrink-0 place-items-center rounded-full border-[0.8px] border-line text-fg-2 transition-colors duration-300 hover:bg-white/[.06] hover:text-fg disabled:opacity-40",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={clsx("inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent", className)}
    />
  );
}

/* ---------- Chips (filter pills, measured: 38px tall, 14px, pill) ---------- */

export function Chip({
  active,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={clsx(
        "inline-flex h-[38px] items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-[14px] font-medium transition-colors duration-300",
        active
          ? "bg-accent-soft text-accent shadow-[inset_0_0_0_0.8px_var(--accent-line)]"
          : "text-muted shadow-[inset_0_0_0_0.8px_var(--app-line)] hover:text-fg",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ---------- Surfaces ---------- */

export function Card({
  className,
  children,
  as: Tag = "section",
  ...rest
}: { className?: string; children: ReactNode; as?: "section" | "div" | "article" | "li" } & Record<string, unknown>) {
  return (
    <Tag className={clsx("card", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  className,
  id,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <header className={clsx("flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <h2 id={id} className="text-[15px] font-semibold tracking-[0.01em] text-fg">
          {title}
        </h2>
        {subtitle ? <p className="mt-1 text-[13px] leading-snug text-muted">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}

const toneClass: Record<Tone, string> = {
  accent: "bg-accent-soft text-accent",
  ok: "bg-ok/12 text-ok",
  warn: "bg-warn/12 text-warn",
  bad: "bg-bad/12 text-bad",
  info: "bg-info/12 text-info",
  muted: "bg-white/[.06] text-fg-2",
};

export function Badge({ tone = "muted", children, className, dot }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span
      className={clsx(
        "inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-[12px] font-medium",
        toneClass[tone],
        className,
      )}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden /> : null}
      {children}
    </span>
  );
}

export function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex h-[22px] items-center rounded-full bg-white/[.06] px-2 text-[12px] text-fg-2">{children}</span>
  );
}

export function PreviewBadge({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex h-6 items-center gap-1.5 rounded-full border border-dashed border-warn/60 px-2.5 text-[12px] font-medium text-warn",
        className,
      )}
      title="Sample data for previewing the interface. Not from the core."
    >
      Preview data
    </span>
  );
}

/* ---------- States ---------- */

export function EmptyState({
  title,
  body,
  action,
  icon,
  className,
}: {
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      {icon ? (
        <div className="mb-4 grid h-12 w-12 place-items-center rounded-[12px] bg-accent-soft text-accent">{icon}</div>
      ) : null}
      <p className="text-[15px] font-medium text-fg">{title}</p>
      {body ? <div className="mt-1.5 max-w-[46ch] text-[14px] leading-relaxed text-muted">{body}</div> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const unreachable = error instanceof ApiError && error.unreachable;
  return (
    <div role="alert" className={clsx("flex flex-col items-center px-6 py-12 text-center", className)}>
      <div className="mb-4 grid h-12 w-12 place-items-center rounded-[12px] bg-bad/12 text-bad">
        <IconAlert />
      </div>
      <p className="text-[15px] font-medium text-fg">{unreachable ? "Pramana cannot be reached" : "Could not load this"}</p>
      <p className="mt-1.5 max-w-[52ch] text-[14px] leading-relaxed text-muted">{describeError(error)}</p>
      {error instanceof ApiError && error.requestId ? (
        <p className="mt-2 font-mono text-[11px] text-muted">request {error.requestId}</p>
      ) : null}
      {onRetry ? (
        <Button className="mt-5" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("skeleton", className)} />;
}

export function Notice({
  tone = "muted",
  title,
  children,
  className,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  const border: Record<Tone, string> = {
    accent: "border-accent/30",
    ok: "border-ok/30",
    warn: "border-warn/30",
    bad: "border-bad/30",
    info: "border-info/30",
    muted: "border-line",
  };
  return (
    <div className={clsx("rounded-[12px] border-[0.8px] bg-white/[.02] px-4 py-3 text-[13px] leading-relaxed text-fg-2", border[tone], className)}>
      {title ? <p className="mb-0.5 font-medium text-fg">{title}</p> : null}
      {children}
    </div>
  );
}

/* ---------- Form fields ---------- */

const fieldBase =
  "w-full rounded-[12px] border-[0.8px] border-line bg-white/[.03] px-3.5 text-[15px] text-fg placeholder:text-muted/80 transition-[border-color,background-color] duration-200 outline-none hover:border-line-strong focus:border-accent/70 focus:bg-white/[.05] aria-[invalid=true]:border-bad/70";

export function Field({
  label,
  hint,
  error,
  children,
  id,
  optional,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (props: { id: string; "aria-invalid": boolean; "aria-describedby"?: string }) => ReactNode;
  id?: string;
  optional?: boolean;
}) {
  const auto = useId();
  const fid = id ?? auto;
  const hid = `${fid}-hint`;
  const eid = `${fid}-err`;
  const describedBy = [hint ? hid : null, error ? eid : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={fid} className="text-[13px] font-medium text-fg-2">
        {label}
        {optional ? <span className="ml-1 font-normal text-muted">(optional)</span> : null}
      </label>
      {children({ id: fid, "aria-invalid": Boolean(error), "aria-describedby": describedBy })}
      {hint && !error ? (
        <p id={hid} className="text-[12px] text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={eid} className="text-[12px] text-bad" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={clsx(fieldBase, "h-11", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={clsx(fieldBase, "min-h-[96px] py-3 leading-relaxed", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <div className="relative">
      <select
        ref={ref}
        className={clsx(fieldBase, "h-11 cursor-pointer appearance-none pr-9 [&>option]:bg-[#1b1b1e]", className)}
        {...rest}
      >
        {children}
      </select>
      <svg aria-hidden viewBox="0 0 20 20" className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="m5 8 5 5 5-5" />
      </svg>
    </div>
  );
});

export function Checkbox({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className={clsx("flex cursor-pointer items-start gap-3", disabled && "cursor-not-allowed opacity-50")}>
      <input
        id={id}
        type="checkbox"
        className="peer sr-only"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        aria-hidden
        className="mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-[5px] border-[0.8px] border-line-strong transition-colors peer-checked:border-accent peer-checked:bg-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-accent peer-focus-visible:outline-offset-2"
      >
        <svg viewBox="0 0 20 20" className={clsx("h-3.5 w-3.5 text-accent-ink", checked ? "opacity-100" : "opacity-0")} fill="none" stroke="currentColor" strokeWidth="2.5">
          <path d="m4.5 10.5 3.5 3.5 7.5-8" />
        </svg>
      </span>
      <span className="text-[14px] leading-snug">
        <span className="text-fg">{label}</span>
        {description ? <span className="mt-0.5 block text-[13px] text-muted">{description}</span> : null}
      </span>
    </label>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
}) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-6">
      <div>
        <label htmlFor={id} className="text-[14px] text-fg">
          {label}
        </label>
        {description ? <p className="mt-0.5 text-[13px] text-muted">{description}</p> : null}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={clsx(
          "relative h-6 w-11 shrink-0 rounded-full transition-colors duration-300",
          checked ? "bg-accent" : "bg-white/15",
        )}
      >
        <span
          className={clsx(
            "absolute top-[3px] h-[18px] w-[18px] rounded-full bg-white shadow transition-transform duration-300 ease-out",
            checked ? "translate-x-[23px] bg-accent-ink" : "translate-x-[3px]",
          )}
        />
      </button>
    </div>
  );
}

/* ---------- Tabs ---------- */

export function Tabs<T extends string>({
  value,
  onChange,
  items,
  label,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  items: { value: T; label: ReactNode; count?: number }[];
  label: string;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    let n = -1;
    if (e.key === "ArrowRight") n = (i + 1) % items.length;
    if (e.key === "ArrowLeft") n = (i - 1 + items.length) % items.length;
    if (e.key === "Home") n = 0;
    if (e.key === "End") n = items.length - 1;
    if (n >= 0) {
      e.preventDefault();
      onChange(items[n].value);
      refs.current[n]?.focus();
    }
  };
  return (
    <div role="tablist" aria-label={label} className={clsx("flex flex-wrap gap-2", className)}>
      {items.map((it, i) => {
        const active = it.value === value;
        return (
          <button
            key={it.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="tab"
            type="button"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => onKey(e, i)}
            onClick={() => onChange(it.value)}
            className={clsx(
              "inline-flex h-[38px] items-center gap-1.5 rounded-full px-3 text-[14px] font-medium transition-colors duration-300",
              active
                ? "bg-accent-soft text-accent shadow-[inset_0_0_0_0.8px_var(--accent-line)]"
                : "text-muted shadow-[inset_0_0_0_0.8px_var(--app-line)] hover:text-fg",
            )}
          >
            {it.label}
            {it.count != null ? <span className="text-[12px] opacity-70">{it.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- Dialog (native <dialog>: focus trap, Esc and backdrop handled by the browser) ---------- */

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const tid = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={tid}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={clsx(
        "app-root m-auto w-[calc(100%-32px)] rounded-[20px] border-[0.8px] border-line bg-[#141416] p-0 text-fg shadow-[0_30px_80px_rgba(0,0,0,.6)] backdrop:bg-black/60 backdrop:backdrop-blur-[2px]",
        wide ? "max-w-[720px]" : "max-w-[480px]",
      )}
    >
      {open ? (
        <div className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id={tid} className="font-serif text-[26px] leading-tight tracking-[0.02em]">
                {title}
              </h2>
              {description ? <div className="mt-1.5 text-[14px] text-muted">{description}</div> : null}
            </div>
            <IconButton label="Close dialog" onClick={onClose} className="-mr-2 -mt-1 border-transparent">
              <IconClose />
            </IconButton>
          </div>
          {children ? <div className="mt-5">{children}</div> : null}
          {footer ? <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div> : null}
        </div>
      ) : null}
    </dialog>
  );
}

/* ---------- Probability bar ---------- */

export function ProbBar({ value, tone = "accent", className, label }: { value: number; tone?: Tone; className?: string; label?: string }) {
  const color: Record<Tone, string> = {
    accent: "bg-accent",
    ok: "bg-ok",
    warn: "bg-warn",
    bad: "bg-bad",
    info: "bg-info",
    muted: "bg-white/30",
  };
  const v = Math.max(0, Math.min(1, value));
  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v * 100)}
      aria-label={label}
      className={clsx("h-1.5 w-full overflow-hidden rounded-full bg-white/[.07]", className)}
    >
      <div
        className={clsx("h-full rounded-full transition-[width] duration-700 ease-[cubic-bezier(.22,1,.36,1)]", color[tone])}
        style={{ width: `${v * 100}%` }}
      />
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  eyebrow,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-2">{eyebrow}</div> : null}
        <h1 className="font-serif text-[clamp(34px,4vw,48px)] font-normal leading-[1.06] tracking-[0.017em] text-fg">
          {title}
        </h1>
        {subtitle ? <div className="mt-2 max-w-[70ch] text-[15px] leading-relaxed text-muted">{subtitle}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function KeyValue({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2 text-[14px]">
      <dt className="text-muted">{k}</dt>
      <dd className="text-right text-fg">{v}</dd>
    </div>
  );
}
