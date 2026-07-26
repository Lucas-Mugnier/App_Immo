// Vercel serverless function (Node runtime).
// Verifies the caller is the admin, then triggers the "Refresh listings"
// GitHub Actions workflow via workflow_dispatch. Secrets (GITHUB_TOKEN,
// ADMIN_EMAIL) live only in Vercel env vars — never sent to the client.
import { createClient } from '@supabase/supabase-js'

const GITHUB_OWNER = 'Lucas-Mugnier'
const GITHUB_REPO = 'immo-radar'
const WORKFLOW_FILE = 'scrape.yml'

export default async function handler(req: any, res: any) {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'Method not allowed' })
    return
  }

  const authHeader = req.headers.authorization as string | undefined
  const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null
  if (!token) {
    res.status(401).json({ error: 'Missing token' })
    return
  }

  const supabaseUrl = process.env.VITE_SUPABASE_URL
  const supabaseAnonKey = process.env.VITE_SUPABASE_ANON_KEY
  const adminEmail = process.env.ADMIN_EMAIL
  const githubToken = process.env.GITHUB_TOKEN

  if (!supabaseUrl || !supabaseAnonKey || !adminEmail || !githubToken) {
    res.status(500).json({ error: 'Server misconfigured' })
    return
  }

  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  const { data, error } = await supabase.auth.getUser(token)
  if (error || data.user?.email !== adminEmail) {
    res.status(403).json({ error: 'Forbidden' })
    return
  }

  const ghRes = await fetch(
    `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${githubToken}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify({ ref: 'main' }),
    }
  )

  if (!ghRes.ok) {
    const detail = await ghRes.text()
    res.status(502).json({ error: 'GitHub dispatch failed', detail })
    return
  }

  res.status(200).json({ ok: true })
}
