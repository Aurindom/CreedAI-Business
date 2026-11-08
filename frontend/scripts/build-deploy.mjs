// Vite embeds only these public auth settings. Internal service secrets stay in
// the BuildKit secret mount and are never exported to npm or image layers.
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

export function publicAuth(source) {
  const values = {}
  for (const line of source.split(/\r?\n/)) {
    const match = line.match(/^\s*(SUPABASE_URL|SUPABASE_PUBLISHABLE_KEY)\s*=\s*(.*?)\s*$/)
    if (match) values[match[1]] = match[2].replace(/^(['"])(.*)\1$/, '$2')
  }
  const url = new URL(values.SUPABASE_URL)
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw Error('Invalid public Supabase URL')
  const key = values.SUPABASE_PUBLISHABLE_KEY || ''
  let anon = false
  try { anon = JSON.parse(Buffer.from(key.split('.')[1], 'base64url').toString()).role === 'anon' } catch {}
  if (!(key.startsWith('sb_publishable_') || anon) || key.includes('REPLACE_')) throw Error('Use a Supabase publishable or anon key')
  return { VITE_SUPABASE_URL: url.origin, VITE_SUPABASE_PUBLISHABLE_KEY: key }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const auth = publicAuth(readFileSync(process.argv[2], 'utf8'))
    const result = spawnSync('npm', ['run', 'build'], { stdio: 'inherit', env: { ...process.env, ...auth } })
    process.exit(result.status ?? 1)
  } catch {
    console.error('Frontend auth build failed: supply a valid SUPABASE_URL and publishable/anon key in app.env.')
    process.exit(1)
  }
}
