/** Тип-заглушка для тестов Pipeline (совпадает с backend-моделью PipelineInput). */
export interface PipelineInputBodyLike {
  id?: string;
  name: string;
  description?: string;
  enabled?: boolean;
  steps: Array<{ id: string; tool: string; input: unknown }>;
}