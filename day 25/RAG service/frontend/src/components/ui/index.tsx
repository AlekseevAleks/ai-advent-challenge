/** Переиспользуемые UI-примитивы в стиле shadcn/ui (Tailwind + CSS-переменные). */

import { CheckCircle2, CircleAlert, Info, Loader2, TriangleAlert, X } from "lucide-react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import React, { useEffect, useId, useRef, useState } from "react";
import { cn } from "../../lib/utils";

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

type ButtonVariant = "default" | "secondary" | "outline" | "ghost" | "destructive";
type ButtonSize = "default" | "sm" | "lg" | "icon";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: boolean;
}

export function Button({
  variant = "default",
  size = "default",
  loading = false,
  className,
  disabled,
  children,
  ...rest
}: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 rounded-md whitespace-nowrap";
  const variants: Record<ButtonVariant, string> = {
    default: "bg-primary DEFAULT text-primary-foreground hover:bg-primary DEFAULT/90 shadow-sm",
    secondary: "bg-secondary DEFAULT text-secondary-foreground hover:bg-secondary DEFAULT/80",
    outline: "border border-border bg-transparent hover:bg-accent DEFAULT text-accent-foreground",
    ghost: "hover:bg-accent DEFAULT hover:text-accent-foreground",
    destructive: "bg-destructive DEFAULT text-destructive-foreground hover:bg-destructive DEFAULT/90",
  };
  const sizes: Record<ButtonSize, string> = {
    default: "h-9 px-4 text-sm",
    sm: "h-8 px-3 text-xs",
    lg: "h-11 px-6 text-base",
    icon: "h-9 w-9",
  };
  return (
    <button
      type="button"
      className={cn(base, variants[variant], sizes[size], className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

interface BadgeProps {
  variant?: "default" | "secondary" | "success" | "warning" | "error" | "outline";
  className?: string;
  children: React.ReactNode;
  title?: string;
}

const badgeVariants: Record<string, string> = {
  default: "bg-[hsl(var(--primary)/0.14)] text-foreground",
  secondary: "bg-secondary DEFAULT text-secondary-foreground",
  success: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  warning: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30",
  error: "bg-red-500/15 text-red-600 dark:text-red-400",
  outline: "border border-border text-muted-foreground",
};

export function Badge({ variant = "default", className, children, title }: BadgeProps) {
  return (
    <span title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
        badgeVariants[variant], className,
      )}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string;
  children?: React.ReactNode;
}

export function Card({ className, children, ...rest }: CardProps) {
  return (
    <div className={cn("rounded-lg border border-border bg-card DEFAULT shadow-sm", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex flex-col space-y-1.5 px-5 py-4", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...rest }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn("text-base font-semibold leading-none tracking-tight text-card-foreground", className)} {...rest}>
      {children}
    </h3>
  );
}

export function CardDescription({ className, children, ...rest }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...rest}>{children}</p>;
}

export function CardContent({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 py-4", className)} {...rest}>{children}</div>;
}

export function CardFooter({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center px-5 py-3", className)} {...rest}>{children}</div>;
}

// ---------------------------------------------------------------------------
// Form-элементы
// ---------------------------------------------------------------------------

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: React.ReactNode;
  error?: string | null;
  leading?: React.ReactNode;
}

export function Input({ label, hint, error, leading, className, ...rest }: InputProps) {
  const id = useId();
  return (
    <div className="space-y-1">
      {label ? (
        <label htmlFor={id} className="text-sm font-medium">{label}</label>
      ) : null}
      <div className="relative">
        {leading ? (
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">
            {leading}
          </span>
        ) : null}
        <input
          id={id}
          className={cn(
            "flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm transition-colors",
            "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            leading ? "pl-9" : "",
            error ? "border-red-500" : "",
            className,
          )}
          {...rest}
        />
      </div>
      {hint && !error ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {error ? <p className="text-xs text-red-600 dark:text-red-400">{error}</p> : null}
    </div>
  );
}

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  hint?: React.ReactNode;
  error?: string | null;
}

export function Textarea({ label, hint, error, className, ...rest }: TextareaProps) {
  return (
    <div className="space-y-1">
      {label ? <span className="text-sm font-medium">{label}</span> : null}
      <textarea
        className={cn(
          "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors",
          "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          error ? "border-red-500" : "",
          className,
        )}
        {...rest}
      />
      {hint && !error ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {error ? <p className="text-xs text-red-600 dark:text-red-400">{error}</p> : null}
    </div>
  );
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  hint?: React.ReactNode;
  error?: string | null;
  children: React.ReactNode;
}

export function Select({ label, hint, error, className, children, ...rest }: SelectProps) {
  return (
    <div className="space-y-1">
      {label ? <span className="text-sm font-medium">{label}</span> : null}
      <select
        className={cn(
          "flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          error ? "border-red-500" : "",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
      {hint && !error ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {error ? <p className="text-xs text-red-600 dark:text-red-400">{error}</p> : null}
    </div>
  );
}

export interface CheckboxProps {
  label?: React.ReactNode;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
}

export function Checkbox({ label, description, checked, onChange, disabled, className }: CheckboxProps) {
  return (
    <label className={cn("flex cursor-pointer items-start gap-2.5 select-none", disabled ? "opacity-50 cursor-not-allowed" : "", className)}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-border text-primary DEFAULT focus:ring-ring focus:ring-offset-0"
      />
      <span className="space-y-0.5">
        {label ? <span className="text-sm font-medium leading-tight">{label}</span> : null}
        {description ? <span className="block text-xs text-muted-foreground leading-snug">{description}</span> : null}
      </span>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Alert / Spinner / EmptyState
// ---------------------------------------------------------------------------

const alertStyles = {
  info: "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  error: "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300",
};

export type AlertVariant = keyof typeof alertStyles;

export function Alert({ variant = "info", icon, children, className }: {
  variant?: AlertVariant;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start gap-3 rounded-lg border p-3 text-sm", alertStyles[variant], className)}>
      {icon ? <span className="mt-0.5 shrink-0">{icon}</span> : null}
      <div className="flex-1">{children}</div>
    </div>
  );
}

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-sm text-muted-foreground", className)}>
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </span>
  );
}

export function EmptyState({ icon, title, description, action }: {
  icon: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-card px-8 py-12 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-secondary DEFAULT text-secondary-foreground">
        {icon}
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      {description ? <p className="mt-1 text-sm text-muted-foreground max-w-md">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------

export function Progress({ value, className, stripe }: { value: number; className?: string; stripe?: boolean }) {
  const v = Math.min(100, Math.max(0, value));
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-secondary DEFAULT", className)}>
      <div
        className={cn("h-2 rounded-full bg-primary DEFAULT transition-all duration-300", stripe ? "animate-pulse" : "")}
        style={{ width: `${v}%` }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dialog (модальное окно)
// ---------------------------------------------------------------------------

export function Dialog({ open, onClose, title, description, children, wide }: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        className={cn(
          "absolute left-1/2 top-1/2 max-h-[85vh] w-full -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-card DEFAULT shadow-2xl",
          wide ? "max-w-4xl" : "max-w-lg",
        )}
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-start justify-between gap-4 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-card-foreground">{title}</h2>
            {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent DEFAULT"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

export function Tabs({ tabs, active, onChange, className }: {
  tabs: Array<{ id: string; label: string; badge?: number | null }>;
  active: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("inline-flex rounded-md bg-secondary DEFAULT p-1 text-muted-foreground", className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-sm font-medium transition-colors",
            active === tab.id ? "bg-card DEFAULT text-foreground shadow-sm" : "hover:text-foreground",
          )}
        >
          {tab.label}
          {tab.badge ? (
            <span className="ml-1 rounded-full bg-[hsl(var(--primary)/0.14)] px-1.5 text-xs text-foreground">{tab.badge}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ToggleSwitch
// ---------------------------------------------------------------------------

export function ToggleSwitch({ checked, onChange, disabled, label, description }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
  description?: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className={cn("inline-flex cursor-pointer items-center gap-2", disabled ? "opacity-50" : "")}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
      />
      <span
        className={cn(
          "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
          checked ? "bg-primary DEFAULT" : "bg-secondary DEFAULT",
        )}
      >
        <span
          className={cn(
            "inline-block h-4 w-4 rounded-full bg-white transition-transform",
            checked ? "translate-x-4" : "translate-x-0.5",
          )}
        />
      </span>
      {label ? (
        <span className="text-sm font-medium">
          {label}
          {description ? <span className="ml-1 text-xs text-muted-foreground">({description})</span> : null}
        </span>
      ) : null}
    </label>
  );
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------

export function StatCard({ label, value, sub, icon, accent }: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: React.ReactNode;
  accent?: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {icon ? <span className={cn("text-muted-foreground", accent || "")}>{icon}</span> : null}
      </div>
      <p className="mt-2 text-2xl font-bold tracking-tight">{value}</p>
      {sub ? <p className="text-xs text-muted-foreground mt-1">{sub}</p> : null}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Slider (ползунок с подписями)
// ---------------------------------------------------------------------------

export function Slider({ label, value, min, max, step = 0.01, onChange, hint, disabled }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  hint?: React.ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="text-sm font-medium">{label}</label>
        <span className="font-mono text-xs text-foreground">{value.toFixed(2)}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[hsl(var(--primary))]"
      />
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>{min.toFixed(2)}</span>
        <span>{max.toFixed(2)}</span>
      </div>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      <span className="sr-only" aria-hidden="true">{pct}%</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Kbd
// ---------------------------------------------------------------------------

export function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-border bg-secondary DEFAULT px-1.5 py-0.5 font-mono text-[11px]">
      {children}
    </kbd>
  );
}