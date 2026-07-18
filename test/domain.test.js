import test from 'node:test'
import assert from 'node:assert/strict'
import { aggregateHeatCells, canonicalPoint, densityOpacity, officialToMap, reliabilityTone, teamPerspectivePoint } from '../src/domain.js'

test('red side remains in official coordinates', () => {
  assert.deepEqual(canonicalPoint(3, 4, '红'), [3, 4])
})

test('blue side is centrally mirrored for own-side view', () => {
  assert.deepEqual(canonicalPoint(25, 11, '蓝'), [3, 4])
})

test('reliability grades have stable visual groups', () => {
  assert.equal(reliabilityTone('A'), 'good')
  assert.equal(reliabilityTone('C'), 'warn')
  assert.equal(reliabilityTone('E'), 'bad')
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
