export function canonicalPoint(x, y, side) {
  return side === '蓝' ? [28 - x, 15 - y] : [x, y]
}

// Official coordinates use +Y toward the red helipad, while SVG/image pixels
// increase downward. The competition-map image therefore needs a vertical flip.
export function officialToMap(x, y) {
  return [x, 15 - y]
}

// Pixel rectangles whose inner wall edges represent the official 28×15 m
// field. The source JPGs include white margin, perimeter frame and protruding
// referee structures; those pixels are context, not playable coordinates.
const rasterFieldRois = {
  current: { imageWidth: 1683, imageHeight: 938, x: 100, y: 68, width: 1478, height: 789 },
  historical: { imageWidth: 1285, imageHeight: 691, x: 68, y: 34, width: 1138, height: 606 },
}

export function rasterMapPlacement(map = 'current') {
  const roi = rasterFieldRois[map] || rasterFieldRois.current
  return {
    offsetX: roi.x * 28 / roi.imageWidth,
    offsetY: roi.y * 15 / roi.imageHeight,
    scaleX: roi.width / roi.imageWidth,
    scaleY: roi.height / roi.imageHeight,
  }
}

export function rasterMapPoint(x, y, map = 'current') {
  const placement = rasterMapPlacement(map)
  return [placement.offsetX + x * placement.scaleX, placement.offsetY + y * placement.scaleY]
}

export function rasterMapCenter(map = 'current') {
  return rasterMapPoint(14, 7.5, map)
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
  firepower: .08,
  objective: .56,
  spatial: .12,
  defense: .11,
  resource: .12,
  adaptability: .01,
}

const southMatchupWeights = {
  ...tacticalWeights,
  spatial: .17,
  defense: .02,
  resource: .16,
}

const northMatchupWeights = {
  ...tacticalWeights,
  spatial: .04,
  resource: .20,
}

const regionalMatchupWeights = { 南部赛区: southMatchupWeights, 东部赛区: tacticalWeights, 北部赛区: northMatchupWeights }
const regionalMatchupLabels = {
  南部赛区: '南部赛区校准（火力8·目标56·空间17·防守2·资源16·适应1）',
  北部赛区: '北部赛区校准（火力8·目标56·空间4·防守11·资源20·适应1）',
}

const matchupUncertainty = {
  南部赛区: { margin: 14, foldEcePct: 13.2 },
  东部赛区: { margin: 13, foldEcePct: 12.2 },
  北部赛区: { margin: 12, foldEcePct: 7.2 },
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
    opponentScore: team?.opponent_score_analysis || null,
    consistency: team?.consistency_analysis || null,
    confidence: team?.score_confidence || null,
    dimensionConfidence: team?.dimension_confidence || null,
  }
}

export function teamStrength(team) {
  if (team?.strength_analysis?.score !== null && team?.strength_analysis?.score !== undefined && Number.isFinite(Number(team.strength_analysis.score))) {
    return Number(team.strength_analysis.score)
  }
  const tactical = Object.entries(tacticalWeights).reduce(
    (total, [key, weight]) => total + finite(team?.scores?.[key]) * weight, 0,
  )
  return tactical
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

export const roleMetrics = {
  availability_pct: { label: '有效在场率', suffix: '%', direction: 'desc' },
  deaths_per_game: { label: '场均阵亡', suffix: '', direction: 'asc' },
  terminal_hp_pct: { label: '平均终局血量', suffix: '%', direction: 'desc' },
  distance_per_game_m: { label: '场均里程', suffix: ' m', direction: 'desc' },
  attack_depth_m: { label: '平均推进纵深', suffix: ' m', direction: 'desc' },
  forward_presence_pct: { label: '前压在场占比', suffix: '%', direction: 'desc' },
  combat_damage_per_alive_min: { label: '每存活分钟净承伤', suffix: '', direction: 'asc' },
  shots_per_game: { label: '场均发弹', suffix: '', direction: 'desc' },
  high_heat_seconds_per_game: { label: '场均高热秒数', suffix: ' s', direction: 'asc' },
  position_coverage_pct: { label: '定位覆盖', suffix: '%', direction: 'desc' },
  estimated_damage_per_game: { label: '推定场均伤害', suffix: '', direction: 'desc' },
  estimated_base_damage_per_game: { label: '推定场均基地伤害', suffix: '', direction: 'desc' },
  estimated_outpost_damage_per_game: { label: '推定场均前哨伤害', suffix: '', direction: 'desc' },
  estimated_robot_damage_per_game: { label: '推定场均机器人伤害', suffix: '', direction: 'desc' },
  estimated_damage_confidence_pct: { label: '伤害归因置信度', suffix: '%', direction: 'desc' },
  hits: { label: '飞镖命中', suffix: '', direction: 'desc' },
  damage: { label: '飞镖伤害', suffix: '', direction: 'desc' },
  hit_game_pct: { label: '飞镖命中覆盖', suffix: '%', direction: 'desc' },
  median_first_hit_sec: { label: '首命中中位时间', suffix: ' s', direction: 'asc' },
  gate_events: { label: '闸门事件', suffix: '', direction: 'desc' },
}

export function rankRoleTeams(teams, metric = 'availability_pct') {
  const definition = roleMetrics[metric] || roleMetrics.availability_pct
  const usable = (teams || []).filter(team => team?.summary?.[metric] !== null && team?.summary?.[metric] !== undefined && Number.isFinite(Number(team.summary[metric])))
  const sorted = [...usable].sort((first, second) => {
    const difference = Number(first.summary[metric]) - Number(second.summary[metric])
    return (definition.direction === 'asc' ? difference : -difference) || first.team.localeCompare(second.team, 'zh-CN')
  })
  return sorted.map(team => {
    const value = Number(team.summary[metric])
    const factRank = 1 + usable.filter(other => definition.direction === 'asc'
      ? Number(other.summary[metric]) < value
      : Number(other.summary[metric]) > value).length
    return { ...team, factRank, factValue: value }
  })
}

export function roleFrameSeries(game) {
  const columns = game?.frame_columns || []
  const index = Object.fromEntries(columns.map((column, position) => [column, position]))
  const frames = game?.frames || []
  return frames.map(frame => {
    const heat17 = Number(frame[index.heat17] || 0)
    const heat42 = Number(frame[index.heat42] || 0)
    const heat17Limit = Number(frame[index.heat17_limit] || 0)
    const heat42Limit = Number(frame[index.heat42_limit] || 0)
    return {
      raw: frame,
      second: Number(frame[index.second] || 0),
      hpRatio: Number(frame[index.max_hp]) > 0 ? Number(frame[index.hp] || 0) / Number(frame[index.max_hp]) : 0,
      heatRatio: Math.max(heat17Limit > 0 ? heat17 / heat17Limit : 0, heat42Limit > 0 ? heat42 / heat42Limit : 0),
      power: Number(frame[index.power] || 0),
      x: Number(frame[index.x]),
      y: Number(frame[index.y]),
      valid: Number.isFinite(Number(frame[index.x])) && Number.isFinite(Number(frame[index.y])) && Number(frame[index.x]) >= 0 && Number(frame[index.x]) <= 28 && Number(frame[index.y]) >= 0 && Number(frame[index.y]) <= 15 && !(Number(frame[index.x]) === 0 && Number(frame[index.y]) === 0),
    }
  })
}

export function matchupEstimate(primary, opponent, headToHead = [], context = {}) {
  const primaryStrength = teamStrength(primary)
  const opponentStrength = teamStrength(opponent)
  const primaryRegion = primary?.summary?.region || primary?.region
  const opponentRegion = opponent?.summary?.region || opponent?.region
  const sameRegion = primaryRegion === opponentRegion
  const dimensionWeights = sameRegion ? (regionalMatchupWeights[primaryRegion] || tacticalWeights) : tacticalWeights
  const weightProfile = sameRegion ? (regionalMatchupLabels[primaryRegion] || '全国统一六维') : '全国统一六维'
  const resultWeight = sameRegion && primaryRegion === '东部赛区' ? 0.10 : 0
  const primaryResult = finite(primary?.strength_analysis?.result_score, 50)
  const opponentResult = finite(opponent?.strength_analysis?.result_score, 50)
  const tacticalModelScore = team => Object.entries(dimensionWeights).reduce(
    (total, [key, weight]) => total + finite(team?.scores?.[key], 50) * weight, 0,
  )
  const primaryTacticalModel = sameRegion ? tacticalModelScore(primary) : primaryStrength
  const opponentTacticalModel = sameRegion ? tacticalModelScore(opponent) : opponentStrength
  const primaryModelScore = primaryTacticalModel * (1 - resultWeight) + primaryResult * resultWeight
  const opponentModelScore = opponentTacticalModel * (1 - resultWeight) + opponentResult * resultWeight
  const baseScale = primaryRegion === opponentRegion
    ? ({ 南部赛区: 10, 东部赛区: 10, 北部赛区: 21 }[primaryRegion] || 22)
    : 22
  // Rolling-origin tests retain a small result correction only for East-region
  // matchups. Rankings stay tactical-only and cross-region estimates remain
  // conservative because no direct cross-region sample exists in this dataset.
  const modelDifference = primaryModelScore - opponentModelScore
  const stage = context.stage === '淘汰赛' ? '淘汰赛' : '小组赛'
  const stageMultiplier = sameRegion && primaryRegion === '南部赛区' && stage === '淘汰赛' ? 0.8 : 1
  const gapMultiplier = sameRegion && primaryRegion === '南部赛区' && Math.abs(modelDifference) >= 10 ? 0.8 : 1
  const regionalScale = baseScale * stageMultiplier * gapMultiplier
  const probability = 1 / (1 + Math.exp(-modelDifference / regionalScale))
  const h2hGames = headToHead.length
  const h2hWins = headToHead.filter(match => Boolean(match.won)).length
  // Direct meetings are shown as context, but rolling-origin tests find that
  // blending consecutive series games into the probability reduces accuracy.
  const primaryPct = Math.round(probability * 1000) / 10
  const opponentPct = Math.round((100 - primaryPct) * 10) / 10
  const minimumSample = Math.min(finite(primary?.summary?.games), finite(opponent?.summary?.games))
  const confidence = !sameRegion ? '探索性'
    : primaryRegion === '北部赛区' ? (minimumSample >= 10 ? '中' : '较低')
      : minimumSample >= 15 ? '较高' : minimumSample >= 10 ? '中' : '较低'
  const uncertainty = sameRegion ? matchupUncertainty[primaryRegion] : null
  const modelMargin = uncertainty?.margin || 15
  const margin = Math.max(modelMargin, 24 / Math.sqrt(Math.max(1, minimumSample)))
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
    primaryModelScore: Math.round(primaryModelScore * 10) / 10,
    opponentModelScore: Math.round(opponentModelScore * 10) / 10,
    resultWeight,
    scale: regionalScale,
    baseScale,
    stage,
    stageMultiplier,
    gapMultiplier,
    weightProfile,
    dimensionWeights,
    modelMargin,
    foldEcePct: uncertainty?.foldEcePct ?? null,
    h2hGames,
    h2hWins,
    h2hLosses: h2hGames - h2hWins,
    confidence,
    interval: [Math.max(0, Math.round((primaryPct - margin) * 10) / 10), Math.min(100, Math.round((primaryPct + margin) * 10) / 10)],
    verdict,
  }
}

export function swissStandings(teams, rounds = [], winTarget = null, lossTarget = 3, maxRounds = 5) {
  const records = new Map((teams || []).map(team => [team.team, { team: team.team, wins: 0, losses: 0, opponents: [] }]))
  for (const round of rounds || []) for (const match of round.matches || []) {
    if (!match.winner || !records.has(match.first) || !records.has(match.second)) continue
    const loser = match.winner === match.first ? match.second : match.first
    records.get(match.winner).wins += 1; records.get(loser).losses += 1
    records.get(match.first).opponents.push(match.second); records.get(match.second).opponents.push(match.first)
  }
  const completeRounds = (rounds || []).filter(round => round.matches?.length && round.matches.every(match => match.winner)).length
  return [...records.values()].map(record => ({
    ...record,
    opponentScore: record.opponents.reduce((total, opponent) => {
      const opposingRecord = records.get(opponent)
      return total + (opposingRecord ? opposingRecord.wins - opposingRecord.losses : 0)
    }, 0),
    status: winTarget && record.wins >= winTarget ? '晋级'
      : record.losses >= lossTarget ? '淘汰'
        : completeRounds >= maxRounds ? '晋级下一阶段' : '比赛中',
  })).sort((first, second) => second.wins - first.wins || first.losses - second.losses || second.opponentScore - first.opponentScore || first.team.localeCompare(second.team, 'zh-CN'))
}

export function swissNextPairings(teams, rounds = [], winTarget = null, lossTarget = 3, maxRounds = 5) {
  const members = [...(teams || [])]
  const standings = swissStandings(members, rounds, winTarget, lossTarget, maxRounds)
  const completed = (rounds || []).filter(round => round.matches?.length && round.matches.every(match => match.winner)).length
  if (completed >= maxRounds || (rounds || []).some(round => round.matches?.some(match => !match.winner))) return []
  const activeNames = new Set(standings.filter(record => record.status === '比赛中').map(record => record.team))
  const active = members.filter(team => activeNames.has(team.team))
  if (!rounds.length) return active.slice(0, active.length / 2).reduce((pairs, team, index) => {
    const opponent = active[active.length - 1 - index]
    if (opponent) pairs.push(makeSwissPair(team, opponent))
    return pairs
  }, [])
  const recordMap = new Map(standings.map(record => [record.team, record]))
  const history = new Set()
  for (const round of rounds) for (const match of round.matches || []) history.add([match.first, match.second].sort().join('|'))
  const pool = [...active].sort((first, second) => {
    const a = recordMap.get(first.team), b = recordMap.get(second.team)
    return b.wins - a.wins || a.losses - b.losses || b.opponentScore - a.opponentScore || teamStrength(second) - teamStrength(first)
  })
  const pairs = []
  while (pool.length >= 2) {
    const first = pool.shift()
    const firstRecord = recordMap.get(first.team)
    let bestIndex = 0, bestScore = Infinity
    for (let index = 0; index < pool.length; index += 1) {
      const candidate = pool[index], candidateRecord = recordMap.get(candidate.team)
      const rematch = history.has([first.team, candidate.team].sort().join('|')) ? 10000 : 0
      const recordGap = Math.abs(firstRecord.wins - candidateRecord.wins) * 1000 + Math.abs(firstRecord.losses - candidateRecord.losses) * 500
      const strengthGap = Math.abs(teamStrength(first) - teamStrength(candidate))
      const score = rematch + recordGap + strengthGap
      if (score < bestScore) { bestScore = score; bestIndex = index }
    }
    pairs.push(makeSwissPair(first, pool.splice(bestIndex, 1)[0]))
  }
  return pairs
}

export function seriesWinProbability(singleGamePct, bestOf = 3) {
  const probability = Math.max(0, Math.min(1, Number(singleGamePct) / 100))
  const winsNeeded = Math.floor(bestOf / 2) + 1
  let total = 0
  const combination = (n, k) => {
    let result = 1
    for (let index = 1; index <= k; index += 1) result = result * (n - index + 1) / index
    return result
  }
  for (let wins = winsNeeded; wins <= bestOf; wins += 1) total += combination(bestOf, wins) * probability ** wins * (1 - probability) ** (bestOf - wins)
  return Math.round(total * 1000) / 10
}

function makeSeriesPair(first, second, bestOf = 3, stage = '小组赛') {
  const estimate = matchupEstimate(first, second, [], { stage })
  const firstPct = seriesWinProbability(estimate.primaryPct, bestOf)
  return { first: first.team, second: second.team, firstPct, secondPct: Math.round((100 - firstPct) * 10) / 10, confidence: estimate.confidence, bestOf, winner: null }
}

function makeSwissPair(first, second) { return makeSeriesPair(first, second, 3) }

export function predictedWinner(match, mode = 'random', rng = Math.random) {
  if (!match?.first || !match?.second) return null
  if (mode === 'favorite') return match.firstPct >= match.secondPct ? match.first : match.second
  return rng() < Number(match.firstPct) / 100 ? match.first : match.second
}

export function doubleEliminationStandings(teams, rounds = [], target = Math.ceil((teams || []).length / 2)) {
  const records = new Map((teams || []).map(team => [team.team, { team: team.team, wins: 0, losses: 0, opponents: [] }]))
  for (const round of rounds || []) for (const match of round.matches || []) {
    if (!match.winner || !records.has(match.first) || !records.has(match.second)) continue
    const loser = match.winner === match.first ? match.second : match.first
    records.get(match.winner).wins += 1
    records.get(loser).losses += 1
    records.get(match.first).opponents.push(match.second)
    records.get(match.second).opponents.push(match.first)
  }
  const activeCount = [...records.values()].filter(record => record.losses < 2).length
  return [...records.values()].map(record => ({
    ...record,
    status: record.losses >= 2 ? '淘汰' : activeCount <= target ? '晋级' : '比赛中',
  })).sort((first, second) => first.losses - second.losses || second.wins - first.wins || first.team.localeCompare(second.team, 'zh-CN'))
}

export function doubleEliminationNextPairings(teams, rounds = [], target = Math.ceil((teams || []).length / 2)) {
  const members = [...(teams || [])]
  if ((rounds || []).some(round => round.matches?.some(match => !match.winner))) return []
  const standings = doubleEliminationStandings(members, rounds, target)
  const activeNames = new Set(standings.filter(record => record.status === '比赛中').map(record => record.team))
  const active = members.filter(team => activeNames.has(team.team))
  if (active.length <= target) return []
  const recordMap = new Map(standings.map(record => [record.team, record]))
  const history = new Set()
  for (const round of rounds || []) for (const match of round.matches || []) history.add([match.first, match.second].sort().join('|'))
  const pool = [...active].sort((first, second) => {
    const a = recordMap.get(first.team), b = recordMap.get(second.team)
    return a.losses - b.losses || b.wins - a.wins || teamStrength(second) - teamStrength(first)
  })
  const pairs = []
  while (pool.length >= 2) {
    const first = pool.shift(), firstRecord = recordMap.get(first.team)
    let bestIndex = 0, bestScore = Infinity
    for (let index = 0; index < pool.length; index += 1) {
      const candidate = pool[index], candidateRecord = recordMap.get(candidate.team)
      const score = Math.abs(firstRecord.losses - candidateRecord.losses) * 1000
        + (history.has([first.team, candidate.team].sort().join('|')) ? 100 : 0)
        + teamStrength(candidate)
      if (score < bestScore) { bestScore = score; bestIndex = index }
    }
    pairs.push(makeSeriesPair(first, pool.splice(bestIndex, 1)[0], 3, '淘汰赛'))
  }
  return pairs
}

export function simulateSwissStage(teams, config, rng = Math.random) {
  const rounds = []
  for (let round = 0; round < config.swiss_rounds; round += 1) {
    const matches = swissNextPairings(teams, rounds, config.win_target, config.loss_target, config.swiss_rounds)
    for (const match of matches) match.winner = predictedWinner(match, 'random', rng)
    rounds.push({ round: round + 1, matches })
  }
  return { rounds, standings: swissStandings(teams, rounds, config.win_target, config.loss_target, config.swiss_rounds) }
}

export function simulateDoubleElimination(teams, target, rng = Math.random) {
  const rounds = []
  for (let round = 1; round <= 12; round += 1) {
    const matches = doubleEliminationNextPairings(teams, rounds, target)
    if (!matches.length) break
    for (const match of matches) match.winner = predictedWinner(match, 'random', rng)
    rounds.push({ round, matches })
  }
  const standings = doubleEliminationStandings(teams, rounds, target)
  return { rounds, standings, qualifiers: standings.filter(record => record.status === '晋级').map(record => record.team) }
}

function makeSeededRandom(seed = 2026) {
  let state = seed >>> 0
  return () => {
    state = (1664525 * state + 1013904223) >>> 0
    return state / 4294967296
  }
}

export function monteCarloTournament(groups, config, mode = 'repechage', iterations = 1000, seed = 2026) {
  const members = (groups || []).flat()
  const byName = new Map(members.map(team => [team.team, team]))
  const counts = new Map(members.map(team => [team.team, { swiss: 0, qualify: 0, top8: 0, top4: 0, champion: 0 }]))
  const rng = makeSeededRandom(seed)
  const add = (names, key) => names.forEach(name => { if (counts.has(name)) counts.get(name)[key] += 1 })
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const swissNames = []
    for (const group of groups) {
      const result = simulateSwissStage(group, config, rng)
      swissNames.push(...result.standings.filter(record => record.status !== '淘汰').map(record => record.team))
    }
    add(swissNames, 'swiss')
    const swissTeams = swissNames.map(name => byName.get(name)).filter(Boolean)
    const firstDouble = simulateDoubleElimination(swissTeams, swissTeams.length / 2, rng)
    add(firstDouble.qualifiers, 'qualify')
    if (mode !== 'finals') continue
    add(firstDouble.qualifiers, 'top8')
    const top8Teams = firstDouble.qualifiers.map(name => byName.get(name)).filter(Boolean)
    const secondDouble = simulateDoubleElimination(top8Teams, 4, rng)
    add(secondDouble.qualifiers, 'top4')
    const seeded = secondDouble.qualifiers.map(name => byName.get(name)).filter(Boolean).sort((a, b) => teamStrength(b) - teamStrength(a))
    const semifinals = [makeSeriesPair(seeded[0], seeded[3], 3, '淘汰赛'), makeSeriesPair(seeded[1], seeded[2], 3, '淘汰赛')]
    const finalists = semifinals.map(match => predictedWinner(match, 'random', rng))
    const finalMatch = makeSeriesPair(byName.get(finalists[0]), byName.get(finalists[1]), 5, '淘汰赛')
    add([predictedWinner(finalMatch, 'random', rng)], 'champion')
  }
  const pct = value => Math.round(value * 1000 / iterations) / 10
  return [...counts.entries()].map(([team, result]) => ({
    team,
    swissPct: pct(result.swiss),
    qualifyPct: pct(result.qualify),
    top8Pct: pct(result.top8),
    top4Pct: pct(result.top4),
    championPct: pct(result.champion),
  })).sort((first, second) => (mode === 'finals' ? second.championPct - first.championPct : second.qualifyPct - first.qualifyPct) || first.team.localeCompare(second.team, 'zh-CN'))
}
