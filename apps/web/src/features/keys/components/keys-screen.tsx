"use client";

import { PlusIcon } from "lucide-react";
import * as React from "react";

import { PageHeader } from "@/components/page-header";
import { Surface } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/features/auth/api";

import { CreateKeyDialog } from "./create-key-dialog";
import { KeysTable } from "./keys-table";

export function KeysScreen() {
  const { canWrite } = usePermissions();
  const [open, setOpen] = React.useState(false);
  const [showRevoked, setShowRevoked] = React.useState(false);
  return (
    <>
      <PageHeader
        title="API keys"
        description="Service keys for /v1/context and the OpenAI-compatible proxy. Stored as a peppered hash; the full key is shown once at creation."
        actions={
          canWrite && (
            <Button onClick={() => setOpen(true)}>
              <PlusIcon />
              New key
            </Button>
          )
        }
      />
      <Surface className="overflow-hidden">
        <div className="flex items-center justify-end gap-2 px-5 pt-3.5 pb-1 text-[12.5px] text-muted-foreground">
          <label htmlFor="show-revoked">Show revoked</label>
          <Switch id="show-revoked" checked={showRevoked} onCheckedChange={setShowRevoked} />
        </div>
        <KeysTable includeRevoked={showRevoked} canWrite={canWrite} onCreate={() => setOpen(true)} />
      </Surface>
      <CreateKeyDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
