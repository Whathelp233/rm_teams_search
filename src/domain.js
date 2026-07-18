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
  firepower: .18,
  objective: .20,
  spatial: .17,
  defense: .20,
  resource: .10,
  adaptability: .15,
}

function finite(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function average(values) {
  const usable = values.filter(value => value !== null && value !== undefined && value !== '').map(value => Number(value)).filter(Number.isFinite)
  return usable.length ? usable.reduce((total, value) => total + value, 0) / usable.length : null
}

function median(values) {
  const usable = values.filter(value => value !== null && value !== undefined && value !== '').map(value => Number(value)).filter(Number.isFinite).sort((a, b) => a - b)
  if (!usable.length) return null
  const middle = Math.floor(usable.length / 2)
  return usable.length % 2 ? usable[middle] : (usable[middle - 1] + usable[middle]) / 2
}

function rounded(value, digits = 1) {
  return value === null ? null : Math.round(value * (10 ** digits)) / (10 ** digits)
}

export function summarizeDimensions(team) {
  const matches = team?.matches || []
  const games = Math.max(1, matches.length)
  const sum = key => matches.reduce((total, match) => total + finite(match[key]), 0)
  const totalCoins = sum('total_coins_final')
  const validPositions = sum('valid_position_points')
  const invalidPositions = sum('invalid_position_points')
  const baseDamage = Math.max(1, sum('base_damage'))
  const outpostAttacks = matches.filter(match => match.first_outpost_damage_sec !== null && match.first_outpost_damage_sec !== undefined && Number.isFinite(Number(match.first_outpost_damage_sec)))
  const outpostTimeline = outpostAttacks.map(match => {
    const firstDamageSec = Number(match.first_outpost_damage_sec)
    const rawDestroySec = match.outpost_destroy_sec === null || match.outpost_destroy_sec === undefined ? null : Number(match.outpost_destroy_sec)
    const destroySec = Number.isFinite(rawDestroySec) && rawDestroySec >= firstDamageSec ? rawDestroySec : null
    return {
      gameId: match.game_id,
      opponent: match.opponent,
      side: match.side,
      won: Boolean(match.won),
      firstDamageSec,
      damage: rounded(finite(match.outpost_damage), 0),
      destroySec,
      killDurationSec: destroySec === null ? null : rounded(destroySec - firstDamageSec),
    }
  }).sort((a, b) => a.firstDamageSec - b.firstDamageSec)
  const outpostKills = outpostTimeline.filter(event => event.killDurationSec !== null)
  return {
    mobility: {
      distanceM: rounded(average(matches.map(match => match.distance_m))),
      pairDistanceM: rounded(average(matches.map(match => match.mean_pair_distance_m))),
      attackDepthM: rounded(average(matches.map(match => match.mean_attack_depth_m))),
      deepPressureSec: rounded(average(matches.map(match => match.deep_pressure_seconds))),
      positionCoveragePct: rounded(validPositions * 100 / Math.max(1, validPositions + invalidPositions)),
    },
    resource: {
      totalCoins: rounded(average(matches.map(match => match.total_coins_final))),
      remainingCoins: rounded(average(matches.map(match => match.remaining_coins_final))),
      spendPct: rounded((totalCoins - sum('remaining_coins_final')) * 100 / Math.max(1, totalCoins)),
      meanPower: rounded(average(matches.map(match => match.mean_power))),
      highHeatSec: rounded(average(matches.map(match => match.high_heat_seconds))),
    },
    objective: {
      firstOutpostSec: rounded(median(matches.map(match => match.first_outpost_damage_sec))),
      earliestOutpostSec: outpostTimeline.length ? rounded(outpostTimeline[0].firstDamageSec) : null,
      outpostAttackGames: outpostAttacks.length,
      outpostAttackPct: rounded(outpostAttacks.length * 100 / games),
      outpostWithin90Pct: rounded(outpostAttacks.filter(match => Number(match.first_outpost_damage_sec) <= 90).length * 100 / games),
      outpostWithin180Pct: rounded(outpostAttacks.filter(match => Number(match.first_outpost_damage_sec) <= 180).length * 100 / games),
      outpostKillGames: outpostKills.length,
      fastestOutpostKillSec: outpostKills.length ? Math.min(...outpostKills.map(event => event.killDurationSec)) : null,
      medianOutpostKillSec: rounded(median(outpostKills.map(event => event.killDurationSec))),
      outpostTimeline,
      firstBaseSec: rounded(median(matches.map(match => match.first_base_damage_sec))),
      outpostDestroyPct: rounded(outpostKills.length * 100 / games),
      buffsPerGame: rounded(sum('buffs') / games),
      runePerGame: rounded(sum('rune_events') / games),
      assemblyPerGame: rounded(sum('assembly_events') / games),
    },
    firepower: {
      shots17PerGame: rounded(sum('shots_17') / games),
      shots42PerGame: rounded(sum('shots_42') / games),
      highHeatSec: rounded(average(matches.map(match => match.high_heat_seconds))),
      base17Pct: rounded(sum('base_damage_17') * 100 / baseDamage),
      base42Pct: rounded(sum('base_damage_42') * 100 / baseDamage),
      baseDartPct: rounded(sum('base_damage_dart') * 100 / baseDamage),
    },
    radar: team?.radar_analysis || null,
    analysis: {
      firepower: team?.firepower_analysis || null,
      objective: team?.objective_analysis || null,
      spatial: team?.spatial_analysis || null,
      defense: team?.defense_analysis || null,
      resource: team?.resource_analysis || null,
      adaptability: team?.adaptability_analysis || null,
    },
    spatial: team?.spatial_analysis || null,
    defense: team?.defense_analysis || null,
    strength: team?.strength_analysis || null,
    consistency: team?.consistency_analysis || null,
    confidence: team?.score_confidence || null,
  }
}

export function teamStrength(team) {
  const tactical = Object.entries(tacticalWeights).reduce(
    (total, [key, weight]) => total + finite(team?.scores?.[key]) * weight, 0,
  )
  const result = finite(team?.strength_analysis?.result_score, finite(team?.summary?.win_rate ?? team?.win_rate))
  return .75 * tactical + .25 * result
}

export function strengthGrade(score) {
  const value = finite(score)
  if (value >= 75) return 'S'
  if (value >= 65) return 'A'
  if (value >= 55) return 'B'
  if (value >= 45) return 'C'
  if (value >= 35) return 'D'
  return 'E'
}

export function rankTeamsByStrength(teams) {
  return [...(teams || [])]
    .sort((first, second) => teamStrength(second) - teamStrength(first) || first.team.localeCompare(second.team, 'zh-CN'))
    .map((team, index) => ({ ...team, strengthRank: index + 1, strengthValue: rounded(teamStrength(team)) }))
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
