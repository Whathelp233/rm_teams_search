export function canonicalPoint(x, y, side) {
  return side === '蓝' ? [28 - x, 15 - y] : [x, y]
}

// Official coordinates use +Y toward the red helipad, while SVG/image pixels
// increase downward. The competition-map image therefore needs a vertical flip.
export function officialToMap(x, y) {
  return [x, 15 - y]
}

// A dual-team timeline must rotate the entire world, never one side at a time.
// This keeps opponents on opposite sides in the selected team's perspective.
export function teamPerspectivePoint(x, y, selectedSide) {
  return selectedSide === '蓝' ? [28 - x, y] : officialToMap(x, y)
}

export function aggregateHeatCells(cells, project, mergeSides = false) {
  const result = new Map()
  for (const cell of cells) {
    const [x, y] = project(cell)
    const side = mergeSides ? '己' : cell[0]
    const key = `${side}:${x}:${y}`
    const previous = result.get(key)
    if (previous) previous.samples += cell[5]
    else result.set(key, { side, x, y, samples: cell[5] })
  }
  return [...result.values()]
}

export function densityOpacity(samples, maximum) {
  const normalized = Math.log1p(samples) / Math.log1p(Math.max(1, maximum))
  return Math.max(.025, Math.min(.88, normalized * normalized * .88))
}

const tacticalWeights = {
  firepower: .22,
  objective: .18,
  spatial: .15,
  defense: .18,
  resource: .12,
  adaptability: .15,
}

function finite(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

export function teamStrength(team) {
  const tactical = Object.entries(tacticalWeights).reduce(
    (total, [key, weight]) => total + finite(team?.scores?.[key]) * weight, 0,
  )
  return .7 * tactical + .3 * finite(team?.summary?.win_rate ?? team?.win_rate)
}

export function strengthGrade(score) {
  const value = finite(score)
  if (value >= 80) return 'S'
  if (value >= 70) return 'A'
  if (value >= 60) return 'B'
  if (value >= 50) return 'C'
  if (value >= 40) return 'D'
  return 'E'
}

export function matchupEstimate(primary, opponent, headToHead = []) {
  const primaryStrength = teamStrength(primary)
  const opponentStrength = teamStrength(opponent)
  // A broad logistic scale deliberately avoids extreme claims from a small,
  // schedule-dependent regional sample.
  let probability = 1 / (1 + Math.exp(-(primaryStrength - opponentStrength) / 20))
  const h2hGames = headToHead.length
  const h2hWins = headToHead.filter(match => Boolean(match.won)).length
  if (h2hGames) {
    const smoothedRate = (h2hWins + 1) / (h2hGames + 2)
    const weight = Math.min(.3, h2hGames * .06)
    probability = probability * (1 - weight) + smoothedRate * weight
  }
  const primaryPct = Math.round(probability * 1000) / 10
  const opponentPct = Math.round((100 - primaryPct) * 10) / 10
  const minimumSample = Math.min(finite(primary?.summary?.games), finite(opponent?.summary?.games))
  const confidence = h2hGames >= 5 && minimumSample >= 10 ? '较高' : minimumSample >= 10 ? '中' : '较低'
  const margin = Math.max(8, 24 / Math.sqrt(Math.max(1, minimumSample)))
  let verdict = '接近五五开'
  if (primaryPct >= 65) verdict = `${primary.team}明显占优`
  else if (primaryPct >= 55) verdict = `${primary.team}略占优`
  else if (primaryPct <= 35) verdict = `${opponent.team}明显占优`
  else if (primaryPct <= 45) verdict = `${opponent.team}略占优`
  return {
    primaryPct,
    opponentPct,
    primaryStrength: Math.round(primaryStrength * 10) / 10,
    opponentStrength: Math.round(opponentStrength * 10) / 10,
    h2hGames,
    h2hWins,
    h2hLosses: h2hGames - h2hWins,
    confidence,
    interval: [Math.max(0, Math.round((primaryPct - margin) * 10) / 10), Math.min(100, Math.round((primaryPct + margin) * 10) / 10)],
    verdict,
  }
}
