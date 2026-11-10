import type { Metadata } from "next";
import { ConsentForm } from "./ConsentForm";

export const metadata: Metadata = {
  title: "Consent | Pramana",
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

export default async function ConsentPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <ConsentForm token={token} />;
}
