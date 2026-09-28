import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend REST API и MCP endpoint проксируются на 127.0.0.1:3000.
// В production Web UI собирается в web/dist и раздаётся самим сервером.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true,
      },
      '/mcp': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true,
        // Streamable HTTP transport поверх обычного HTTP(S); ws не нужен,
        // но оставляем для совместимости с клиентами, использующими websocket-транспорт.
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
});