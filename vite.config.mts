import { defineConfig } from 'vite';
export default defineConfig({
  base: '/static/build/',
  build: {
    outDir: 'static/build',
    emptyOutDir: true,
    manifest: true,
    rollupOptions: { input: 'frontend/carousels.ts' }
  }
});
