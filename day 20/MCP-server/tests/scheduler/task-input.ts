export type TaskInputLeft = {
  id?: string;
  name: string;
  description?: string;
  enabled?: boolean;
  schedule:
    | { type: 'once'; executeAt: string; timezone?: string }
    | { type: 'cron'; cron: string; timezone: string };
  action: { type: 'provider_tool'; provider: string; tool: string; input?: unknown };
  aggregation?: { enabled?: boolean; strategy?: string; window?: string };
};