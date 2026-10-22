"use client";

import { cn } from "@/lib/utils";

/** Shared native select field styles (saved research status, filters). */
export const nativeSelectClassName = cn(
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground",
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
  "hover:border-ring/60 disabled:cursor-not-allowed disabled:opacity-50",
);

/** Best-effort option colors (native dropdown is browser-controlled). */
export const nativeSelectOptionClassName = "bg-background text-foreground";

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
}

export function Select({ className, label, children, id, ...props }: SelectProps) {
  const selectId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className={cn("space-y-2", className)}>
      {label && (
        <label htmlFor={selectId} className="text-sm font-medium text-foreground">
          {label}
        </label>
      )}
      <select id={selectId} className={cn(nativeSelectClassName, className)} {...props}>
        {children}
      </select>
    </div>
  );
}
