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
  firepower: .15,
  objective: .50,
  spatial: .11,
  defense: .09,
  resource: .14,
  adaptability: .01,
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
  const tactical = Object.entries(tacticalWeights).reduce(
    (total, [key, weight]) => total + finite(team?.scores?.[key]) * weight, 0,
  )
  const result = finite(team?.strength_analysis?.result_score, finite(team?.summary?.win_rate ?? team?.win_rate))
  return .90 * tactical + .10 * result
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

export function matchupEstimate(primary, opponent, headToHead = []) {
  const primaryStrength = teamStrength(primary)
  const opponentStrength = teamStrength(opponent)
  const primaryRegion = primary?.summary?.region || primary?.region
  const opponentRegion = opponent?.summary?.region || opponent?.region
  const regionalScale = primaryRegion === opponentRegion
    ? ({ 南部赛区: 16, 东部赛区: 10, 北部赛区: 24 }[primaryRegion] || 20)
    : 20
  // Rolling-origin backtests favor wider uncertainty in South and North.
  // Cross-region comparisons have no direct sample and remain conservative.
  const probability = 1 / (1 + Math.exp(-(primaryStrength - opponentStrength) / regionalScale))
  const h2hGames = headToHead.length
  const h2hWins = headToHead.filter(match => Boolean(match.won)).length
  // Direct meetings are shown as context, but rolling-origin tests find that
  // blending consecutive series games into the probability reduces accuracy.
  const primaryPct = Math.round(probability * 1000) / 10
  const opponentPct = Math.round((100 - primaryPct) * 10) / 10
  const minimumSample = Math.min(finite(primary?.summary?.games), finite(opponent?.summary?.games))
  const confidence = minimumSample >= 15 ? '较高' : minimumSample >= 10 ? '中' : '较低'
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

export function repechageGroupProjection(teams) {
  const members = [...(teams || [])]
  const pairings = []
  for (let first = 0; first < members.length; first += 1) {
    for (let second = first + 1; second < members.length; second += 1) {
      const estimate = matchupEstimate(members[first], members[second])
      pairings.push({ first, second, probability: estimate.primaryPct / 100, estimate })
    }
  }
  const advancement = Array(members.length).fill(0)
  const expectedWins = Array(members.length).fill(0)
  const wins = Array(members.length).fill(0)
  function enumerate(index, probability) {
    if (index === pairings.length) {
      const best = Math.max(...wins, 0)
      const leaders = wins.map((value, team) => value === best ? team : -1).filter(team => team >= 0)
      for (const leader of leaders) advancement[leader] += probability / leaders.length
      return
    }
    const match = pairings[index]
    wins[match.first] += 1
    enumerate(index + 1, probability * match.probability)
    wins[match.first] -= 1
    wins[match.second] += 1
    enumerate(index + 1, probability * (1 - match.probability))
    wins[match.second] -= 1
  }
  enumerate(0, 1)
  for (const match of pairings) {
    expectedWins[match.first] += match.probability
    expectedWins[match.second] += 1 - match.probability
  }
  return {
    teams: members.map((team, index) => ({
      team: team.team,
      advancePct: Math.round(advancement[index] * 1000) / 10,
      expectedWins: Math.round(expectedWins[index] * 100) / 100,
      strength: Math.round(teamStrength(team) * 10) / 10,
    })),
    pairings: pairings.map(match => ({
      first: members[match.first].team,
      second: members[match.second].team,
      firstPct: match.estimate.primaryPct,
      secondPct: match.estimate.opponentPct,
      confidence: match.estimate.confidence,
    })),
    model: '四队单循环、胜场最高晋级；同胜场并列时等分概率',
  }
}
