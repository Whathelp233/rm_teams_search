import test from 'node:test'
import assert from 'node:assert/strict'
import { aggregateHeatCells, canonicalPoint, densityOpacity, matchupEstimate, officialToMap, rankTeamsByStrength, strengthGrade, summarizeDimensions, teamPerspectivePoint, teamStrength } from '../src/domain.js'

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

test('composite strength gives defense a 15 percent effective weight', () => {
  const baseline = { summary: { win_rate: 50 }, scores: { firepower: 50, objective: 50, spatial: 50, defense: 0, resource: 50, adaptability: 50 } }
  const defended = { ...baseline, scores: { ...baseline.scores, defense: 100 } }
  assert.equal(teamStrength(defended) - teamStrength(baseline), 15)
})

test('strength grade uses the same composite strength as comparison', () => {
  assert.equal(strengthGrade(80), 'S')
  assert.equal(strengthGrade(70), 'A')
  assert.equal(strengthGrade(60), 'B')
  assert.equal(strengthGrade(50), 'C')
  assert.equal(strengthGrade(40), 'D')
  assert.equal(strengthGrade(39.9), 'E')
  assert.equal(teamStrength({ ...strongTeam, summary: undefined, win_rate: 80 }), teamStrength(strongTeam))
})

test('team list ranking is descending by composite strength', () => {
  const ranked = rankTeamsByStrength([weakerTeam, strongTeam])
  assert.deepEqual(ranked.map(team => team.team), ['强队', '弱队'])
  assert.deepEqual(ranked.map(team => team.strengthRank), [1, 2])
  assert.ok(ranked[0].strengthValue > ranked[1].strengthValue)
})

test('high-dimensional summary keeps match-level timing, resource, and source detail', () => {
  const spatialAnalysis = { version: '2.2.0', score: 75.3, components: { mobility_intensity: 62, attack_depth: 74.5, deep_pressure: 82.8 } }
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
  assert.equal(estimate.confidence, '中')
  assert.match(estimate.verdict, /强队/)
})

test('head-to-head evidence adjusts but does not replace the model', () => {
  const withoutHistory = matchupEstimate(strongTeam, weakerTeam)
  const upsetHistory = matchupEstimate(strongTeam, weakerTeam, [{ won: 0 }, { won: 0 }, { won: 0 }])
  assert.ok(upsetHistory.primaryPct < withoutHistory.primaryPct)
  assert.ok(upsetHistory.primaryPct > 50)
})
