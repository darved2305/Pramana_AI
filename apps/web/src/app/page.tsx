import { SiteNav } from "@/components/landing/SiteNav";
import { Hero } from "@/components/landing/Hero";
import {
  ClosingCta,
  ConsolePreview,
  Evidence,
  FloatingPreview,
  Notes,
  Platform,
  SiteFooter,
  Workflow,
} from "@/components/landing/Sections";

export default function LandingPage() {
  return (
    <>
      <SiteNav />
      <main>
        <Hero />
        <Platform />
        <Evidence />
        <Workflow />
        <ConsolePreview />
        <Notes />
        <ClosingCta />
      </main>
      <SiteFooter />
      <FloatingPreview />
    </>
  );
}
