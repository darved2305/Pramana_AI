"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { Wordmark } from "@/components/brand/Wordmark";
import { accountApi, actionKey } from "@/lib/api/account";
import { ApiError, describeError } from "@/lib/api/http";
import type { CurrentAccount, OnboardingAnswers, OnboardingState, OnboardingStep } from "@/lib/api/types";
import { refreshAccount, useAccount } from "@/lib/data/account";

/** The steps a new person walks through, in order. ``join``/``waiting`` are for invitations. */
const FLOW: { id: OnboardingStep; label: string }[] = [
  { id: "welcome", label: "Welcome" },
  { id: "survey", label: "About you" },
  { id: "org", label: "Workspace" },
  { id: "sandbox", label: "Practice" },
  { id: "site", label: "Your site" },
  { id: "people", label: "People" },
  { id: "test_call", label: "Test call" },
];

type Problem = NonNullable<OnboardingAnswers["problem"]> | "water" | "cooling" | "lifts" | "devices";

const WORK: { id: NonNullable<OnboardingAnswers["work"]>; label: string }[] = [
  { id: "facilities", label: "I run facilities or maintenance" },
  { id: "it", label: "I look after IT or the network" },
  { id: "duty_manager", label: "I am a duty or shift manager" },
  { id: "technician", label: "I fix things on site" },
  { id: "representative", label: "I represent residents or staff" },
  { id: "other", label: "Something else" },
];
const KIND: { id: NonNullable<OnboardingAnswers["organization_kind"]>; label: string }[] = [
  { id: "campus", label: "Campus or hostel" },
  { id: "hospital", label: "Hospital or clinic" },
  { id: "office", label: "Office" },
  { id: "hotel", label: "Hotel" },
  { id: "retail", label: "Shop or retail branch" },
  { id: "other", label: "Something else" },
];
const BUILDINGS: { id: NonNullable<OnboardingAnswers["buildings"]>; label: string }[] = [
  { id: "one", label: "One" },
  { id: "two_to_five", label: "2 to 5" },
  { id: "six_to_twenty", label: "6 to 20" },
  { id: "more_than_twenty", label: "More than 20" },
];
const PROBLEM: { id: Problem; label: string; template: string | null }[] = [
  { id: "wifi", label: "Wi-Fi and network", template: null },
  { id: "power", label: "Power and breakers", template: null },
  { id: "water", label: "Water supply", template: "office_water" },
  { id: "cooling", label: "Cooling and air", template: "ward_cooling" },
  { id: "devices", label: "Tills, terminals and devices", template: "retail_billing" },
  { id: "lifts", label: "Lifts", template: null },
  { id: "other", label: "Something else", template: null },
];
type Language = NonNullable<OnboardingAnswers["languages"]>[number];
const LANGS: { id: Language; label: string }[] = [
  { id: "hi", label: "Hindi" },
  { id: "mr", label: "Marathi" },
  { id: "en", label: "English" },
  { id: "hi-en", label: "Hinglish" },
];

export default function OnboardingPage() {
  const { step } = useParams<{ step: OnboardingStep }>();
  const router = useRouter();
  const account = useAccount();
  const [state, setState] = useState<OnboardingState | null>(null);
  // Refs hold the newest saved state, so a quick second click builds on the first one.
  const latest = useRef<{ state: OnboardingState | null; etag: string | null; saved: OnboardingAnswers | null }>({ state: null, etag: null, saved: null });
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [joinBusy, setJoinBusy] = useState<string | null>(null);
  const [requested, setRequested] = useState<Record<string, string>>({});
  const joinKeys = useRef(new Map<string, string>());
  const cancelKeys = useRef(new Map<string, string>());

  function adopt(next: OnboardingState, etag: string | null) {
    latest.current = { state: next, etag, saved: next.answers };
    setState(next);
  }

  useEffect(() => {
    if (account.status === "signed-out") router.replace(`/login?next=${encodeURIComponent(`/onboarding/${step}`)}`);
  }, [account.status, router, step]);
  useEffect(() => {
    let alive = true;
    accountApi
      .onboarding()
      .then((r) => {
        if (!alive) return;
        adopt(r.state, r.etag);
      })
      .catch((e) => alive && !(e instanceof ApiError && e.status === 401) && setError(describeError(e)));
    return () => {
      alive = false;
    };
  }, []);

  /** Save a change; the core keeps it, so the person resumes here on any device. */
  async function save(patch: { answers?: Partial<OnboardingAnswers>; step?: OnboardingStep; dismissed?: boolean }) {
    const shown = latest.current.state;
    if (!shown || !latest.current.etag) return null;
    if (patch.answers) {
      // Show the choice at once and let later clicks add to it while this one is saving.
      const next = { ...shown, answers: { ...shown.answers, ...patch.answers } };
      latest.current.state = next;
      setState(next);
    }
    setBusy(true);
    setError(null);
    const run = queue.current.then(() => send(patch));
    queue.current = run;
    return run;
  }
  /** Saves run one at a time: each needs the version the one before it returned. */
  async function send(patch: { answers?: Partial<OnboardingAnswers>; step?: OnboardingStep; dismissed?: boolean }) {
    const { state: current, etag } = latest.current;
    if (!current || !etag) return null;
    try {
      const body = { ...patch, answers: patch.answers ? current.answers : undefined };
      const r = await accountApi.saveOnboarding(body as never, etag, actionKey("onboarding"));
      // A later choice may already be on screen: keep it until its own save returns.
      latest.current = { state: { ...r.state, answers: { ...r.state.answers, ...diff(current.answers, latest.current.state?.answers) } }, etag: r.etag, saved: r.state.answers };
      setState(latest.current.state);
      return r.state;
    } catch (e) {
      try {
        const fresh = await accountApi.onboarding();
        adopt(fresh.state, fresh.etag);
      } catch {
        if (latest.current.state && latest.current.saved) setState({ ...latest.current.state, answers: latest.current.saved });
      }
      setError(e instanceof ApiError && e.status === 412 ? "This changed in another tab. We loaded the latest version." : describeError(e));
      return null;
    } finally {
      setBusy(false);
    }
  }
  async function go(next: OnboardingStep) {
    const saved = await save({ step: next });
    if (saved) router.push(next === "done" ? await finishDestination() : `/onboarding/${next}`);
  }
  async function finishDestination() {
    const fresh = await refreshAccount();
    return fresh.status === "ready" ? fresh.account.destination : "/app";
  }

  async function requestToJoin(organizationId: string) {
    setJoinBusy(organizationId);
    setError(null);
    const key = joinKeys.current.get(organizationId) ?? actionKey("domain-join");
    joinKeys.current.set(organizationId, key);
    try {
      const result = await accountApi.requestJoin(organizationId, key);
      if (result.joined && result.destination) {
        await refreshAccount();
        router.push(result.destination);
        return;
      }
      setRequested((current) => ({ ...current, [organizationId]: result.request.id }));
      await refreshAccount();
    } catch (e) {
      if (e instanceof ApiError && !e.unreachable && e.code !== "IDEMPOTENCY_IN_FLIGHT") {
        joinKeys.current.delete(organizationId);
      }
      setError(describeError(e));
    } finally {
      setJoinBusy(null);
    }
  }

  async function cancelJoin(organizationId: string, requestId: string) {
    setJoinBusy(organizationId);
    setError(null);
    const key = cancelKeys.current.get(requestId) ?? actionKey("cancel-join");
    cancelKeys.current.set(requestId, key);
    try {
      await accountApi.cancelJoinRequest(requestId, key);
      cancelKeys.current.delete(requestId);
      joinKeys.current.delete(organizationId);
      setRequested((current) => {
        const next = { ...current };
        delete next[organizationId];
        return next;
      });
      await refreshAccount();
    } catch (e) {
      if (e instanceof ApiError && !e.unreachable && e.code !== "IDEMPOTENCY_IN_FLIGHT") {
        cancelKeys.current.delete(requestId);
      }
      setError(describeError(e));
    } finally {
      setJoinBusy(null);
    }
  }

  const workspace =
    account.status === "ready" && state?.org_id
      ? account.account.memberships.find((m) => m.id === state.org_id) ?? null
      : null;
  const joinSuggestions =
    account.status === "ready" ? account.account.join_suggestions ?? [] : [];
  const index = FLOW.findIndex((f) => f.id === step);

  return (
    <div className="flex min-h-dvh flex-col bg-ink text-cream">
      <header className="flex items-center justify-between gap-4 px-6 py-6 sm:px-[50px]">
        <Wordmark />
        {workspace ? (
          <button type="button" className="btn-line" disabled={busy} onClick={async () => {
            if (await save({ dismissed: true })) router.push(`/app/${workspace.slug}`);
          }}>
            Skip setup for now
          </button>
        ) : null}
      </header>
      <ol className="mx-auto flex w-full max-w-[860px] flex-wrap gap-2 px-6" aria-label="Setup steps">
        {FLOW.map((f, i) => (
          <li key={f.id} aria-current={f.id === step ? "step" : undefined}
            className={clsx("rounded-full px-3 py-1 text-[12px]", i < index ? "bg-cream/15 text-cream" : f.id === step ? "bg-cream text-ink" : "text-cream/45 shadow-[inset_0_0_0_0.8px_rgba(255,255,255,.2)]")}>
            {i + 1}. {f.label}
          </li>
        ))}
      </ol>
      <main className="mx-auto flex w-full max-w-[860px] flex-1 flex-col px-6 py-10">
        {error ? <p role="alert" className="mb-6 rounded-[14px] border-[0.8px] border-[#ff6b5e]/60 px-4 py-3 text-[14px] text-[#ff8a7f]">{error}</p> : null}
        {!state ? (
          <p className="text-cream/60" aria-busy="true">Loading your setup...</p>
        ) : step === "welcome" ? (
          <Step title="Find out what is wrong by asking the people who are there" lead="When something breaks where there are no sensors, Pramana works out who can check what, asks them by voice in their own language, and reasons from their answers to the cause. Setting up takes a few minutes.">
            {account.status === "ready" && (account.account.pending_invitations ?? []).length > 0 ? (
              <Invitations invitations={account.account.pending_invitations ?? []} onJoined={(dest) => router.push(dest)} />
            ) : null}
            {joinSuggestions.length > 0 ? (
              <DomainJoinChoices
                suggestions={joinSuggestions}
                localRequests={requested}
                busyId={joinBusy}
                onRequest={requestToJoin}
                onCancel={cancelJoin}
              />
            ) : null}
            <Primary busy={busy || joinBusy !== null} onClick={() => go("survey")}>
              {joinSuggestions.length > 0
                ? "Create a separate organization"
                : "Get started"}
            </Primary>
          </Step>
        ) : step === "survey" ? (
          <Survey answers={state.answers} busy={busy} onChange={(a) => save({ answers: a })} onNext={() => go("org")} />
        ) : step === "org" ? (
          <CreateWorkspace answers={state.answers} existing={account.status === "ready" ? account.account.memberships.length : 0} onCreated={async (dest) => {
            const fresh = await accountApi.onboarding();
            adopt(fresh.state, fresh.etag);
            await refreshAccount();
            router.push(dest);
          }} />
        ) : !workspace ? (
          <Step title="Create your workspace first" lead="The next steps happen inside a workspace.">
            <Primary busy={busy} onClick={() => go("org")}>Create a workspace</Primary>
          </Step>
        ) : step === "sandbox" ? (
          <Step title="See one investigation from start to finish" lead="A simulated site has a hidden fault. You report the problem, Pramana asks simulated colleagues what they see, and at the end the hidden fault is revealed so you can check its reasoning. Nothing real is touched.">
            <div className="flex flex-wrap gap-3">
              <Link href={`/app/${workspace.slug}/investigations/new?practice=1`} className="btn-cream">Start a practice investigation</Link>
              <Secondary busy={busy} onClick={() => go("site")}>Skip, I will try it later</Secondary>
            </div>
          </Step>
        ) : step === "site" ? (
          <SiteStep slug={workspace.slug} problem={state.answers.problem as Problem | null | undefined} busy={busy} onNext={() => go("people")} />
        ) : step === "people" ? (
          <Step title="Who can help when something breaks?" lead="Add facilities staff, technicians and the people who are there each day. Pramana only asks people to check things their role allows. Their answers help it check your site description.">
            <div className="flex flex-wrap gap-3">
              <Link href={`/app/${workspace.slug}/people`} className="btn-cream">Add people</Link>
              <Secondary busy={busy} onClick={() => go("test_call")}>Continue</Secondary>
            </div>
          </Step>
        ) : step === "test_call" ? (
          <Step title="Check your microphone and speaker" lead="People answer Pramana by voice. Try it once on this device so you know what they will hear.">
            <div className="flex flex-wrap gap-3">
              <Link href="/app/voice" className="btn-cream">Open the voice check</Link>
              <Primary busy={busy} onClick={() => go("done")}>Finish setup</Primary>
            </div>
          </Step>
        ) : (
          <Step title="You are set up" lead="Your workspace home shows what needs you first, and why.">
            <Link href={`/app/${workspace.slug}`} className="btn-cream">Open my workspace</Link>
          </Step>
        )}
      </main>
    </div>
  );
}

/** The answers in ``after`` that differ from ``before``. */
function diff(before: OnboardingAnswers, after: OnboardingAnswers | undefined): Partial<OnboardingAnswers> {
  return Object.fromEntries(Object.entries(after ?? {}).filter(([k, v]) => JSON.stringify(before[k as keyof OnboardingAnswers]) !== JSON.stringify(v)));
}

function Step({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-6">
      <h1 className="display-slab max-w-[18ch] text-[clamp(38px,4.4vw,60px)]">{title}</h1>
      <p className="max-w-[62ch] text-[17px] leading-relaxed text-cream/75">{lead}</p>
      <div className="pt-2">{children}</div>
    </section>
  );
}

function Primary({ children, onClick, busy }: { children: ReactNode; onClick: () => void; busy: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={busy} className="btn-cream disabled:opacity-50">
      {busy ? "Saving..." : children}
    </button>
  );
}
function Secondary({ children, onClick, busy }: { children: ReactNode; onClick: () => void; busy: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={busy} className="btn-line disabled:opacity-50">
      {children}
    </button>
  );
}

function Choice<T extends string>({ legend, options, value, onPick }: { legend: string; options: { id: T; label: string }[]; value: T | null | undefined; onPick: (v: T) => void }) {
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-3 text-[15px] font-medium text-cream">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <button key={o.id} type="button" aria-pressed={value === o.id} onClick={() => onPick(o.id)}
            className={clsx("min-h-[44px] rounded-full px-4 text-[15px] transition-colors", value === o.id ? "bg-cream text-ink" : "text-cream/80 shadow-[inset_0_0_0_0.8px_rgba(255,255,255,.35)] hover:text-cream")}>
            {o.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function Survey({ answers, busy, onChange, onNext }: { answers: OnboardingAnswers; busy: boolean; onChange: (a: Partial<OnboardingAnswers>) => void; onNext: () => void }) {
  const ready = Object.values(answers).some((v) => (Array.isArray(v) ? v.length > 0 : Boolean(v)));
  return (
    <section className="flex flex-col gap-8">
      <h1 className="display-slab text-[clamp(38px,4.4vw,60px)]">A little about you</h1>
      <p className="-mt-4 max-w-[62ch] text-[16px] text-cream/70">Your answers choose your starting template and what your home shows first. Each choice is saved as you go.</p>
      <Choice legend="What do you do?" options={WORK} value={answers.work} onPick={(work) => onChange({ work })} />
      <Choice legend="What kind of place is it?" options={KIND} value={answers.organization_kind} onPick={(organization_kind) => onChange({ organization_kind })} />
      <Choice legend="How many buildings?" options={BUILDINGS} value={answers.buildings} onPick={(buildings) => onChange({ buildings })} />
      <Choice legend="What goes wrong most often?" options={PROBLEM} value={answers.problem as Problem | null | undefined} onPick={(problem) => onChange({ problem: problem as OnboardingAnswers["problem"] })} />
      <fieldset>
        <legend className="mb-3 text-[15px] font-medium text-cream">Which languages do people there speak?</legend>
        <div className="flex flex-wrap gap-2">
          {LANGS.map((l) => {
            const chosen = answers.languages ?? [];
            const on = chosen.includes(l.id);
            return (
              <button key={l.id} type="button" aria-pressed={on} onClick={() => onChange({ languages: on ? chosen.filter((x) => x !== l.id) : [...chosen, l.id] })}
                className={clsx("min-h-[44px] rounded-full px-4 text-[15px]", on ? "bg-cream text-ink" : "text-cream/80 shadow-[inset_0_0_0_0.8px_rgba(255,255,255,.35)]")}>
                {l.label}
              </button>
            );
          })}
        </div>
      </fieldset>
      <div>
        <Primary busy={busy} onClick={onNext}>{ready ? "Continue" : "Continue without answering"}</Primary>
      </div>
    </section>
  );
}

function CreateWorkspace({ answers, existing, onCreated }: { answers: OnboardingAnswers; existing: number; onCreated: (destination: string) => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(actionKey("workspace")); // one key per attempt, so a retry never makes two
  return (
    <section className="flex flex-col gap-6">
      <h1 className="display-slab text-[clamp(38px,4.4vw,60px)]">Name your workspace</h1>
      <p className="max-w-[62ch] text-[16px] text-cream/70">
        A workspace keeps your sites, people and problem reports together. You get a guided example and a blank site to describe.
        {existing ? ` You already belong to ${existing} workspace${existing === 1 ? "" : "s"}; this adds another.` : ""}
      </p>
      <form className="flex max-w-[460px] flex-col gap-4" onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          const created = await accountApi.createOrganization({ name: name.trim() || undefined, kind: answers.organization_kind ?? undefined }, key.current);
          onCreated(created.destination);
        } catch (x) {
          setError(describeError(x));
          if (!(x instanceof ApiError && x.status >= 500)) key.current = actionKey("workspace");
        } finally {
          setBusy(false);
        }
      }}>
        <label htmlFor="ws-name" className="text-[13px] font-medium uppercase tracking-[0.06em] text-cream/70">Workspace name</label>
        <input id="ws-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="Riverside Offices"
          className="h-[52px] w-full border-[0.8px] border-cream/40 bg-transparent px-4 text-[16px] text-cream outline-none placeholder:text-cream/35 focus:rounded-[26px] focus:border-cream" />
        {error ? <p role="alert" className="text-[14px] text-[#ff8a7f]">{error}</p> : null}
        <button type="submit" disabled={busy} className="btn-cream disabled:opacity-50">{busy ? "Creating..." : "Create workspace"}</button>
      </form>
    </section>
  );
}

function SiteStep({ slug, problem, busy, onNext }: { slug: string; problem: Problem | null | undefined; busy: boolean; onNext: () => void }) {
  const suggested = PROBLEM.find((p) => p.id === problem)?.template ?? null;
  return (
    <Step title="Describe your own site" lead={suggested
      ? "Based on your answers, start from the closest template, then change it to match what is really there. Pramana checks your site description before you publish it."
      : "Pick the closest template, or start from scratch: list your places, the people who work there, the equipment and what each item needs to work. Pramana checks your site description before you publish it."}>
      <div className="flex flex-wrap gap-3">
        <Link href={`/app/${slug}/sites${suggested ? `?template=${suggested}` : ""}`} className="btn-cream">Describe my site</Link>
        <Secondary busy={busy} onClick={onNext}>Continue</Secondary>
      </div>
    </Step>
  );
}

/** Workspaces that invited this verified address: joining needs no link. */
function Invitations({
  invitations,
  onJoined,
}: {
  invitations: NonNullable<CurrentAccount["pending_invitations"]>;
  onJoined: (destination: string) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const keys = useRef(new Map<string, string>());

  async function join(organizationId: string, id: string) {
    setBusy(id);
    setProblem(null);
    const key = keys.current.get(id) ?? actionKey("accept");
    keys.current.set(id, key);
    try {
      const joined = await accountApi.acceptPendingInvitation(organizationId, id, key);
      await refreshAccount();
      onJoined(joined.destination);
    } catch (e) {
      setProblem(describeError(e));
      setBusy(null);
    }
  }

  return (
    <section aria-label="Invitations" className="mb-8 flex flex-col gap-3">
      <h2 className="text-[20px] font-medium text-cream">You have been invited</h2>
      {problem ? <p className="text-[14px] text-[#ff8a7f]">{problem}</p> : null}
      <ul className="flex flex-col gap-3">
        {invitations.map((invite) => (
          <li key={invite.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[14px] border-[0.8px] border-cream/25 px-4 py-3">
            <span className="text-[16px] text-cream">
              {invite.organization_name}
              <span className="ml-2 text-[14px] text-cream/60">{invite.roles.join(", ")}</span>
            </span>
            <button type="button" className="btn-cream disabled:opacity-50" disabled={busy !== null} onClick={() => join(invite.organization_id, invite.id)}>
              {busy === invite.id ? "Joining..." : "Join"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DomainJoinChoices({
  suggestions,
  localRequests,
  busyId,
  onRequest,
  onCancel,
}: {
  suggestions: NonNullable<CurrentAccount["join_suggestions"]>;
  localRequests: Record<string, string>;
  busyId: string | null;
  onRequest: (organizationId: string) => void;
  onCancel: (organizationId: string, requestId: string) => void;
}) {
  return (
    <section aria-labelledby="domain-join-heading" className="mb-6 flex flex-col gap-3">
      <h2 id="domain-join-heading" className="text-[20px] font-medium text-cream">Workspaces for your verified email</h2>
      <p className="text-[14px] leading-relaxed text-cream/65">
        You can create a separate organization and use its sandbox while an admin reviews your request.
      </p>
      <ul className="flex flex-col gap-3">
        {suggestions.map((suggestion) => {
          const requestId = localRequests[suggestion.organization_id] ?? suggestion.request_id;
          const pending = Boolean(requestId);
          return (
            <li key={suggestion.organization_id} className="flex flex-wrap items-center justify-between gap-3 rounded-[14px] border-[0.8px] border-cream/25 px-4 py-3">
              <span className="min-w-0 flex-1 text-[15px] text-cream">
                {suggestion.organization_name}
                <span className="ml-2 block text-[12px] text-cream/55">Verified domain: {suggestion.domain}</span>
                {pending ? <span className="mt-1 block text-[13px] text-cream/70">Request sent. You can create a separate organization to use a sandbox.</span> : null}
              </span>
              {pending && requestId ? (
                <button type="button" className="btn-line disabled:opacity-50" disabled={busyId !== null} onClick={() => onCancel(suggestion.organization_id, requestId)}>
                  {busyId === suggestion.organization_id ? "Saving..." : "Cancel request"}
                </button>
              ) : (
                <button type="button" className="btn-cream disabled:opacity-50" disabled={busyId !== null} onClick={() => onRequest(suggestion.organization_id)}>
                  {busyId === suggestion.organization_id
                    ? "Sending request..."
                    : suggestion.policy === "auto"
                      ? `Join ${suggestion.organization_name}`
                      : `Request to join ${suggestion.organization_name}`}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
