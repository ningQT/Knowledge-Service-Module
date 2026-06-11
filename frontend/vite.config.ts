import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '^/api/': {
        target: 'http://localhost:8900',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('reactflow') || id.includes('d3-force') || id.includes('dagre')) return 'vendor-graph'
          if (id.includes('react-markdown') || id.includes('remark-gfm') || id.includes('rehype-highlight') || id.includes('highlight.js')) return 'vendor-markdown'
          if (id.includes('radix-ui') || id.includes('lucide-react')) return 'vendor-ui'
          if (id.includes('react') || id.includes('react-dom') || id.includes('react-router-dom')) return 'vendor-react'
          if (id.includes('i18next') || id.includes('ky') || id.includes('zustand')) return 'vendor-app'
          return 'vendor'
        },
      },
    },
  },
})
