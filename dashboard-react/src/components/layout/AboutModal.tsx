import { useEffect } from 'react'
import { X } from 'lucide-react'
import { useStore } from '@/store/useStore'

/** Sources, avertissement et mentions légales (LCEN art. 6). */
export function AboutModal() {
  const open    = useStore((s) => s.aboutOpen)
  const setOpen = useStore((s) => s.setAboutOpen)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  if (!open) return null
  return (
    <div className="login-overlay" role="dialog" aria-modal="true" aria-labelledby="about-title" onClick={() => setOpen(false)}>
      <div className="login-card about-card" onClick={(e) => e.stopPropagation()}>
        <button className="login-close" onClick={() => setOpen(false)} aria-label="Fermer"><X size={16} /></button>
        <h2 className="about-title" id="about-title">À propos &amp; mentions légales</h2>

        <h3>Sources des données</h3>
        <p>
          Les statistiques de marché, la carte des ventes et l'estimateur reposent sur
          les « Demandes de valeurs foncières » (DVF) publiées par la DGFiP sur
          data.gouv.fr, sous Licence Ouverte Etalab 2.0. Fonds de carte © OpenStreetMap,
          © CARTO, © OpenSnowMap.
        </p>

        <h3>Avertissement</h3>
        <p>
          Les estimations sont produites par un modèle statistique et restent
          indicatives. Elles ne constituent ni une expertise immobilière, ni un conseil
          en investissement. Vérifie toujours avec un professionnel avant toute décision.
        </p>

        <h3>Données personnelles</h3>
        <p>
          Le site n'utilise ni cookie publicitaire ni outil de mesure d'audience. Les
          préférences d'affichage sont stockées dans ton navigateur uniquement. Pour
          les comptes invités, l'authentification est gérée par Supabase.
        </p>

        <h3>Éditeur et hébergeur</h3>
        <p>
          Site personnel édité par un particulier, à titre non professionnel ; ses
          coordonnées ont été communiquées à l'hébergeur (art. 6-III-2 de la loi
          n° 2004-575 du 21 juin 2004).
          Hébergement : Vercel Inc., 440 N Barranca Ave #4133, Covina, CA 91723, États-Unis.
        </p>
      </div>
    </div>
  )
}
