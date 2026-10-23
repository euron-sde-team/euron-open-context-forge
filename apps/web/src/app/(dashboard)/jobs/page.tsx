import type { Metadata } from "next";

import { JobsScreen } from "@/features/jobs/components/jobs-screen";

export const metadata: Metadata = { title: "Jobs" };

export default function Page() {
  return <JobsScreen />;
}
