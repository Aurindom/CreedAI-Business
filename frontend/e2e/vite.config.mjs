import config from '../vite.config.js'
import { fileURLToPath } from 'node:url'
// Synthetic provider credentials are used only by this explicit QA build.
process.env.VITE_SUPABASE_URL = 'https://fixture.supabase.co'
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = 'fixture-public-key'
export default {
  ...config,
  root: fileURLToPath(new URL('../', import.meta.url)),
  server: { ...config.server, port: 5175, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8001' } },
}
