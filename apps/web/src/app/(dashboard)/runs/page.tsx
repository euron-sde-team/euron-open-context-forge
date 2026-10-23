import type { Metadata } from "next";

import { Suspense } from "react";
import { RunsScreen } from "@/features/runs/components/runs-screen";

export const metadata: Metadata = { title: "Runs" };

export default function Page() {
  return (
    <Suspense>
      <RunsScreen />
    </Suspense>
  );
}
