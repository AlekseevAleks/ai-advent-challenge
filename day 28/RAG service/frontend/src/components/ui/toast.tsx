/** Система уведомлений (toast): успех, ошибка, предупреждение, информация. */

import { CheckCircle2, CircleAlert, Info, TriangleAlert } from "lucide-react";
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { cn, uid } from "../../lib/utils";

interface ToastItem {
  id: string;
  variant: "success" | "error" | "warning" | "info";
  title: string;
  description?: string;
}

interface ToastApi {
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  warning: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastApi>({
  success: () => {},
  error: () => {},
  warning: () => {},
  info: () => {},
  dismiss: () => {},
});

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

const styles = {
  success: { icon: <CheckCircle2 className="h-5 w-5 text-emerald-500 dark:text-emerald-400" />, cls: "border-emerald-500/30" },
  error: { icon: <CircleAlert className="h-5 w-5 text-red-500 dark:text-red-400" />, cls: "border-red-500/30" },
  warning: { icon: <TriangleAlert className="h-5 w-5 text-amber-500 dark:text-amber-400" />, cls: "border-amber-500/30" },
  info: { icon: <Info className="h-5 w-5 text-sky-500 dark:text-sky-400" />, cls: "border-sky-500/30" },
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef<Record<string, number>>({});

  function push(variant: ToastItem["variant"], title: string, description?: string) {
    const id = uid();
    setItems((prev) => [...prev.slice(-4), { id, variant, title, description }]);
    timers.current[id] = window.setTimeout(() => dismiss(id), variant === "error" ? 9000 : 5200);
  }

  function dismiss(id: string) {
    window.clearTimeout(timers.current[id]);
    delete timers.current[id];
    setItems((prev) => prev.filter((t) => t.id !== id));
  }

  const api: ToastApi = {
    success: (t, d) => push("success", t, d),
    error: (t, d) => push("error", t, d),
    warning: (t, d) => push("warning", t, d),
    info: (t, d) => push("info", t, d),
    dismiss,
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {items.map((item) => {
          const s = styles[item.variant];
          return (
            <div key={item.id} className={cn("pointer-events-auto rounded-lg border bg-card DEFAULT p-3 shadow-xl", s.cls)}>
              <div className="flex items-start gap-2.5">
                {s.icon}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium leading-tight">{item.title}</p>
                  {item.description ? <p className="mt-0.5 text-xs text-muted-foreground leading-snug">{item.description}</p> : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}