import test from 'node:test'
import assert from 'node:assert/strict'
import { canonicalPoint, officialToMap, reliabilityTone, teamPerspectivePoint } from '../src/domain.js'

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
