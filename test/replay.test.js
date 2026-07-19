import test from 'node:test'
import assert from 'node:assert/strict'
import { activeDamageEffects, deriveDamageEffects, deriveShotEffects, interpolatedFrame, nativeFrameRate, normalizeReplayData, teamFrameAt } from '../src/replay.js'

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

test('shot effects preserve factual firing position and optional muzzle heading', () => {
  const data = { frames: [[2, [row(0, 2, 200, 1, 3), [1, 8, 5, 200, 200, 0, 0, 0, 0, 1, 1]]]] }
  const effects = deriveShotEffects(data)
  assert.deepEqual(effects, [
    { id: '2-0', second: 2, robot: 0, x: 2, y: 5, yaw: null, shots17: 3, shots42: 0 },
    { id: '2-1', second: 2, robot: 1, x: 8, y: 5, yaw: null, shots17: 0, shots42: 1 },
  ])
  assert.ok(effects.every(effect => !('target' in effect)))
})

test('v3 compact evidence expands without changing confidence or candidates', () => {
  const payload = normalizeReplayData({
    event_columns: ['second', 'type', 'team'], events: [[120, '装配成功', '红队']],
    damage_columns: ['id', 'second', 'confidence', 'candidates'],
    candidate_columns: ['robot_id', 'angle_error'],
    damage_effects: [['hit-1', 25, 'medium', [[103, 7.5]]]],
  })
  assert.deepEqual(payload.events[0], { second: 120, type: '装配成功', team: '红队' })
  assert.equal(payload.damage_effects[0].confidence, 'medium')
  assert.deepEqual(payload.damage_effects[0].candidates[0], { robot_id: 103, angle_error: 7.5 })
})

test('change-point team frames resolve the latest scoreboard state', () => {
  const frames = [[1, [['红', 100, 80]]], [20, [['红', 150, 40]]]]
  assert.deepEqual(teamFrameAt(frames, 19), [['红', 100, 80]])
  assert.deepEqual(teamFrameAt(frames, 20), [['红', 150, 40]])
})

test('penalty health loss is excluded from simulated combat impacts', () => {
  const data = {
    robots: [{ side: '红' }, { side: '蓝' }], events: [{ second: 2, type: '黄牌', robot: 0 }],
    frames: [[1, [row(0, 2, 200), row(1, 8, 200)]], [2, [row(0, 2, 180), row(1, 8, 200, 1, 1)]]],
  }
  assert.equal(deriveDamageEffects(data).length, 0)
})
