import test from 'node:test'
import assert from 'node:assert/strict'
import { aggregateHeatCells, canonicalPoint, densityOpacity, doubleEliminationNextPairings, doubleEliminationStandings, matchupEstimate, monteCarloTournament, officialToMap, predictedWinner, rankRoleTeams, rankTeamsByStrength, rasterMapCenter, rasterMapPlacement, rasterMapPoint, roleFrameSeries, seriesWinProbability, simulateDoubleElimination, strengthGrade, summarizeDimensions, swissNextPairings, swissStandings, teamPerspectivePoint, teamStrength } from '../src/domain.js'

test('red side remains in official coordinates', () => {
  assert.deepEqual(canonicalPoint(3, 4, '红'), [3, 4])
})

test('blue side is centrally mirrored for own-side view', () => {
  assert.deepEqual(canonicalPoint(25, 11, '蓝'), [3, 4])
})

test('official positive Y is vertically flipped onto the field image', () => {
  assert.deepEqual(officialToMap(3, 4), [3, 11])
  assert.deepEqual(officialToMap(25, 11), [25, 4])
})

test('raster coordinates respect the inner wall ROI instead of the image border', () => {
  const placement = rasterMapPlacement('current')
  assert.deepEqual(rasterMapPoint(0, 0, 'current'), [placement.offsetX, placement.offsetY])
  assert.deepEqual(rasterMapPoint(14, 7.5, 'current'), rasterMapCenter('current'))
  assert.ok(rasterMapPoint(28, 15, 'current')[0] < 28)
  assert.ok(rasterMapPoint(28, 15, 'current')[1] < 15)
})

test('blue team perspective rotates both teams as one world', () => {
  assert.deepEqual(teamPerspectivePoint(3, 4, '蓝'), [25, 4])
  assert.deepEqual(teamPerspectivePoint(25, 11, '蓝'), [3, 11])
})

test('heatmap seconds aggregate once per side and grid cell', () => {
  const rows = [
    ['蓝', '哨兵', 1, 10, 12, 1],
    ['蓝', '哨兵', 2, 10, 12, 1],
    ['红', '哨兵', 3, 10, 12, 1],
  ]
  const cells = aggregateHeatCells(rows, row => [row[3], row[4]])
  assert.equal(cells.length, 2)
  assert.equal(cells.find(cell => cell.side === '蓝').samples, 2)
})

test('log heat scale keeps a one-second cell faint', () => {
  assert.ok(densityOpacity(1, 100) < .05)
  assert.equal(densityOpacity(100, 100), .88)
})

const strongTeam = {
  team: '强队',
  summary: { games: 20, win_rate: 80 },
  scores: { firepower: 85, objective: 80, spatial: 75, defense: 82, resource: 70, adaptability: 78 },
}
const weakerTeam = {
  team: '弱队',
  summary: { games: 20, win_rate: 35 },
  scores: { firepower: 40, objective: 45, spatial: 50, defense: 42, resource: 55, adaptability: 48 },
}

test('team comparison uses tactical and historical result inputs', () => {
  assert.ok(teamStrength(strongTeam) > teamStrength(weakerTeam))
})

test('composite strength gives defense its full eleven percent tactical weight', () => {
  const baseline = { summary: { win_rate: 50 }, scores: { firepower: 50, objective: 50, spatial: 50, defense: 0, resource: 50, adaptability: 50 } }
  const defended = { ...baseline, scores: { ...baseline.scores, defense: 100 } }
  assert.ok(Math.abs(teamStrength(defended) - teamStrength(baseline) - 11) < 1e-9)
})

test('strength grade uses the same composite strength as comparison', () => {
  assert.equal(strengthGrade(75), 'S')
  assert.equal(strengthGrade(65), 'A')
  assert.equal(strengthGrade(55), 'B')
  assert.equal(strengthGrade(45), 'C')
  assert.equal(strengthGrade(35), 'D')
  assert.equal(strengthGrade(34.9), 'E')
  assert.equal(teamStrength({ ...strongTeam, summary: undefined, win_rate: 80 }), teamStrength(strongTeam))
})

test('team list ranking is descending by composite strength', () => {
  const ranked = rankTeamsByStrength([weakerTeam, strongTeam])
  assert.deepEqual(ranked.map(team => team.team), ['强队', '弱队'])
  assert.deepEqual(ranked.map(team => team.strengthRank), [1, 2])
  assert.ok(ranked[0].strengthValue > ranked[1].strengthValue)
})

test('high-dimensional summary keeps match-level timing, resource, and source detail', () => {
  const spatialAnalysis = { version: '3.0.0', score: 71.5, components: { relative_territory: 72.8, forward_presence: 76, neutral_control: 68.8 } }
  const summary = summarizeDimensions({ spatial_analysis: spatialAnalysis, matches: [
    { distance_m: 600, mean_pair_distance_m: 8, mean_attack_depth_m: 9, deep_pressure_seconds: 100, valid_position_points: 90, invalid_position_points: 10, total_coins_final: 1000, remaining_coins_final: 200, mean_power: 70, high_heat_seconds: 20, first_outpost_damage_sec: 80, first_base_damage_sec: 300, outpost_destroy_sec: 200, buffs: 4, rune_events: 1, assembly_events: 2, shots_17: 500, shots_42: 10, base_damage: 1000, base_damage_17: 500, base_damage_42: 300, base_damage_dart: 200 },
    { distance_m: 800, mean_pair_distance_m: 10, mean_attack_depth_m: 11, deep_pressure_seconds: 200, valid_position_points: 80, invalid_position_points: 20, total_coins_final: 1200, remaining_coins_final: 300, mean_power: 90, high_heat_seconds: 40, first_outpost_damage_sec: 120, first_base_damage_sec: null, outpost_destroy_sec: null, buffs: 2, rune_events: 0, assembly_events: 0, shots_17: 700, shots_42: 20, base_damage: 500, base_damage_17: 250, base_damage_42: 0, base_damage_dart: 250 },
  ] })
  assert.equal(summary.mobility.distanceM, 700)
  assert.equal(summary.mobility.positionCoveragePct, 85)
  assert.deepEqual(summary.spatial, spatialAnalysis)
  assert.equal(summary.resource.spendPct, 77.3)
  assert.equal(summary.objective.firstOutpostSec, 100)
  assert.equal(summary.objective.earliestOutpostSec, 80)
  assert.equal(summary.objective.outpostAttackGames, 2)
  assert.equal(summary.objective.outpostAttackPct, 100)
  assert.equal(summary.objective.outpostWithin90Pct, 50)
  assert.equal(summary.objective.outpostWithin180Pct, 100)
  assert.equal(summary.objective.outpostKillGames, 1)
  assert.equal(summary.objective.fastestOutpostKillSec, 120)
  assert.equal(summary.objective.medianOutpostKillSec, 120)
  assert.equal(summary.objective.outpostTimeline[0].firstDamageSec, 80)
  assert.equal(summary.objective.outpostTimeline[0].killDurationSec, 120)
  assert.equal(summary.objective.outpostTimeline[1].killDurationSec, null)
  assert.equal(summary.objective.outpostDestroyPct, 50)
  assert.equal(summary.firepower.baseDartPct, 30)
})

test('matchup estimate is complementary and reports sample confidence', () => {
  const estimate = matchupEstimate(strongTeam, weakerTeam)
  assert.equal(estimate.primaryPct + estimate.opponentPct, 100)
  assert.ok(estimate.primaryPct > 70)
  assert.equal(estimate.confidence, '较高')
  assert.match(estimate.verdict, /强队/)
})

test('Swiss simulator pairs by record, avoids rematches, and eliminates at two losses', () => {
  const team = index => ({ ...strongTeam, team: `队伍${index}`, scores: Object.fromEntries(Object.keys(strongTeam.scores).map(key => [key, 80 - index])) })
  const teams = Array.from({ length: 8 }, (_, index) => team(index))
  const rounds = []
  for (let round = 0; round < 3; round += 1) {
    const matches = swissNextPairings(teams, rounds, null, 2, 3)
    assert.equal(matches.length, round < 2 ? 4 : 3)
    for (const match of matches) {
      assert.equal(match.firstPct + match.secondPct, 100)
      match.winner = match.first
    }
    rounds.push({ matches })
  }
  const pairs = rounds.flatMap(round => round.matches.map(match => [match.first, match.second].sort().join('|')))
  assert.equal(new Set(pairs).size, pairs.length)
  const standings = swissStandings(teams, rounds, null, 2, 3)
  assert.equal(standings.filter(team => team.status === '淘汰').length, 4)
  assert.equal(standings.filter(team => team.status === '晋级下一阶段').length, 4)
})

test('national Swiss simulator resolves eight qualifiers at three wins and eight eliminations at three losses', () => {
  const team = index => ({ ...strongTeam, team: `全国队伍${index}`, scores: Object.fromEntries(Object.keys(strongTeam.scores).map(key => [key, 82 - index])) })
  const teams = Array.from({ length: 16 }, (_, index) => team(index))
  const rounds = []
  for (let round = 1; round <= 5; round += 1) {
    const matches = swissNextPairings(teams, rounds, 3, 3, 5)
    assert.equal(matches.length, [8, 8, 8, 6, 3][round - 1])
    for (const match of matches) match.winner = match.first
    rounds.push({ round, matches })
  }
  const standings = swissStandings(teams, rounds, 3, 3, 5)
  assert.equal(standings.filter(team => team.status === '晋级').length, 8)
  assert.equal(standings.filter(team => team.status === '淘汰').length, 8)
  assert.ok(standings.every(team => Number.isInteger(team.opponentScore)))
})

test('probability simulation can produce an upset while favorite mode remains explicit', () => {
  const match = { first: '热门', second: '冷门', firstPct: 80, secondPct: 20 }
  assert.equal(predictedWinner(match, 'favorite', () => .99), '热门')
  assert.equal(predictedWinner(match, 'random', () => .79), '热门')
  assert.equal(predictedWinner(match, 'random', () => .81), '冷门')
})

test('BO3 and BO5 convert single-game probability into complementary series probability', () => {
  assert.equal(seriesWinProbability(50, 3), 50)
  assert.equal(seriesWinProbability(50, 5), 50)
  assert.equal(seriesWinProbability(60, 3), 64.8)
  assert.equal(seriesWinProbability(60, 5), 68.3)
  assert.equal(seriesWinProbability(40, 5), 31.7)
})

test('double-elimination qualification requires two losses and halves the field', () => {
  const team = index => ({ ...strongTeam, team: `双败队伍${index}`, scores: Object.fromEntries(Object.keys(strongTeam.scores).map(key => [key, 80 - index])) })
  const teams = Array.from({ length: 8 }, (_, index) => team(index))
  const result = simulateDoubleElimination(teams, 4, () => .25)
  assert.equal(result.rounds.length, 3)
  assert.equal(result.qualifiers.length, 4)
  assert.equal(result.standings.filter(team => team.status === '淘汰').length, 4)
  assert.ok(result.standings.filter(team => team.status === '淘汰').every(team => team.losses === 2))
  assert.equal(doubleEliminationNextPairings(teams, result.rounds, 4).length, 0)
  assert.equal(doubleEliminationStandings(teams, result.rounds, 4).filter(team => team.status === '晋级').length, 4)
})

test('Monte Carlo tournament reports bounded non-deterministic advancement probabilities', () => {
  const team = index => ({ ...strongTeam, team: `模拟队伍${index}`, scores: Object.fromEntries(Object.keys(strongTeam.scores).map(key => [key, 75 - index])) })
  const groups = [Array.from({ length: 8 }, (_, index) => team(index)), Array.from({ length: 8 }, (_, index) => team(index + 8))]
  const result = monteCarloTournament(groups, { swiss_rounds: 3, win_target: null, loss_target: 2 }, 'repechage', 200, 7)
  assert.equal(result.length, 16)
  assert.equal(result.reduce((total, team) => total + team.qualifyPct, 0), 400)
  assert.ok(result.every(team => team.qualifyPct >= 0 && team.qualifyPct <= 100))
  assert.ok(result.some(team => team.qualifyPct > 0 && team.qualifyPct < 100))
})

test('head-to-head evidence is contextual and does not alter calibrated probability', () => {
  const withoutHistory = matchupEstimate(strongTeam, weakerTeam)
  const upsetHistory = matchupEstimate(strongTeam, weakerTeam, [{ won: 0 }, { won: 0 }, { won: 0 }])
  assert.equal(upsetHistory.primaryPct, withoutHistory.primaryPct)
  assert.ok(upsetHistory.primaryPct > 50)
})

test('only same-region East matchup uses the ten-percent result correction', () => {
  const first = { ...strongTeam, summary: { ...strongTeam.summary, region: '东部赛区' }, strength_analysis: { score: 60, result_score: 90 } }
  const second = { ...weakerTeam, summary: { ...weakerTeam.summary, region: '东部赛区' }, strength_analysis: { score: 60, result_score: 10 } }
  const east = matchupEstimate(first, second)
  assert.equal(east.resultWeight, .1)
  assert.equal(east.scale, 10)
  assert.ok(east.primaryPct > 50)
  const cross = matchupEstimate(first, { ...second, summary: { ...second.summary, region: '北部赛区' } })
  assert.equal(cross.resultWeight, 0)
  assert.equal(cross.scale, 22)
  assert.equal(cross.primaryPct, 50)
})

test('North matchup calibration shifts noisy spatial weight into resource evidence', () => {
  const first = { ...strongTeam, summary: { ...strongTeam.summary, region: '北部赛区' }, scores: { ...strongTeam.scores, spatial: 0, resource: 100 }, strength_analysis: { score: 60, result_score: 50 } }
  const second = { ...weakerTeam, summary: { ...weakerTeam.summary, region: '北部赛区' }, scores: { ...weakerTeam.scores, spatial: 100, resource: 0 }, strength_analysis: { score: 60, result_score: 50 } }
  const north = matchupEstimate(first, second)
  assert.equal(north.weightProfile, '北部赛区校准')
  assert.equal(north.scale, 21)
  assert.equal(north.dimensionWeights.spatial, .08)
  assert.equal(north.dimensionWeights.resource, .16)
  assert.ok(north.primaryPct > 50)
  assert.equal(north.confidence, '中')
  assert.equal(north.modelMargin, 12)
})

test('cross-region matchup stays exploratory and exposes a wider interval', () => {
  const first = { ...strongTeam, summary: { ...strongTeam.summary, region: '南部赛区' } }
  const second = { ...weakerTeam, summary: { ...weakerTeam.summary, region: '北部赛区' } }
  const cross = matchupEstimate(first, second)
  assert.equal(cross.weightProfile, '全国统一六维')
  assert.equal(cross.confidence, '探索性')
  assert.equal(cross.modelMargin, 15)
  assert.ok(cross.interval[1] - cross.interval[0] >= 30)
})

test('regional matchup intervals cover rolling calibration drift', () => {
  const south = matchupEstimate(
    { ...strongTeam, summary: { ...strongTeam.summary, region: '南部赛区' } },
    { ...weakerTeam, summary: { ...weakerTeam.summary, region: '南部赛区' } },
  )
  assert.equal(south.foldEcePct, 11.1)
  assert.equal(south.modelMargin, 12)
  const east = matchupEstimate(
    { ...strongTeam, summary: { ...strongTeam.summary, region: '东部赛区' } },
    { ...weakerTeam, summary: { ...weakerTeam.summary, region: '东部赛区' } },
  )
  assert.equal(east.foldEcePct, 12.2)
  assert.equal(east.modelMargin, 13)
})

test('role facts rank nullable metrics without treating not-applicable as zero', () => {
  const teams = [
    { team: '乙', summary: { availability_pct: 80 } },
    { team: '甲', summary: { availability_pct: 90 } },
    { team: '工程无发弹', summary: { availability_pct: null } },
  ]
  const ranked = rankRoleTeams(teams, 'availability_pct')
  assert.deepEqual(ranked.map(team => team.team), ['甲', '乙'])
  assert.deepEqual(ranked.map(team => team.factRank), [1, 2])
})

test('role frame series reconstructs hp, heat, power, and valid position', () => {
  const game = {
    frame_columns: ['second', 'hp', 'max_hp', 'x', 'y', 'z', 'yaw', 'power', 'heat17', 'heat17_limit', 'heat42', 'heat42_limit'],
    frames: [[12, 100, 200, 3, 4, 0, 0, 80, 90, 100, 0, 0]],
  }
  const [frame] = roleFrameSeries(game)
  assert.equal(frame.hpRatio, .5)
  assert.equal(frame.heatRatio, .9)
  assert.equal(frame.power, 80)
  assert.equal(frame.valid, true)
})
