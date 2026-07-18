import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { teamStrength } from '../src/domain.js'

const readJson = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'))

test('all published teams use complete score schema 3.9', () => {
  const index = readJson('../public/data/index.json')
  assert.equal(index.schema_version, '3.9.0')
  assert.equal(index.data_version, 'score-3.9.0')
  assert.equal(index.teams.length, 96)
  const dimensions = ['firepower', 'objective', 'spatial', 'defense', 'resource', 'adaptability']
  const tacticalWeights = { firepower: .15, objective: .50, spatial: .11, defense: .09, resource: .14, adaptability: .01 }
  const componentWeights = {
    firepower: { clean_output: .35, accuracy: .15, kill_conversion: .25, pressure_uptime: .25 },
    objective: { outpost_pressure: .10, outpost_conversion: .25, base_pressure: .15, base_conversion: .35, strategic_tools: .15 },
    spatial: { relative_territory: .25, forward_presence: .30, neutral_control: .35, field_coverage: .10 },
    defense: { trade_resilience: .35, mobile_resilience: .25, outpost_denial: .15, base_denial: .15, collapse_resistance: .10 },
    resource: { acquisition: .40, utilization: .05, combat_conversion: .10, objective_conversion: .25, thermal_efficiency: .20 },
    adaptability: { side_transfer: .10, opponent_robustness: .10, strong_opponent_residual: .20, setback_adjustment: .30, rematch_adjustment: .30 },
  }
  const placementCounts = {}
  for (const listing of index.teams) {
    const team = readJson(`../public/data/teams/${listing.slug}.json`)
    assert.equal(team.schema_version, '3.9.0', listing.team)
    assert.equal(team.data_version, 'score-3.9.0', listing.team)
    assert.equal('consistency_analysis' in team, false, listing.team)
    assert.equal(team.overall_rank, listing.overall_rank, listing.team)
    assert.deepEqual(team.strength_analysis.tactical_dimension_weights, tacticalWeights, listing.team)
    assert.equal(team.strength_analysis.victory_rule_alignment.direct_dimension_weight, .74, listing.team)
    assert.equal(team.strength_analysis.victory_rule_alignment.enabling_dimension_weight, .26, listing.team)
    assert.ok(team.overall_rank >= 1 && team.overall_rank <= 96, listing.team)
    if (team.placement) placementCounts[team.placement.label] = (placementCounts[team.placement.label] || 0) + 1
    for (const dimension of dimensions) {
      const detail = team[`${dimension}_analysis`]
      assert.equal(detail.version, '3.9.0', `${listing.team} ${dimension}`)
      assert.deepEqual(detail.weights, componentWeights[dimension], `${listing.team} ${dimension} weights`)
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
    assert.equal(team.opponent_score_analysis.enters_strength, false, listing.team)
    assert.equal(team.opponent_score_analysis.direct_matches_excluded, true, listing.team)
    assert.equal(team.opponent_score_analysis.strength_coefficient, 0, listing.team)
    assert.ok(team.opponent_score_analysis.score >= 0 && team.opponent_score_analysis.score <= 100, listing.team)
    assert.equal(team.opponent_score_analysis.rank, listing.opponent_score_analysis.rank, listing.team)
    assert.equal(team.opponent_score_analysis.region_rank, listing.opponent_score_analysis.region_rank, listing.team)
    assert.ok(team.opponent_score_analysis.region_rank >= 1 && team.opponent_score_analysis.region_rank <= team.opponent_score_analysis.region_size, listing.team)
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

test('transparent opponent score excludes direct meetings and reconstructs its two-level formula', () => {
  const index = readJson('../public/data/index.json')
  const teams = index.teams.map(listing => readJson(`../public/data/teams/${listing.slug}.json`))
  const byName = new Map(teams.map(team => [team.team, team]))
  const firstOrder = new Map()
  for (const team of teams) {
    const opponents = [...new Set(team.matches.map(match => match.opponent))].filter(name => byName.has(name))
    const rates = opponents.map(name => {
      const otherMatches = byName.get(name).matches.filter(match => match.opponent !== team.team)
      return (otherMatches.filter(match => Boolean(match.won)).length + 1) / (otherMatches.length + 2)
    })
    firstOrder.set(team.team, rates.length ? rates.reduce((sum, value) => sum + value, 0) / rates.length : .5)
  }
  for (const team of teams) {
    const opponents = [...new Set(team.matches.map(match => match.opponent))].filter(name => byName.has(name))
    const secondOrder = opponents.length
      ? opponents.reduce((sum, name) => sum + firstOrder.get(name), 0) / opponents.length
      : .5
    const raw = 100 * (.75 * firstOrder.get(team.team) + .25 * secondOrder)
    const expected = 50 + (raw - 50) * opponents.length / (opponents.length + 3)
    assert.ok(Math.abs(expected - team.opponent_score_analysis.score) < .06, team.team)
  }
})
