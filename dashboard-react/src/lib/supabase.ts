import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

export const supabase =
  supabaseUrl && supabaseAnonKey ? createClient(supabaseUrl, supabaseAnonKey) : null

export const ADMIN_EMAIL = import.meta.env.VITE_ADMIN_EMAIL as string | undefined

export async function signUpWithEmail(email: string, password: string) {
  if (!supabase) return { error: 'Supabase non configuré' }
  const { error } = await supabase.auth.signUp({ email, password })
  return { error: error?.message ?? null }
}

export async function signInWithEmail(email: string, password: string) {
  if (!supabase) return { error: 'Supabase non configuré' }
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  return { error: error?.message ?? null }
}

export async function signInWithGoogle() {
  if (!supabase) return { error: 'Supabase non configuré' }
  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: window.location.origin },
  })
  return { error: error?.message ?? null }
}

export async function signOut() {
  if (!supabase) return
  await supabase.auth.signOut()
}

export type CorrectionField = 'neighbourhood' | 'surface' | 'carrez' | 'prix' | 'autre'

export interface Correction {
  id: string
  listing_id: string
  listing_url: string | null
  listing_title: string | null
  field: string
  current_value: string | null
  suggested_value: string
  comment: string | null
  reporter_name: string | null
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
  reviewed_at: string | null
}

export const FIELD_LABELS: Record<string, string> = {
  neighbourhood: 'Localisation / Quartier',
  surface:       'Surface (m²)',
  carrez:        'Surface Carrez (m²)',
  prix:          'Prix affiché',
  autre:         'Autre information',
}

export async function fetchCorrections(listing_id: string): Promise<Correction[]> {
  if (!supabase) return []
  const { data, error } = await supabase
    .from('corrections')
    .select('*')
    .eq('listing_id', listing_id)
    .in('status', ['pending', 'approved'])
    .order('created_at', { ascending: false })
  if (error) { console.error('[supabase]', error); return [] }
  return (data as Correction[]) ?? []
}

export async function submitCorrection(
  c: Omit<Correction, 'id' | 'created_at' | 'reviewed_at' | 'status'>
): Promise<boolean> {
  if (!supabase) return false
  const { error } = await supabase.from('corrections').insert([c])
  if (error) { console.error('[supabase]', error); return false }
  return true
}

export async function fetchAllCorrections(): Promise<Correction[]> {
  if (!supabase) return []
  const { data, error } = await supabase
    .from('corrections')
    .select('*')
    .order('status', { ascending: true })
    .order('created_at', { ascending: false })
  if (error) { console.error('[supabase]', error); return [] }
  return (data as Correction[]) ?? []
}

export async function updateCorrectionStatus(
  id: string,
  status: 'approved' | 'rejected'
): Promise<boolean> {
  if (!supabase) return false
  const { error } = await supabase
    .from('corrections')
    .update({ status, reviewed_at: new Date().toISOString() })
    .eq('id', id)
  if (error) { console.error('[supabase]', error); return false }
  return true
}
