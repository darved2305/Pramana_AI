"use client";

import { useEffect, useState } from "react";
import { Wordmark } from "@/components/brand/Wordmark";
import { Button, Notice, Skeleton } from "@/components/ui";
import { ApiError } from "@/lib/api/http";
import { consentApi } from "@/lib/api/consent";
import type { ConsentLinkView } from "@/lib/api/types";

type Choice = "granted" | "refused";

const COPY = {
  en: {
    title: "May Pramana ask you questions?",
    intro: "The site team would like Pramana to ask you questions on the web during an investigation.",
    detail: "This choice is only for web questions. It does not allow phone calls, SMS or WhatsApp messages. You can say yes or no, and you can change your mind later by asking the site team.",
    agree: "Yes, I agree",
    refuse: "No, I do not agree",
    loading: "Loading your consent request...",
    invalid: "This link has expired or has already been used. Ask the site team for a new link.",
    unavailable: "Pramana could not be reached. Check your connection and try again.",
    granted: "Your choice is recorded. The site may ask you questions on the web during investigations.",
    refused: "Your choice is recorded. The site will not ask you new questions on the web.",
    working: "Saving your choice...",
  },
  hi: {
    title: "क्या Pramana आपसे सवाल पूछ सकता है?",
    intro: "साइट टीम चाहती है कि जाँच के दौरान Pramana आपसे वेब पर सवाल पूछे।",
    detail: "यह अनुमति केवल वेब पर सवालों के लिए है। इससे फोन कॉल, SMS या WhatsApp संदेश भेजने की अनुमति नहीं मिलती। आप हाँ या नहीं चुन सकते हैं। बाद में साइट टीम से कहकर अपना फैसला बदल सकते हैं।",
    agree: "हाँ, मैं सहमत हूँ",
    refuse: "नहीं, मैं सहमत नहीं हूँ",
    loading: "आपकी सहमति का अनुरोध खुल रहा है...",
    invalid: "यह लिंक समाप्त हो गया है या इस्तेमाल किया जा चुका है। साइट टीम से नया लिंक माँगें।",
    unavailable: "Pramana से संपर्क नहीं हो पाया। अपना इंटरनेट कनेक्शन जाँचकर फिर से कोशिश करें।",
    granted: "आपका फैसला दर्ज हो गया है। साइट जाँच के दौरान आपसे वेब पर सवाल पूछ सकती है।",
    refused: "आपका फैसला दर्ज हो गया है। साइट अब आपसे वेब पर नए सवाल नहीं पूछेगी।",
    working: "आपका फैसला सहेजा जा रहा है...",
  },
  mr: {
    title: "Pramana तुम्हाला प्रश्न विचारू शकतो का?",
    intro: "तपासादरम्यान Pramana ने तुम्हाला वेबवर प्रश्न विचारावेत अशी साइट टीमची विनंती आहे.",
    detail: "ही परवानगी फक्त वेबवरील प्रश्नांसाठी आहे. यामुळे फोन कॉल, SMS किंवा WhatsApp संदेश पाठवण्याची परवानगी मिळत नाही. तुम्ही हो किंवा नाही निवडू शकता. नंतर साइट टीमला सांगून तुमचा निर्णय बदलू शकता.",
    agree: "हो, मी सहमत आहे",
    refuse: "नाही, मी सहमत नाही",
    loading: "तुमची संमतीची विनंती उघडत आहे...",
    invalid: "ही लिंक कालबाह्य झाली आहे किंवा वापरली गेली आहे. साइट टीमकडून नवीन लिंक मागा.",
    unavailable: "Pramana शी संपर्क होऊ शकला नाही. इंटरनेट कनेक्शन तपासून पुन्हा प्रयत्न करा.",
    granted: "तुमचा निर्णय नोंदवला आहे. तपासादरम्यान साइट तुम्हाला वेबवर प्रश्न विचारू शकते.",
    refused: "तुमचा निर्णय नोंदवला आहे. साइट तुम्हाला वेबवर नवीन प्रश्न विचारणार नाही.",
    working: "तुमचा निर्णय जतन करत आहोत...",
  },
} as const;

export function ConsentForm({ token }: { token: string }) {
  const [link, setLink] = useState<ConsentLinkView | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState<Choice | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    consentApi
      .read(token, controller.signal)
      .then(setLink)
      .catch((cause) => {
        if ((cause as Error).name !== "AbortError") {
          setError(cause instanceof ApiError && cause.code === "CONSENT_LINK_INVALID" ? "invalid" : "unavailable");
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [token]);

  const language = link?.language === "hi" || link?.language === "hi-en"
    ? "hi"
    : link?.language === "mr"
      ? "mr"
      : "en";
  const copy = COPY[language];

  async function respond(choice: Choice) {
    setBusy(true);
    setError(null);
    try {
      const result = await consentApi.respond(token, choice);
      setDecision(result.decision);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.code === "CONSENT_LINK_INVALID" ? "invalid" : "unavailable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-ink text-cream">
      <header className="px-6 py-6 sm:px-[50px]"><Wordmark /></header>
      <main className="mx-auto flex w-full max-w-[560px] flex-1 flex-col justify-center gap-5 px-5 pb-12 sm:px-6">
        {loading ? (
          <div className="flex flex-col gap-4" aria-busy="true" aria-label={copy.loading}>
            <Skeleton className="h-12" />
            <Skeleton className="h-28" />
            <Skeleton className="h-12" />
          </div>
        ) : error && !link ? (
          <Notice tone="warn" title="Consent link unavailable">{error === "invalid" ? copy.invalid : copy.unavailable}</Notice>
        ) : decision ? (
          <>
            <h1 className="display-slab text-[clamp(34px,4vw,52px)] leading-tight">{decision === "granted" ? copy.agree : copy.refuse}</h1>
            <Notice tone={decision === "granted" ? "ok" : "info"}>{decision === "granted" ? copy.granted : copy.refused}</Notice>
          </>
        ) : link ? (
          <>
            <p className="text-[12px] font-medium uppercase tracking-[.16em] text-accent">Pramana consent</p>
            <h1 className="display-slab text-[clamp(34px,4vw,52px)] leading-tight">{copy.title}</h1>
            <p className="text-[17px] leading-relaxed text-cream/80">{copy.intro}</p>
            <p className="rounded-[14px] border-[0.8px] border-white/10 bg-white/[.03] px-4 py-3 text-[14px] leading-relaxed text-cream/65">{copy.detail}</p>
            {error ? <p role="alert" className="text-[14px] text-[#ff8a7f]">{error === "invalid" ? copy.invalid : copy.unavailable}</p> : null}
            <p className="text-[12px] text-cream/50">{copy.working && busy ? copy.working : ""}</p>
            <div className="flex flex-col gap-3 pt-2 sm:flex-row">
              <Button variant="primary" size="lg" loading={busy} disabled={busy} onClick={() => void respond("granted")}>
                {copy.agree}
              </Button>
              <Button size="lg" loading={busy} disabled={busy} onClick={() => void respond("refused")}>
                {copy.refuse}
              </Button>
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
