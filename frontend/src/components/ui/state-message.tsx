"use client";

import { AlertCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface StateMessageProps {
  title: string;
  description?: string;
  variant?: "error" | "empty" | "loading";
  className?: string;
}

export function StateMessage({ title, description, variant = "empty", className }: StateMessageProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-border/80 px-6 py-16 text-center",
        className,
      )}
    >
      {variant === "loading" && <Loader2 className="mb-4 h-8 w-8 animate-spin text-primary" />}
      {variant === "error" && <AlertCircle className="mb-4 h-8 w-8 text-destructive" />}
      <h3 className="text-lg font-medium">{title}</h3>
      {description && <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>}
    </div>
  );
}
