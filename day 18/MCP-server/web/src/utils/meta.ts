// Бейджи/метки, общие для статусов (health, success, direction).
import type { BadgeKind } from '../components/ui.js';

export function healthKind(status: 'ok' | 'error' | 'unknown'): BadgeKind {
  if (status === 'ok') return 'ok';
  if (status === 'error') return 'error';
  return 'muted';
}

/** Статус-код HTTP → цвет бейджа. */
export function statusKind(status: number): BadgeKind {
  if (status >= 200 && status < 300) return 'ok';
  if (status >= 400) return 'error';
  return 'warn';
}

export function directionLabel(direction: 'mcp' | 'test' | 'health'): string {
  switch (direction) {
    case 'mcp':
      return 'MCP → Provider';
    case 'test':
      return 'TEST';
    case 'health':
      return 'HEALTH';
  }
}

export function directionKind(direction: 'mcp' | 'test' | 'health'): BadgeKind {
  switch (direction) {
    case 'mcp':
      return 'accent';
    case 'test':
      return 'warn';
    case 'health':
      return 'muted';
  }
}