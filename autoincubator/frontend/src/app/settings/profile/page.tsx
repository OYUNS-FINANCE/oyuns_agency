import type { Metadata } from "next";

import { ProfileForm } from "@/components/profile/profile-form";

export const metadata: Metadata = { title: "Founder profile" };

export default function ProfilePage() {
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="font-serif text-3xl tracking-tight">Founder profile</h1>
        <p className="text-muted-foreground text-sm">
          Autonomous runs read this to decide where to look. Each run keeps a snapshot of the
          profile as it was when the run started.
        </p>
      </header>
      <ProfileForm />
    </div>
  );
}
