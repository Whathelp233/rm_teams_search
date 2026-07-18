import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, statSync } from 'node:fs'
import { buildCounterPlans, visibleTacticalPatterns } from '../src/tactics.js'

const pattern = {
  pattern_id: 'opening_outpost', phase: 'opening', label: '90秒内形成前哨首压',
  classification: '核心模式', confidence: '高', observed: 8, eligible: 10, opponents: 4, rate: .8,
  timing: { median: 32, p25: 18, p75: 54 }, evidence: [{ game_id: 1, opponent: '乙', side: '红', won: true }],
  association: { with_win_pct: 70, without_win_pct: 40, win_delta_pp: 30 },
  counter_response: { usable: true, games: 4, opponents: 3, early_forward_pct: 22, multi_push_seconds: 8, damage_per_game: 3000 },
}
const profile = (team, overrides = {}) => ({
  team, sample: { games: 12, opponents: 5 }, patterns: [pattern],
  capabilities: { mobility_score: 70, defense_score: 68, objective_score: 65, firepower_score: 66, resource_score: 60, base_denial_pct: 70, outpost_denial_pct: 65, early_forward_pct: 30, multi_push_seconds: 12, damage_per_game: 3800 },
  ...overrides,
})

test('counter plans are matchup-specific and reject the same team', () => {
  const target = profile('目标队')
  const executor = profile('我方队')
  const [plan] = buildCounterPlans(target, executor)
  assert.equal(plan.id, 'opening_outpost')
  assert.equal(plan.threat.observed, 8)
  assert.ok(plan.matchup.executorCapability > 0)
  assert.equal(buildCounterPlans(target, profile('目标队')).length, 0)
})

test('missing counterexample support explicitly degrades to a rule fallback', () => {
  const target = profile('目标队', { patterns: [{ ...pattern, counter_response: { usable: false, games: 1, opponents: 1 } }] })
  const [plan] = buildCounterPlans(target, profile('我方队'))
  assert.match(plan.confidence, /规则型备选/)
})

test('phase filter hides insufficient patterns unless requested', () => {
  const weak = { ...pattern, pattern_id: 'weak', classification: '样本不足' }
  const target = profile('目标队', { patterns: [pattern, weak] })
  assert.deepEqual(visibleTacticalPatterns(target, 'opening').map(item => item.pattern_id), ['opening_outpost'])
  assert.equal(visibleTacticalPatterns(target, 'opening', true).length, 2)
})

test('all generated tactical profiles are bounded and reference real team games', () => {
  const index = JSON.parse(readFileSync(new URL('../public/data/index.json', import.meta.url)))
  for (const listing of index.teams) {
    const path = new URL(`../public/data/v4/tactics/${listing.slug}.json`, import.meta.url)
    assert.ok(statSync(path).size <= 80 * 1024, `${listing.team} exceeds 80KB`)
    const tactical = JSON.parse(readFileSync(path))
    const detail = JSON.parse(readFileSync(new URL(`../public/data/teams/${listing.slug}.json`, import.meta.url)))
    const gameIds = new Set(detail.matches.map(match => match.game_id))
    assert.equal(tactical.schema_version, 'tactical-profile-1.0.0')
    assert.equal(tactical.team, listing.team)
    assert.equal(tactical.phases.length, 6)
    assert.equal(tactical.patterns.length, 17)
    for (const item of tactical.patterns) {
      assert.ok(item.observed <= item.eligible, `${listing.team}/${item.pattern_id}`)
      assert.ok(item.rate >= 0 && item.rate <= 1)
      assert.ok(item.interval80[0] <= item.rate && item.interval80[1] >= item.rate)
      const evidence = new Set(item.evidence.map(game => game.game_id))
      assert.ok(item.evidence.every(game => gameIds.has(game.game_id)))
      assert.ok(item.counterexamples.every(game => gameIds.has(game.game_id) && !evidence.has(game.game_id)))
    }
  }
})

