"use client";

import { ButtonLink, Card, CardHeader, KeyValue, Notice, PageHeader } from "@/components/ui";
import { IconUser } from "@/components/ui/icons";

export default function AccountPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Account" />
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card className="p-5">
          <div className="flex items-center gap-4">
            <span className="grid h-16 w-16 place-items-center rounded-full bg-white/[.06] text-fg-2">
              <IconUser className="h-7 w-7" />
            </span>
            <div>
              <p className="text-[18px] font-medium">Not signed in</p>
              <p className="text-[14px] text-muted">There is no account system yet.</p>
            </div>
          </div>
          <dl className="mt-5 divide-y divide-line">
            <KeyValue k="Name" v={<span className="text-muted">Not available</span>} />
            <KeyValue k="Email" v={<span className="text-muted">Not available</span>} />
            <KeyValue k="Role" v={<span className="text-muted">Not available</span>} />
          </dl>
        </Card>
        <Card className="p-5">
          <CardHeader title="About sign-in" />
          <Notice className="mt-3">
            The core does not have authentication yet, so the console runs without accounts against your local core. The
            sign-in screen is built and validates input, but it does not create sessions. When authentication is added,
            this page will show the signed-in profile.
          </Notice>
          <div className="mt-4 flex gap-2">
            <ButtonLink href="/login">Open sign-in screen</ButtonLink>
            <ButtonLink href="/app/settings" variant="ghost">
              Settings
            </ButtonLink>
          </div>
        </Card>
      </div>
    </div>
  );
}
