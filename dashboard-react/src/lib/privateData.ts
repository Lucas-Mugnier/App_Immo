import type { Listing, Maison } from '@/types'
import { supabase } from '@/lib/supabase'
import { setPrivateData } from '@/lib/data'

/** Bucket Supabase Storage PRIVÉ — lecture réservée aux emails de public.allowed_users (RLS). */
export const PRIVATE_BUCKET = 'private-data'

export type PrivateDataStatus = 'anon' | 'loading' | 'ready' | 'denied' | 'error'

async function download<T>(path: string): Promise<T> {
  if (!supabase) throw new Error('Supabase non configuré')
  const { data, error } = await supabase.storage.from(PRIVATE_BUCKET).download(path)
  if (error || !data) {
    const status = (error as { statusCode?: string | number } | null)?.statusCode
    const err = new Error(error?.message ?? 'download failed') as Error & { denied?: boolean }
    // Storage renvoie 400/403/404 quand la RLS refuse l'accès (l'objet est « introuvable » pour ce compte)
    err.denied = status == null || ['400', '401', '403', '404', 400, 401, 403, 404].includes(status as never)
    throw err
  }
  return JSON.parse(await data.text()) as T
}

/** Télécharge les annonces si le compte connecté est autorisé. */
export async function loadPrivateData(): Promise<PrivateDataStatus> {
  try {
    const [listings, maisons] = await Promise.all([
      download<Listing[]>('listings.json'),
      download<Maison[]>('maisons.json'),
    ])
    setPrivateData(listings, maisons)
    return 'ready'
  } catch (e) {
    console.warn('[private-data]', e)
    return (e as { denied?: boolean }).denied ? 'denied' : 'error'
  }
}
