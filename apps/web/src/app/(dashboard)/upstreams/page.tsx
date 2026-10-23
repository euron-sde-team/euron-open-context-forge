import type { Metadata } from "next";

import { UpstreamsScreen } from "@/features/upstreams/components/upstreams-screen";

export const metadata: Metadata = { title: "Upstreams" };

export default function Page() {
  return <UpstreamsScreen />;
}
