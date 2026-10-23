import { CircleAlert, Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function LoadingState({
  label = "Loading…",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <p
      role="status"
      className={cn("text-muted-foreground flex items-center gap-2 py-10 text-sm", className)}
    >
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}
    </p>
  );
}

export function ErrorState({
  title,
  message,
  onRetry,
  children,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="border-destructive/30 bg-destructive/5 flex flex-col gap-2 rounded-lg border p-4 text-sm"
    >
      <p className="text-destructive flex items-center gap-2 font-medium">
        <CircleAlert className="size-4" aria-hidden /> {title}
      </p>
      <p className="text-muted-foreground">{message}</p>
      {(onRetry || children) && (
        <div className="flex flex-wrap gap-2 pt-1">
          {onRetry && (
            <Button size="sm" variant="outline" onClick={onRetry}>
              Try again
            </Button>
          )}
          {children}
        </div>
      )}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-6 py-12 text-center">
      <Icon className="text-muted-foreground size-5" aria-hidden />
      <p className="font-medium">{title}</p>
      {children && <div className="text-muted-foreground max-w-sm text-sm">{children}</div>}
    </div>
  );
}
