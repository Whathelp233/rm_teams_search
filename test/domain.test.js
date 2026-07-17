import test from 'node:test'
import assert from 'node:assert/strict'
import { canonicalPoint, reliabilityTone } from '../src/domain.js'

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
