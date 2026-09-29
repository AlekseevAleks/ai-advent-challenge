import { z } from 'zod';

export const summarizeInputSchema = z
  .object({
    data: z.unknown(),
    instruction: z.string().max(2000).optional(),
  })
  .passthrough();

export const outputFileSchema = z
  .object({
    filename: z.string().min(1).max(500),
    content: z.string().max(1_000_000),
  })
  .passthrough();