import type { Metadata } from "next";

import { ProfilesScreen } from "@/features/profiles/components/profiles-screen";

export const metadata: Metadata = { title: "Profiles" };

export default function Page() {
  return <ProfilesScreen />;
}
