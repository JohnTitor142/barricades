import { defineConfig } from 'vite';

// En dev : `npm run dev` (port 5173) relaie /ws vers le serveur Python local.
export default defineConfig({
  server: {
    proxy: { '/ws': { target: 'ws://localhost:8000', ws: true } },
  },
  build: { chunkSizeWarningLimit: 2000 },
});
