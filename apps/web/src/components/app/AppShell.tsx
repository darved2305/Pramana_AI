"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { PramanaMark } from "@/components/brand/Wordmark";
import {
  IconBuilding,
  IconChart,
  IconChevronDown,
  IconClose,
  IconCollapse,
  IconExpand,
  IconGrid,
  IconHistory,
  IconMenu,
  IconPlus,
  IconSearch,
  IconSettings,
  IconUser,
  IconUsers,
} from "@/components/ui/icons";
import { IconButton } from "@/components/ui";
import { useCoreHealth } from "@/lib/data/hooks";
import { previewMode, usePrefs, usePreviewMode } from "@/lib/store/local";
import { useSession } from "@/lib/data/session";

const NAV = [
  { href: "/app", label: "Overview", icon: IconGrid, exact: true },
  { href: "/app/investigations", label: "Investigations", icon: IconHistory },
  { href: "/app/participants", label: "Participants", icon: IconUsers },
  { href: "/app/sites", label: "Sites", icon: IconBuilding },
  { href: "/app/evaluation", label: "Evaluation", icon: IconChart },
];
const NAV_2 = [
  { href: "/app/settings", label: "Settings", icon: IconSettings },
  { href: "/app/account", label: "Account", icon: IconUser },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  // The drawer belongs to the page it was opened on, so navigating closes it.
  const [drawerAt, setDrawerAt] = useState<string | null>(null);
  const drawer = drawerAt === pathname;
  const setDrawer = (open: boolean) => setDrawerAt(open ? pathname : null);
  const preview = usePreviewMode();
  const { reduceMotion } = usePrefs();
  const session = useSession();
  const router = useRouter();

  // The core said nobody is signed in: go to sign-in and come back here afterwards.
  // An unreachable core is not a sign-out; the screens show that state themselves.
  useEffect(() => {
    if (!preview && session.status === "signed-out") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [preview, session.status, pathname, router]);

  useEffect(() => {
    document.documentElement.dataset.motion = reduceMotion ? "reduce" : "";
  }, [reduceMotion]);
  useEffect(() => {
    if (!drawer) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && setDrawerAt(null);
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [drawer]);

  return (
    <div className="app-root flex min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-full bg-accent px-4 py-2 text-accent-ink focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside
        className={clsx(
          "sticky top-0 hidden h-dvh shrink-0 flex-col transition-[width] duration-300 ease-out lg:flex",
          collapsed ? "w-[76px]" : "w-[260px]",
        )}
      >
        <Sidebar collapsed={collapsed} pathname={pathname} />
      </aside>

      {/* Mobile drawer */}
      <div
        className={clsx(
          "fixed inset-0 z-40 lg:hidden",
          drawer ? "pointer-events-auto" : "pointer-events-none",
        )}
        aria-hidden={!drawer}
      >
        <div
          className={clsx("absolute inset-0 bg-black/60 transition-opacity duration-300", drawer ? "opacity-100" : "opacity-0")}
          onClick={() => setDrawer(false)}
        />
        <aside
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          className={clsx(
            "absolute inset-y-0 left-0 flex w-[280px] flex-col bg-app-bg transition-transform duration-300 ease-out",
            drawer ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <div className="absolute right-3 top-3">
            <IconButton label="Close navigation" onClick={() => setDrawer(false)} tabIndex={drawer ? 0 : -1}>
              <IconClose />
            </IconButton>
          </div>
          <Sidebar collapsed={false} pathname={pathname} inert={!drawer} />
        </aside>
      </div>

      <div className="flex min-w-0 flex-1 flex-col lg:py-[10px] lg:pr-[10px]">
        <div className="flex min-h-full flex-1 flex-col bg-panel lg:rounded-[16px]">
          {preview ? <PreviewBanner /> : null}
          <TopBar
            collapsed={collapsed}
            onToggle={() => setCollapsed((c) => !c)}
            onMenu={() => setDrawer(true)}
          />
          <main id="main" className="flex-1 px-4 pb-16 pt-2 sm:px-6 lg:px-[14px] xl:px-[14px]">
            <div className="mx-auto w-full max-w-[1240px]">{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}

function Sidebar({ collapsed, pathname, inert }: { collapsed: boolean; pathname: string; inert?: boolean }) {
  const isActive = (href: string, exact?: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + "/");
  const [moreOpen, setMoreOpen] = useState(true);
  return (
    <div className="flex h-full flex-col px-[5px] pb-[10px] pt-[14px]" inert={inert}>
      <Link
        href="/app"
        className={clsx("mb-[18px] flex h-9 items-center gap-2.5 px-[7px]", collapsed && "justify-center px-0")}
        aria-label="Pramana overview"
      >
        <PramanaMark className="h-[20px] w-auto text-fg" />
        {!collapsed ? <span className="font-inter text-[24px] font-light tracking-[-0.035em] text-fg">Pramana</span> : null}
      </Link>

      <Link
        href="/app/investigations/new"
        className={clsx(
          "mb-3 flex h-10 items-center gap-2 rounded-full bg-accent text-[14px] font-medium text-accent-ink transition-[filter] duration-300 hover:brightness-110",
          collapsed ? "mx-auto w-10 justify-center" : "mx-[5px] px-4",
        )}
        aria-label="New investigation"
      >
        <IconPlus className="h-[18px] w-[18px]" />
        {!collapsed ? "New investigation" : null}
      </Link>

      <nav aria-label="Application" className="flex flex-col gap-[2px]">
        {NAV.map((n) => (
          <NavItem key={n.href} {...n} active={isActive(n.href, n.exact)} collapsed={collapsed} />
        ))}
      </nav>

      <div className="mt-5">
        {!collapsed ? (
          <button
            type="button"
            onClick={() => setMoreOpen((o) => !o)}
            aria-expanded={moreOpen}
            className="flex h-8 w-full items-center justify-between px-[6px] text-[11px] font-medium uppercase tracking-[0.08em] text-muted"
          >
            Workspace
            <IconChevronDown className={clsx("h-4 w-4 transition-transform duration-300", moreOpen ? "rotate-180" : "")} />
          </button>
        ) : (
          <div className="mx-auto my-2 h-px w-8 bg-line" />
        )}
        {moreOpen || collapsed ? (
          <nav aria-label="Workspace" className="flex flex-col gap-[2px]">
            {NAV_2.map((n) => (
              <NavItem key={n.href} {...n} active={isActive(n.href)} collapsed={collapsed} />
            ))}
          </nav>
        ) : null}
      </div>

      <div className="mt-auto flex flex-col gap-2 px-[5px]">
        <ConnectionCard collapsed={collapsed} />
        <AccountPill collapsed={collapsed} />
      </div>
    </div>
  );
}

function NavItem({
  href,
  label,
  icon: Icon,
  active,
  collapsed,
}: {
  href: string;
  label: string;
  icon: (p: React.SVGProps<SVGSVGElement>) => React.ReactElement;
  active: boolean;
  collapsed: boolean;
}) {
  // Measured on the reference: 36px rows, 20px radius, 8px 12px padding, 16px text.
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      title={collapsed ? label : undefined}
      className={clsx(
        "flex h-9 items-center gap-3 rounded-[20px] px-3 text-[16px] transition-colors duration-300",
        active ? "bg-white/[.05] font-medium text-accent" : "text-muted hover:bg-white/[.03] hover:text-fg",
        collapsed && "justify-center px-0",
      )}
    >
      <Icon className="h-[18px] w-[18px] shrink-0" />
      {!collapsed ? <span className="truncate">{label}</span> : <span className="sr-only">{label}</span>}
    </Link>
  );
}

function ConnectionCard({ collapsed }: { collapsed: boolean }) {
  const health = useCoreHealth();
  const preview = usePreviewMode();
  const tone =
    health === "online" ? "bg-ok" : health === "offline" ? "bg-bad" : "bg-muted";
  const label = health === "online" ? "Core connected" : health === "offline" ? "Core offline" : "Checking core";
  if (collapsed)
    return (
      <div className="mx-auto grid h-10 w-10 place-items-center rounded-[12px] bg-white/[.04]" title={label}>
        <span className={clsx("h-2 w-2 rounded-full", tone, health === "checking" && "pulse-dot")} />
      </div>
    );
  return (
    <div className="rounded-[12px] bg-white/[.04] px-3 py-2.5" aria-live="polite">
      <div className="flex items-center gap-2 text-[14px] font-medium text-fg">
        <span className={clsx("h-2 w-2 rounded-full", tone, health === "checking" && "pulse-dot")} aria-hidden />
        {label}
      </div>
      <p className="mt-0.5 text-[12px] text-muted">
        {preview ? "Preview mode shows sample data" : health === "offline" ? "Run make core to connect" : "127.0.0.1:8000 via proxy"}
      </p>
    </div>
  );
}

function AccountPill({ collapsed }: { collapsed: boolean }) {
  const session = useSession();
  const preview = usePreviewMode();
  const name =
    session.status === "signed-in"
      ? session.session.displayName
      : preview
        ? "Preview"
        : session.status === "loading"
          ? "Checking sign-in"
          : "Not signed in";
  const detail =
    session.status === "signed-in"
      ? session.session.method === "open"
        ? "Sign-in not enforced"
        : session.session.roles.join(", ")
      : preview
        ? "Sample data, no account"
        : session.status === "error"
          ? "Sign-in status unknown"
          : "";
  return (
    <Link
      href="/app/account"
      className={clsx(
        "flex items-center gap-2.5 rounded-[12px] border-[0.8px] border-line px-2.5 py-2 transition-colors duration-300 hover:bg-white/[.04]",
        collapsed && "justify-center border-none px-0",
      )}
      title="Account"
    >
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-white/10 text-[12px] font-semibold text-fg-2">
        <IconUser className="h-4 w-4" />
      </span>
      {!collapsed ? (
        <span className="min-w-0">
          <span className="block truncate text-[14px] font-medium text-fg">{name}</span>
          <span className="block truncate text-[12px] text-muted">{detail}</span>
        </span>
      ) : null}
    </Link>
  );
}

function TopBar({ collapsed, onToggle, onMenu }: { collapsed: boolean; onToggle: () => void; onMenu: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <div className="flex items-center gap-2 px-4 pb-2 pt-[10px] sm:px-6 lg:px-[8px]">
      <IconButton label="Open navigation" onClick={onMenu} className="lg:hidden">
        <IconMenu />
      </IconButton>
      <IconButton label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={onToggle} className="hidden lg:grid">
        {collapsed ? <IconExpand /> : <IconCollapse />}
      </IconButton>
      <Link href="/app" className="flex items-center gap-2 lg:hidden" aria-label="Pramana overview">
        <PramanaMark className="h-[16px] w-auto" />
      </Link>
      <form
        role="search"
        className="ml-auto flex h-[42px] w-full max-w-[280px] items-center gap-2 rounded-full border-[0.8px] border-line px-3.5 focus-within:border-accent/60"
        onSubmit={(e) => {
          e.preventDefault();
          router.push(`/app/investigations${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
        }}
      >
        <IconSearch className="h-4 w-4 shrink-0 text-muted" />
        <label htmlFor="global-search" className="sr-only">
          Search investigations
        </label>
        <input
          id="global-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search investigations..."
          className="w-full bg-transparent text-[15px] text-fg outline-none placeholder:text-muted"
        />
      </form>
    </div>
  );
}

function PreviewBanner() {
  const router = useRouter();
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-t-[16px] border-b border-dashed border-warn/40 bg-warn/[.07] px-4 py-2.5 text-[13px] text-warn sm:px-6">
      <p>
        <strong className="font-semibold">Development preview.</strong> You are looking at sample data. Nothing here
        comes from the core, and actions that would change real data are disabled.
      </p>
      <button
        type="button"
        onClick={() => {
          previewMode.disable();
          router.push("/app");
        }}
        className="rounded-full border border-warn/50 px-3 py-1 text-[12px] font-medium transition-colors hover:bg-warn/10"
      >
        Exit preview
      </button>
    </div>
  );
}
