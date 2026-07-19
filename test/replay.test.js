import test from 'node:test'
import assert from 'node:assert/strict'
import { activeDamageEffects, deriveDamageEffects, interpolatedFrame, nativeFrameRate } from '../src/replay.js'

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
  assert.equal(activeDamageEffects(effects, 2.4).length, 1)
  assert.equal(activeDamageEffects(effects, 3).length, 0)
})

test('penalty health loss is excluded from simulated combat impacts', () => {
  const data = {
    robots: [{ side: '红' }, { side: '蓝' }], events: [{ second: 2, type: '黄牌', robot: 0 }],
    frames: [[1, [row(0, 2, 200), row(1, 8, 200)]], [2, [row(0, 2, 180), row(1, 8, 200, 1, 1)]]],
  }
  assert.equal(deriveDamageEffects(data).length, 0)
})
