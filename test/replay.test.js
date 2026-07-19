import test from 'node:test'
import assert from 'node:assert/strict'
import { activeDamageEffects, deriveDamageEffects, deriveShotEffects, interpolatedFrame, nativeFrameRate } from '../src/replay.js'

const row = (robot, x, hp, valid = 1, shots17 = 0) => [robot, x, 5, hp, 200, 0, 0, 0, shots17, 0, valid]

test('replay reports native frequency and interpolates valid positions', () => {
  const frames = [[1, [row(0, 1, 200)]], [2, [row(0, 3, 200)]]]
  assert.equal(nativeFrameRate(frames), 1)
  assert.equal(interpolatedFrame(frames, 1.5)[0][1], 2)
})

test('damage effects classify attribution confidence without inventing damage', () => {
  const data = {
    robots: [{ side: '红' }, { side: '蓝' }, { side: '蓝' }], events: [],
    frames: [[1, [row(0, 2, 200), row(1, 8, 200), row(2, 10, 200)]], [2, [row(0, 2, 180), row(1, 8, 200, 1, 1), row(2, 10, 200)]]],
  }
  const effects = deriveDamageEffects(data)
  assert.equal(effects.length, 1)
  assert.equal(effects[0].damage, 20)
  assert.equal(effects[0].confidence, 'high')
  assert.equal(effects[0].source, undefined)
  assert.equal(activeDamageEffects(effects, 2.4).length, 1)
  assert.equal(activeDamageEffects(effects, 3).length, 0)
})

test('shot effects stay at the firing robot and never invent a target trajectory', () => {
  const data = { frames: [[2, [row(0, 2, 200, 1, 3), [1, 8, 5, 200, 200, 0, 0, 0, 0, 1, 1]]]] }
  const effects = deriveShotEffects(data)
  assert.deepEqual(effects, [
    { id: '2-0', second: 2, robot: 0, x: 2, y: 5, shots17: 3, shots42: 0 },
    { id: '2-1', second: 2, robot: 1, x: 8, y: 5, shots17: 0, shots42: 1 },
  ])
  assert.ok(effects.every(effect => !('target' in effect)))
})

test('penalty health loss is excluded from simulated combat impacts', () => {
  const data = {
    robots: [{ side: '红' }, { side: '蓝' }], events: [{ second: 2, type: '黄牌', robot: 0 }],
    frames: [[1, [row(0, 2, 200), row(1, 8, 200)]], [2, [row(0, 2, 180), row(1, 8, 200, 1, 1)]]],
  }
  assert.equal(deriveDamageEffects(data).length, 0)
})
