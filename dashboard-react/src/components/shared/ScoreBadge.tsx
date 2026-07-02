import type React from 'react'

interface Props {
  score: number | null
  size?: 'sm' | 'md' | 'lg'
}

function houseColor(s: number | null): string {
  if (s == null) return 'oklch(0.62 0.000 0)'
  if (s >= 80)   return 'oklch(0.52 0.155 152)'  // vert profond
  if (s >= 60)   return 'oklch(0.60 0.155 140)'  // vert clair
  if (s >= 40)   return 'oklch(0.68 0.155 70)'   // amber
  return                'oklch(0.56 0.195 27)'    // rouge
}

// viewBox 0 0 36 44
// Walls:   rect x=1 y=19 w=34 h=24  (y 19→43)
// Roof:    polygon 0,19 → 18,4 → 36,19
// Chimney: rect x=25 y=6 w=5 h=14  (drawn before roof so roof clips bottom)

const CRACKS = [
  // [path, minDmg, opacity]
  ['M 8,22 l 3,6 l -2,5',       0.36, 0.58],  // left crack — score < 65
  ['M 26,25 l -3,6 l 2,4',      0.60, 0.55],  // right crack — score < 40
  ['M 17,35 l 2,4 l -1,3',      0.60, 0.48],  // bottom-center — score < 40
  ['M 5,28 l 5,7',              0.80, 0.60],  // far-left diagonal — score < 20
  ['M 29,32 l -4,7 l 3,3',      0.80, 0.55],  // far-right — score < 20
] as const

export function ScoreBadge({ score, size = 'md' }: Props) {
  const s   = score == null ? null : Math.max(0, Math.min(100, Math.round(score)))
  const dmg = s == null ? 0.5 : (100 - s) / 100

  const pw = size === 'sm' ? 26 : size === 'lg' ? 46 : 36
  const ph = Math.round(pw * 44 / 36)
  const col = houseColor(s)

  const label =
    s == null ? 'Score inconnu' :
    s >= 80   ? 'Excellent deal' :
    s >= 60   ? 'Bon deal' :
    s >= 40   ? 'Deal passable' :
                'Deal faible'

  // Score font: smaller for 3 digits
  const fontSize = s != null && s >= 100 ? 11 : 14

  return (
    <svg
      viewBox="0 0 36 44"
      width={pw}
      height={ph}
      aria-label={s == null ? 'Score inconnu' : `Score ${s}/100 — ${label}`}
      role="img"
      style={{ display: 'block', flexShrink: 0 } as React.CSSProperties}
    >
      <title>{s == null ? 'Score non calculé' : `Score ${s}/100 — ${label}`}</title>

      {/* Chimney — drawn first so roof polygon overlaps the lower portion */}
      <rect x="25" y="6" width="5" height="14" fill={col} rx="0.5" />

      {/* Roof */}
      <polygon points="0,19 18,4 36,19" fill={col} />

      {/* Walls (3 sides — top closed by roof) */}
      <rect x="1" y="19" width="34" height="24" fill={col} opacity={0.82} />

      {/* Cracks — appear progressively as score drops */}
      {CRACKS.map(([d, minDmg, op], i) =>
        dmg > minDmg ? (
          <path
            key={i}
            d={d}
            stroke="white"
            strokeWidth="1"
            strokeLinecap="round"
            fill="none"
            opacity={op}
          />
        ) : null
      )}

      {/* Score — big, centered in wall area */}
      <text
        x="18"
        y="31"
        textAnchor="middle"
        dominantBaseline="central"
        fill="white"
        fontSize={fontSize}
        fontWeight="700"
        fontFamily="'JetBrains Mono', monospace"
        letterSpacing="-1"
        style={{ userSelect: 'none' } as React.CSSProperties}
      >
        {s ?? '?'}
      </text>
    </svg>
  )
}
