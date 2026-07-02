import { useState, useEffect, useRef } from 'react'
import {
  Mountain, Zap, Briefcase, FileText, Globe, AlertTriangle,
  Hammer, Layers, ChevronDown, ChevronRight, RotateCcw, Check,
  HelpCircle, TrendingUp, BarChart2, BookOpen, ClipboardList,
} from 'lucide-react'

// ── Scroll reveal hook ────────────────────────────────────────────────────────

function useReveal(threshold = 0.12) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisible(true); obs.disconnect() } },
      { threshold }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [threshold])
  return { ref, visible }
}

function Reveal({ children, delay = 0, className = '' }: {
  children: React.ReactNode; delay?: number; className?: string
}) {
  const { ref, visible } = useReveal()
  return (
    <div
      ref={ref}
      className={`il-reveal-wrap ${visible ? 'il-revealed' : ''} ${className}`}
      style={{ transitionDelay: visible ? `${delay}ms` : '0ms' }}
    >
      {children}
    </div>
  )
}

// ── Data ──────────────────────────────────────────────────────────────────────

const QUIZ = [
  {
    q: '"L\'immobilier monte toujours."',
    answer: false,
    ok:  'Dans les bonnes zones, c\'est le foncier qui s\'apprécie — pas le bâti. Une maison neuve en zone détendue peut perdre de la valeur en termes réels.',
    ko:  'Piège classique. Ce n\'est pas la maison qui monte, c\'est la rareté de l\'emplacement. Une zone peu tendue peut très bien stagner ou reculer.',
  },
  {
    q: 'Rénover une cuisine crée de la valeur immobilière.',
    answer: false,
    ok:  'La plupart des travaux défendent contre la dépréciation — ils ne créent pas de richesse. Exception : les marchés premium où l\'acheteur compare à du haut de gamme neuf.',
    ko:  'La rénovation fait surtout éviter la dépréciation. Elle ne crée de vraie valeur que dans les marchés où les acheteurs comparent à du neuf haut de gamme.',
  },
  {
    q: 'Un appartement vétuste en hypercentre peut valoir très cher.',
    answer: true,
    ok:  'Dans ce cas, vous payez presque uniquement le foncier — la rareté de l\'emplacement, pas la qualité des murs. C\'est la thèse bâti/foncier en action.',
    ko:  'Si, justement. Dans les zones très denses, même un bien dégradé se vend cher : vous payez la rareté de l\'emplacement, pas les murs.',
  },
  {
    q: 'Le terrain ne peut que prendre de la valeur avec le temps.',
    answer: false,
    ok:  'Le foncier peut aussi baisser : changement climatique, perte d\'attractivité, nouveaux terrains constructibles. Aucune garantie automatique.',
    ko:  'Attention à ce mythe. Une ville peut se désertifier, un PLU peut ouvrir de nouveaux terrains à la construction.',
  },
]

const FACTORS = [
  { icon: <Mountain size={16} />, label: 'Contrainte physique',  desc: 'Mer, montagne, forêt classée — on ne peut pas en créer un deuxième. La rareté est structurelle.' },
  { icon: <Zap size={16} />,      label: 'Infrastructures',      desc: 'TGV, métro, aéroport. La connexion se capitalise directement dans le prix foncier.' },
  { icon: <Briefcase size={16} />,label: 'Emploi local',         desc: 'Les entreprises attirent des ménages solvables. La demande suit l\'économie du territoire.' },
  { icon: <FileText size={16} />, label: 'Réglementation',       desc: 'PLU, sites classés — la rareté artificielle du droit à construire cristallise la valeur.' },
  { icon: <Globe size={16} />,    label: 'Attractivité mondiale', desc: 'Les zones à demande internationale bénéficient d\'un vivier d\'acheteurs élargi.' },
  { icon: <AlertTriangle size={16} />, label: 'Point de vigilance', desc: 'Dérèglement climatique, déclin démographique, ou nouveau PLU peuvent effondrer le foncier.', warn: true },
]

const STATS = [
  { val: '×8',    label: 'Le foncier a surperformé le bâti',        sub: 'États-Unis, 1975–2005 en termes réels', color: 'var(--green)' },
  { val: '80 %',  label: 'De la hausse immo post-WWII s\'explique par le foncier', sub: 'Étude sur 14 pays depuis 1870',  color: 'var(--accent)' },
  { val: '×37',   label: 'Valeur du foncier en France depuis 1978', sub: 'En euros courants',                     color: 'var(--green)' },
  { val: '48 %',  label: 'Du prix total représenté par le foncier', sub: 'France 2022 — contre 22 % en 1978',    color: 'var(--amber)' },
]

const CHECKLIST = [
  { q: 'Quelle part correspond au confort personnel ?',     hint: 'Vue, cuisine, exposition. Déterminant pour y vivre, pas pour le rendement financier.' },
  { q: 'Quelle est la facture d\'entretien à prévoir ?',   hint: 'Toiture, isolation, électricité. Estimez le coût et déduisez-le mentalement du prix affiché.' },
  { q: 'Quel rendement locatif net est réaliste ?',        hint: 'Loyers bruts moins charges, taxe foncière, vacance, frais de gestion. Soyez conservateur.' },
  { q: 'Quel est le pari sur la rareté de l\'emplacement ?', hint: 'Terrains constructibles à proximité ? PLU en révision ? Demande structurelle ou conjoncturelle ?' },
]

// ── Quiz ──────────────────────────────────────────────────────────────────────

function Quiz() {
  const [step, setStep]     = useState(0)
  const [chosen, setChosen] = useState<boolean | null>(null)
  const [scores, setScores] = useState<boolean[]>([])

  const current    = QUIZ[step]
  const isAnswered = chosen !== null
  const isCorrect  = chosen === current?.answer
  const isDone     = step >= QUIZ.length

  function answer(val: boolean) {
    if (isAnswered) return
    setChosen(val)
    setScores((s) => [...s, val === current.answer])
  }
  function next() { setStep((s) => s + 1); setChosen(null) }
  function reset() { setStep(0); setChosen(null); setScores([]) }

  const finalScore = scores.filter(Boolean).length

  if (isDone) {
    const msg = finalScore === 4 ? 'Maîtrise totale.'
      : finalScore >= 3 ? 'Très bon niveau.'
      : finalScore >= 2 ? 'Des lacunes à combler.'
      : 'Relisez la théorie avant d\'acheter.'
    return (
      <div className="il-score-screen">
        <div className="il-score-ring">
          <span className="il-score-num">{finalScore}</span>
          <span className="il-score-denom">/4</span>
        </div>
        <div className="il-score-msg">{msg}</div>
        <div className="il-score-dots">
          {scores.map((ok, i) => <span key={i} className={`il-score-dot ${ok ? 'ok' : 'ko'}`} />)}
        </div>
        <button className="il-restart-btn" onClick={reset}>
          <RotateCcw size={13} /> Recommencer
        </button>
      </div>
    )
  }

  return (
    <div className="il-quiz">
      <div className="il-progress-wrap">
        <div className="il-progress-bar">
          <div className="il-progress-fill" style={{ width: `${(step / QUIZ.length) * 100}%` }} />
        </div>
        <span className="il-progress-label">{step + 1} / {QUIZ.length}</span>
      </div>
      <div className={`il-question-card${isAnswered ? (isCorrect ? ' correct' : ' wrong') : ''}`}>
        <div className="il-question-num">Question {step + 1}</div>
        <div className="il-question-text">{current.q}</div>
      </div>
      {!isAnswered ? (
        <div className="il-choices">
          <button className="il-choice il-vrai" onClick={() => answer(true)}>Vrai</button>
          <button className="il-choice il-faux" onClick={() => answer(false)}>Faux</button>
        </div>
      ) : (
        <div className={`il-reveal ${isCorrect ? 'il-reveal-ok' : 'il-reveal-ko'}`}>
          <div className="il-reveal-badge">{isCorrect ? 'Correct' : 'Incorrect'}</div>
          <p className="il-reveal-text">{isCorrect ? current.ok : current.ko}</p>
          <button className="il-next-btn" onClick={next}>
            {step < QUIZ.length - 1
              ? <><ChevronRight size={15} /> Question suivante</>
              : <><Check size={15} /> Voir les résultats</>}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Concept panels ────────────────────────────────────────────────────────────

function ConceptSplit() {
  const [active, setActive] = useState<'bati' | 'foncier' | null>(null)
  return (
    <div className="il-split-wrap">
      {(['bati', 'foncier'] as const).map((side) => {
        const isBati  = side === 'bati'
        const isActive = active === side
        const isDim    = active !== null && active !== side
        return (
          <div key={side}
            className={`il-split-panel il-${side}${isActive ? ' il-panel-active' : ''}${isDim ? ' il-panel-dim' : ''}`}
            onClick={() => setActive(isActive ? null : side)}
          >
            <div className="il-panel-icon-wrap">
              {isBati ? <Hammer size={18} /> : <Layers size={18} />}
            </div>
            <div className="il-panel-title">{isBati ? 'Bâti' : 'Foncier'}</div>
            <div className={`il-panel-verdict ${isBati ? 'neg' : 'pos'}`}>
              {isBati ? 'Se déprécie' : 'Peut s\'apprécier'}
            </div>
            {isActive && (
              <ul className="il-panel-list">
                {isBati ? <>
                  <li>S'use, se démode, se détériore avec le temps</li>
                  <li>Rénover = défense contre la baisse, pas création de valeur</li>
                  <li>Reproductible — on peut en construire un pareil à côté</li>
                  <li>Sa valeur converge vers le coût de reconstruction</li>
                </> : <>
                  <li>Ne prend pas l'humidité, pas de toiture à refaire</li>
                  <li>Irréproductible dans les zones physiquement contraintes</li>
                  <li>Sa valeur dépend de la rareté et de la demande</li>
                  <li>Vraie source de valorisation à long terme</li>
                </>}
              </ul>
            )}
            {!isActive && <div className="il-panel-cta">Cliquer pour développer</div>}
          </div>
        )
      })}
    </div>
  )
}

// ── Checklist ─────────────────────────────────────────────────────────────────

function Checklist() {
  const [checked, setChecked]   = useState(Array(CHECKLIST.length).fill(false))
  const [openHint, setOpenHint] = useState<number | null>(null)
  const done = checked.filter(Boolean).length
  return (
    <div className="il-cl-wrap">
      {CHECKLIST.map((item, i) => (
        <div key={i} className={`il-cl-item${checked[i] ? ' il-cl-done' : ''}`}>
          <button className={`il-cl-check${checked[i] ? ' checked' : ''}`}
            onClick={() => { const n = [...checked]; n[i] = !n[i]; setChecked(n) }}>
            {checked[i] && <Check size={11} strokeWidth={3} />}
          </button>
          <div className="il-cl-body">
            <div className="il-cl-q">{item.q}</div>
            <div className={`il-cl-hint-text${openHint === i ? ' open' : ''}`}>{item.hint}</div>
          </div>
          <button className={`il-cl-hint-btn${openHint === i ? ' active' : ''}`}
            onClick={() => setOpenHint(openHint === i ? null : i)}>
            <HelpCircle size={14} />
          </button>
        </div>
      ))}
      {done === CHECKLIST.length && (
        <div className="il-cl-complete">Analyse complète — vous êtes prêt à faire une offre éclairée.</div>
      )}
    </div>
  )
}

// ── FAQ ───────────────────────────────────────────────────────────────────────

function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`il-faq-item${open ? ' open' : ''}`}>
      <button className="il-faq-btn" onClick={() => setOpen((o) => !o)}>
        <span>{q}</span>
        <ChevronDown size={15} className={`il-faq-chevron${open ? ' rotated' : ''}`} />
      </button>
      {open && <div className="il-faq-body">{children}</div>}
    </div>
  )
}

// ── Section block ─────────────────────────────────────────────────────────────

function Block({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="il-block">
      <div className="il-block-header">
        <span className="il-block-icon">{icon}</span>
        <span className="il-block-title">{title}</span>
      </div>
      <div className="il-block-body">{children}</div>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function ApprendreTab() {
  return (
    <div className="overflow-auto h-full il-scroll-root">
      <div className="il-page">

        {/* Hero — pas de reveal, visible immédiatement */}
        <div className="il-hero">
          <div className="il-hero-accent" />
          <div className="il-hero-label">Théorie fondamentale</div>
          <h1 className="il-hero-title">Vous n'achetez<br />pas des murs.</h1>
          <p className="il-hero-sub">
            La décomposition bâti / foncier — la clé pour évaluer tout bien immobilier
            indépendamment du marché ou de la zone géographique.
          </p>
        </div>

        {/* Concept */}
        <Reveal>
          <Block icon={<TrendingUp size={15} />} title="Le concept">
            <p className="il-prose">
              Tout bien immobilier est en réalité <strong>deux actifs superposés</strong> qui ne se comportent pas de la même façon dans le temps.
              L'analogie : une glace posée sur un lingot d'or. La glace s'use et fond (le bâti). Le lingot reste et peut prendre de la valeur (le foncier).
            </p>
            <ConceptSplit />
          </Block>
        </Reveal>

        {/* Stats */}
        <Reveal delay={60}>
          <Block icon={<BarChart2 size={15} />} title="Ce que disent les données">
            <div className="il-stats-grid">
              {STATS.map((s, i) => (
                <Reveal key={s.label} delay={i * 80}>
                  <div className="il-stat-card">
                    <div className="il-stat-accent" style={{ background: s.color }} />
                    <div className="il-stat-val" style={{ color: s.color }}>{s.val}</div>
                    <div className="il-stat-label">{s.label}</div>
                    <div className="il-stat-sub">{s.sub}</div>
                  </div>
                </Reveal>
              ))}
            </div>
            <p className="il-source">Sources : Davis & Palumbo (2008) · Knoll, Schularick & Steger (2017) · INSEE / Banque de France</p>
          </Block>
        </Reveal>

        {/* Factors */}
        <Reveal delay={40}>
          <Block icon={<Mountain size={15} />} title="Ce qui fait monter un foncier">
            <div className="il-factors-list">
              {FACTORS.map((f, i) => (
                <Reveal key={f.label} delay={i * 60}>
                  <div className={`il-factor-row${f.warn ? ' warn' : ''}`}>
                    <div className="il-factor-icon">{f.icon}</div>
                    <div>
                      <div className="il-factor-label">{f.label}</div>
                      <div className="il-factor-desc">{f.desc}</div>
                    </div>
                  </div>
                </Reveal>
              ))}
            </div>
          </Block>
        </Reveal>

        {/* Quiz */}
        <Reveal delay={40}>
          <Block icon={<HelpCircle size={15} />} title="Vrai ou faux ?">
            <p className="il-prose" style={{ marginBottom: 20 }}>Testez votre compréhension de la théorie.</p>
            <Quiz />
          </Block>
        </Reveal>

        {/* Checklist */}
        <Reveal delay={40}>
          <Block icon={<ClipboardList size={15} />} title="Avant de faire une offre">
            <p className="il-prose" style={{ marginBottom: 20 }}>
              Décomposez mentalement le prix en quatre questions. Cochez au fur et à mesure de votre analyse.
            </p>
            <Checklist />
          </Block>
        </Reveal>

        {/* FAQ */}
        <Reveal delay={40}>
          <Block icon={<BookOpen size={15} />} title="Questions fréquentes">
            <div className="il-faq-list">
              <Faq q="Mes travaux créent-ils vraiment de la valeur ?">
                <p>Rarement autant qu'on le croit. La plupart <strong>défendent contre la dépréciation</strong> — refaire une toiture permet de rester vendable au prix du marché, ce n'est pas de la création de richesse. Exception : les marchés premium où l'acheteur compare à du haut de gamme neuf.</p>
              </Faq>
              <Faq q="Maison neuve en zone peu tendue — bon investissement ?">
                <p>Attention. Le bâti représente 90 %+ du prix, le foncier à peine 10 %. Votre voisin peut construire la même maison au même prix. Sans choc externe (grande entreprise, infrastructure majeure), le potentiel de valorisation foncière est faible.</p>
              </Faq>
              <Faq q="Comment estimer la part foncière d'un bien ?">
                <p>Méthode : coût de reconstruction neuf (1 800 – 3 000 €/m² selon les finitions) × surface, décoté selon la vétusté = valeur bâti. Tout ce qui dépasse dans le prix de vente = foncier implicite. Dans les zones ultra-tendues sans terrain nu disponible, cette part peut dépasser <strong>70 % du prix total</strong>.</p>
              </Faq>
            </div>
          </Block>
        </Reveal>

      </div>
    </div>
  )
}
