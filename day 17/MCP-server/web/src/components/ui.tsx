// Переиспользуемые UI-компоненты: Badge, Button, Card, Spinner, EmptyState,
// ErrorState, Toggle, Tabs, Modal, ConfirmDialog, CopyButton, JsonView, Stat,
// Toast (глобальный провайдер + функция toast()).
import { useEffect, useState } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { IconCheck, IconClose, IconCopy, IconSearch } from './icons.js';

// ---------------------------------------------------------------- Toast

export type ToastType = 'success' | 'error' | 'info';

export interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
}

type ToastListener = (item: ToastItem) => void;

const toastListeners: ToastListener[] = [];
let toastSeq = 0;

const TOAST_DURATION = 4000;

/** Глобальная функция: работает отовсюду (в т.ч. из api/client.ts). */
export function toast(message: string, type: ToastType = 'info'): void {
  const item: ToastItem = { id: ++toastSeq, message, type };
  for (const listener of toastListeners) listener(item);
}

export function ToastProvider({ children }: { children: ReactNode }): ReactNode {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const listener: ToastListener = (item) => {
      setItems((prev) => [...prev, item]);
      window.setTimeout(() => {
        setItems((prev) => prev.filter((i) => i.id !== item.id));
      }, TOAST_DURATION);
    };
    toastListeners.push(listener);
    return () => {
      const index = toastListeners.indexOf(listener);
      if (index >= 0) toastListeners.splice(index, 1);
    };
  }, []);

  return (
    <>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast toast-${item.type}`}>
            <span className="toast-icon">
              {item.type === 'success' ? <IconCheck size={14} /> : item.type === 'error' ? <IconClose size={14} /> : null}
            </span>
            <span className="toast-msg">{item.message}</span>
            <button
              type="button"
              className="btn-icon toast-close"
              aria-label="Dismiss"
              onClick={() => setItems((prev) => prev.filter((i) => i.id !== item.id))}
            >
              <IconClose size={14} />
            </button>
          </div>
        ))}
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Badge

export type BadgeKind = 'ok' | 'error' | 'warn' | 'accent' | 'muted' | 'neutral';

export function Badge({ kind = 'neutral', children, title }: { kind?: BadgeKind; children: ReactNode; title?: string }): ReactNode {
  return (
    <span className={`badge badge-${kind}`} title={title}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- Button

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  loading?: boolean;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps): ReactNode {
  return (
    <button
      type="button"
      className={`btn btn-${variant}${size === 'sm' ? ' btn-sm' : ''}${className ? ` ${className}` : ''}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="spinner spinner-sm" /> : null}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- Spinner

export function Spinner({ text }: { text?: string }): ReactNode {
  return (
    <div className="spinner-wrap">
      <span className="spinner" />
      {text ? <span className="spinner-text">{text}</span> : null}
    </div>
  );
}

// ---------------------------------------------------------------- Card

export function Card({
  title,
  actions,
  children,
  className,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}): ReactNode {
  return (
    <div className={`card${className ? ` ${className}` : ''}`}>
      {title || actions ? (
        <div className="card-header">
          {title ? <div className="card-title">{title}</div> : null}
          {actions ? <div className="card-actions">{actions}</div> : null}
        </div>
      ) : null}
      <div className="card-body">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------- Empty / Error

export function EmptyState({ title, description }: { title: string; description?: string }): ReactNode {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">∅</div>
      <div className="empty-state-title">{title}</div>
      {description ? <div className="empty-state-desc">{description}</div> : null}
    </div>
  );
}

export function ErrorState({
  title = 'Failed to load',
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}): ReactNode {
  return (
    <div className="error-state">
      <div className="error-state-title">{title}</div>
      {message ? <div className="error-state-desc">{message}</div> : null}
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- Toggle

export function Toggle({
  checked,
  onChange,
  disabled = false,
  pending = false,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  pending?: boolean;
  label?: string;
}): ReactNode {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled || pending}
      className={`toggle${checked ? ' toggle-on' : ''}`}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-track">
        <span className="toggle-thumb" />
      </span>
      {pending ? <span className="spinner spinner-xs" /> : null}
    </button>
  );
}

// ---------------------------------------------------------------- Tabs

export interface TabItem<T extends string> {
  value: T;
  label: string;
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: ReadonlyArray<TabItem<T>>;
  value: T;
  onChange: (value: T) => void;
}): ReactNode {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          aria-selected={tab.value === value}
          className={`tab${tab.value === value ? ' tab-active' : ''}`}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- Modal

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide = false,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}): ReactNode {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === 'string' ? title : undefined}
      onClick={onClose}
    >
      <div
        className={`modal${wide ? ' modal-wide' : ''}`}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <div className="modal-header">
          <div className="modal-title">{title}</div>
          <button type="button" className="btn-icon" aria-label="Close" onClick={onClose}>
            <IconClose />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-footer">{footer}</div> : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- ConfirmDialog

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  danger = false,
  pending = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}): ReactNode {
  if (!open) return null;
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={pending}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="confirm-message">{message}</p>
    </Modal>
  );
}

// ---------------------------------------------------------------- CopyButton

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(textarea);
      return ok;
    } catch {
      return false;
    }
  }
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }): ReactNode {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    const ok = await copyText(text);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast('Copy failed', 'error');
    }
  };

  return (
    <button type="button" className="btn btn-ghost btn-sm" onClick={onCopy} aria-label={label}>
      {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
      {copied ? 'Copied' : label}
    </button>
  );
}

// ---------------------------------------------------------------- JsonView / CodeBlock

const REDACTED = '[REDACTED]';

/** Подсветить вхождения [REDACTED] в тексте. */
export function renderRedacted(text: string): ReactNode {
  const parts = text.split(REDACTED);
  if (parts.length === 1) return text;
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {i < parts.length - 1 ? <span className="log-redacted">{REDACTED}</span> : null}
        </span>
      ))}
    </>
  );
}

export function CodeBlock({ text }: { text: string }): ReactNode {
  return <pre className="code-block">{renderRedacted(text)}</pre>;
}

export function JsonView({ data }: { data: unknown }): ReactNode {
  let text: string;
  try {
    text = JSON.stringify(data, null, 2);
  } catch {
    text = String(data);
  }
  return <CodeBlock text={text} />;
}

// ---------------------------------------------------------------- Stat

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }): ReactNode {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint ? <div className="stat-hint">{hint}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------- Field

export function Field({
  label,
  hint,
  required = false,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}): ReactNode {
  return (
    <div className="field">
      <span className="field-label">
        {label}
        {required ? <span className="field-required">*</span> : null}
      </span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}

// ---------------------------------------------------------------- SearchInput (мелочь для фильтров)

export function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}): ReactNode {
  return (
    <div className="search-input">
      <IconSearch size={14} />
      <input type="text" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}