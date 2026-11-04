import Link from "next/link";
import { Wordmark } from "@/components/brand/Wordmark";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col bg-ink px-[var(--gutter)] py-[30px] text-cream">
      <Link href="/" aria-label="Pramana home" className="w-fit">
        <Wordmark />
      </Link>
      <div className="flex flex-1 flex-col items-center justify-center text-center">
        <p className="display-pixel text-[clamp(80px,14vw,200px)] leading-none">404</p>
        <h1 className="display-slab mt-6 text-[clamp(36px,4.5vw,64px)]">Nothing was observed here</h1>
        <p className="mt-4 max-w-[44ch] text-[18px] leading-relaxed text-cream/70">The page you asked for does not exist, or it has moved.</p>
        <div className="mt-8 flex flex-wrap justify-center gap-[13px]">
          <Link href="/" className="btn-line lg">
            Home
          </Link>
          <Link href="/app" className="btn-line lg">
            Console
          </Link>
        </div>
      </div>
    </main>
  );
}
