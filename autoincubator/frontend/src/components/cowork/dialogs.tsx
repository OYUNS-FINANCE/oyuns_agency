"use client";

import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { describeError } from "@/lib/format";

function Confirm({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  tone = "default",
  pending,
  error,
  onConfirm,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  tone?: "default" | "destructive";
  pending: boolean;
  error: unknown;
  onConfirm: () => void;
  children?: ReactNode;
}) {
  return (
    <AlertDialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <AlertDialogContent>
        <AlertDialogTitle>{title}</AlertDialogTitle>
        <AlertDialogDescription render={<div />}>{description}</AlertDialogDescription>
        {children}
        {error != null && (
          <p role="alert" className="text-destructive text-sm">
            {describeError(error)}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <AlertDialogClose render={<Button variant="outline" disabled={pending} />}>
            Cancel
          </AlertDialogClose>
          <Button
            variant={tone === "destructive" ? "destructive" : "default"}
            disabled={pending}
            onClick={onConfirm}
          >
            {pending && <Loader2 className="animate-spin" aria-hidden />}
            {confirmLabel}
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function RejectDialog({
  open,
  onOpenChange,
  title,
  pending,
  error,
  onReject,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  pending: boolean;
  error: unknown;
  onReject: (reason: string | null) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <Confirm
      open={open}
      onOpenChange={onOpenChange}
      title={`Reject “${title}”?`}
      description="It leaves the ranking. A reason is remembered in your founder profile, so future autonomous runs steer away from similar ideas."
      confirmLabel="Reject idea"
      tone="destructive"
      pending={pending}
      error={error}
      onConfirm={() => onReject(reason.trim() || null)}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="reject-reason">Reason (optional)</Label>
        <Textarea
          id="reject-reason"
          value={reason}
          maxLength={300}
          placeholder="e.g. needs a field sales team"
          onChange={(e) => setReason(e.target.value)}
        />
      </div>
    </Confirm>
  );
}

export function DevelopDialog({
  open,
  onOpenChange,
  title,
  pending,
  error,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  pending: boolean;
  error: unknown;
  onConfirm: () => void;
}) {
  return (
    <Confirm
      open={open}
      onOpenChange={onOpenChange}
      title="Develop the full business plan?"
      description={
        <>
          <p>
            “{title}” at its latest version goes into deep development. Co-working closes for this
            run: other ideas can no longer be edited, merged or selected.
          </p>
        </>
      }
      confirmLabel="Develop business plan"
      pending={pending}
      error={error}
      onConfirm={onConfirm}
    />
  );
}

export function MergeDialog({
  open,
  onOpenChange,
  titles,
  pending,
  error,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  titles: string[];
  pending: boolean;
  error: unknown;
  onConfirm: () => void;
}) {
  return (
    <Confirm
      open={open}
      onOpenChange={onOpenChange}
      title={`Merge ${titles.length} ideas?`}
      description={
        <>
          <p>
            The Trend Scout combines them into one hybrid; then the Analyst and the Devil’s Advocate
            analyse and score it. The originals stay in the list.
          </p>
          <ul className="mt-2 list-disc pl-5">
            {titles.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </>
      }
      confirmLabel="Merge"
      pending={pending}
      error={error}
      onConfirm={onConfirm}
    />
  );
}
