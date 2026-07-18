import test from 'node:test'
import assert from 'node:assert/strict'
import { aggregateHeatCells, canonicalPoint, densityOpacity, matchupEstimate, officialToMap, strengthGrade, teamPerspectivePoint, teamStrength } from '../src/domain.js'

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

test('strength grade uses the same composite strength as comparison', () => {
  assert.equal(strengthGrade(80), 'S')
  assert.equal(strengthGrade(70), 'A')
  assert.equal(strengthGrade(60), 'B')
  assert.equal(strengthGrade(50), 'C')
  assert.equal(strengthGrade(40), 'D')
  assert.equal(strengthGrade(39.9), 'E')
  assert.equal(teamStrength({ ...strongTeam, summary: undefined, win_rate: 80 }), teamStrength(strongTeam))
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
