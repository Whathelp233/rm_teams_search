import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { teamStrength } from '../src/domain.js'

const readJson = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'))

test('all published teams use complete score schema 3.7', () => {
  const index = readJson('../public/data/index.json')
  assert.equal(index.schema_version, '3.7.0')
  assert.equal(index.data_version, 'score-3.7.0')
  assert.equal(index.teams.length, 96)
  const dimensions = ['firepower', 'objective', 'spatial', 'defense', 'resource', 'adaptability']
  const tacticalWeights = { firepower: .18, objective: .32, spatial: .14, defense: .14, resource: .17, adaptability: .05 }
  const placementCounts = {}
  for (const listing of index.teams) {
    const team = readJson(`../public/data/teams/${listing.slug}.json`)
    assert.equal(team.schema_version, '3.7.0', listing.team)
    assert.equal(team.data_version, 'score-3.7.0', listing.team)
    assert.equal('consistency_analysis' in team, false, listing.team)
    assert.equal(team.overall_rank, listing.overall_rank, listing.team)
    assert.deepEqual(team.strength_analysis.tactical_dimension_weights, tacticalWeights, listing.team)
    assert.ok(team.overall_rank >= 1 && team.overall_rank <= 96, listing.team)
    if (team.placement) placementCounts[team.placement.label] = (placementCounts[team.placement.label] || 0) + 1
    for (const dimension of dimensions) {
      const detail = team[`${dimension}_analysis`]
      assert.equal(detail.version, '3.7.0', `${listing.team} ${dimension}`)
      assert.ok(team.dimension_ranks[dimension] >= 1 && team.dimension_ranks[dimension] <= 96, `${listing.team} ${dimension} rank`)
      assert.equal(team.dimension_ranks[dimension], listing.dimension_ranks[dimension], `${listing.team} ${dimension} listing rank`)
      assert.equal(team.dimension_confidence[dimension], listing.dimension_confidence[dimension], `${listing.team} ${dimension} listing evidence`)
      const evidence = Object.entries(detail.weights).reduce((total, [key, weight]) => {
        const samples = detail.component_samples[key]
        return total + weight * samples / (samples + 6)
      }, 0) * 100
      assert.ok(Math.abs(evidence - team.dimension_confidence[dimension]) < .06, `${listing.team} ${dimension} evidence`)
      const reconstructed = Object.entries(detail.weights)
        .reduce((total, [key, weight]) => total + detail.components[key] * weight, 0)
      assert.ok(Math.abs(reconstructed - team.scores[dimension]) < .12, `${listing.team} ${dimension}`)
    }
    assert.ok(Math.abs(teamStrength(team) - team.strength_analysis.score) < .15, listing.team)
    assert.equal(team.score_confidence.enters_score, false, listing.team)
  }
  assert.deepEqual(placementCounts, { '冠军': 3, '16强': 24, '八强': 12, '季军': 3, '亚军': 3, '殿军': 3 })
  assert.deepEqual(index.teams.filter(team => team.placement?.label === '冠军').map(team => team.team).sort(),
    ['东北大学', '中国石油大学（华东）', '华南农业大学'])
})

test('defense is bounded and adaptability is condition-based rather than a result clone', () => {
  const index = readJson('../public/data/index.json')
  const teams = index.teams.map(listing => readJson(`../public/data/teams/${listing.slug}.json`))
  const defense = teams.map(team => team.scores.defense)
  assert.ok(Math.max(...defense) - Math.min(...defense) < 40)
  for (const team of teams) {
    assert.deepEqual(Object.keys(team.defense_analysis.weights), ['trade_resilience', 'mobile_resilience', 'outpost_denial', 'base_denial', 'collapse_resistance'])
    assert.deepEqual(Object.keys(team.adaptability_analysis.weights), ['side_transfer', 'opponent_robustness', 'strong_opponent_residual', 'setback_adjustment', 'rematch_adjustment'])
  }
})
