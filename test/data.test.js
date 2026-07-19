import test from 'node:test'
import assert from 'node:assert/strict'
import { createReadStream, readFileSync, statSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { teamStrength } from '../src/domain.js'

const readJson = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'))

test('all published teams use complete score schema 3.9', () => {
  const index = readJson('../public/data/index.json')
  assert.equal(index.schema_version, '3.9.1')
  assert.equal(index.data_version, 'score-3.9.1')
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
    assert.equal(team.schema_version, '3.9.1', listing.team)
    assert.equal(team.data_version, 'score-3.9.1', listing.team)
    assert.equal('consistency_analysis' in team, false, listing.team)
    assert.equal(team.overall_rank, listing.overall_rank, listing.team)
    assert.deepEqual(team.strength_analysis.tactical_dimension_weights, tacticalWeights, listing.team)
    assert.equal(team.strength_analysis.victory_rule_alignment.direct_dimension_weight, .74, listing.team)
    assert.equal(team.strength_analysis.victory_rule_alignment.enabling_dimension_weight, .26, listing.team)
    assert.ok(team.overall_rank >= 1 && team.overall_rank <= 96, listing.team)
    if (team.placement) placementCounts[team.placement.label] = (placementCounts[team.placement.label] || 0) + 1
    for (const dimension of dimensions) {
      const detail = team[`${dimension}_analysis`]
      assert.equal(detail.version, '3.9.1', `${listing.team} ${dimension}`)
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

test('published role catalog covers every second and keeps dart as event data', () => {
  const catalog = readJson('../public/data/roles/index.json')
  assert.equal(catalog.schema_version, 'role-data-1.1.0')
  assert.equal(catalog.roles.length, 7)
  assert.equal(catalog.total_second_rows, 2990075)
  assert.equal(catalog.total_events, 1376165)
  assert.deepEqual(catalog.roles.map(role => role.role), ['英雄', '工程', '步兵3', '步兵4', '哨兵', '空中', '飞镖'])
  for (const role of catalog.roles) {
    const listing = readJson(`../public/data/roles/${role.role_slug}/index.json`)
    assert.equal(listing.schema_version, 'role-data-1.1.0')
    assert.equal(listing.teams.length, 96)
    assert.equal(listing.counts.rows, role.counts.rows)
    assert.equal(listing.counts.events, role.counts.events)
  }
  const teamIndex = readJson('../public/data/index.json')
  const guangdong = teamIndex.teams.find(team => team.team === '广东工业大学')
  const hero = readJson(`../public/data/roles/hero/teams/${guangdong.slug}.json`)
  assert.equal(hero.role, '英雄')
  assert.equal(hero.frame_columns.length, 17)
  assert.ok(hero.games.length > 0)
  assert.equal(hero.games[0].frames.length, hero.games[0].summary.tracked_seconds)
  assert.match(hero.limitations[0], /推定值/)
  assert.ok(hero.summary.estimated_damage_per_game > 0)
  assert.ok(hero.summary.estimated_damage_confidence_pct >= 90)
  assert.equal(hero.damage_estimate_columns.length, 8)
  assert.ok(hero.games.some(game => game.damage_estimates.length > 0))
  const engineer = readJson(`../public/data/roles/engineer/teams/${guangdong.slug}.json`)
  assert.equal(engineer.summary.shots_per_game, null)
  assert.equal(engineer.summary.estimated_damage_per_game, null)
  const dart = readJson(`../public/data/roles/dart/teams/${guangdong.slug}.json`)
  assert.equal(dart.mode, 'event')
  assert.equal('frames' in dart.games[0], false)
})

test('role download manifest sizes and sha256 checksums match generated archives', async () => {
  const manifest = readJson('../public/downloads/roles/manifest.json')
  assert.equal(manifest.schema_version, 'role-data-1.1.0')
  assert.equal(manifest.files.length, 14)
  for (const file of manifest.files) {
    const path = new URL(`../public/${file.path}`, import.meta.url)
    assert.equal(statSync(path).size, file.bytes, file.path)
    assert.deepEqual([...readFileSync(path).subarray(0, 2)], [0x1f, 0x8b], file.path)
    const digest = createHash('sha256')
    await new Promise((resolve, reject) => createReadStream(path).on('data', chunk => digest.update(chunk)).on('end', resolve).on('error', reject))
    assert.equal(digest.digest('hex'), file.sha256, file.path)
  }
})

test('tournament pickem rosters and official Swiss thresholds are internally consistent', () => {
  const pickem = readJson('../public/data/repechage.json')
  const index = readJson('../public/data/index.json')
  assert.equal(pickem.schema_version, 'tournament-pickem-3.0.0')
  assert.deepEqual(pickem.simulation.winner_modes, ['probability_random', 'favorite_path', 'manual'])
  assert.equal(pickem.simulation.monte_carlo_iterations, 2000)
  assert.equal(pickem.repechage.groups, 2)
  assert.equal(pickem.repechage.group_size, 8)
  assert.equal(pickem.repechage.swiss_rounds, 3)
  assert.equal(pickem.repechage.loss_target, 2)
  assert.equal(pickem.repechage.postseason.length, 1)
  assert.equal(pickem.repechage.teams.length, 16)
  assert.deepEqual(pickem.repechage.teams.reduce((counts, team) => ({ ...counts, [team.tier]: (counts[team.tier] || 0) + 1 }), {}), { 1: 8, 2: 8 })
  assert.equal(new Set(pickem.repechage.teams.map(team => team.team)).size, 16)
  for (const team of pickem.repechage.teams) {
    assert.ok(index.teams.some(listing => listing.team === team.team), team.team)
    assert.ok(team.battle_name.length > 0, team.team)
  }
  assert.equal(pickem.finals.groups, 2)
  assert.equal(pickem.finals.group_size, 16)
  assert.equal(pickem.finals.swiss_rounds, 5)
  assert.equal(pickem.finals.win_target, 3)
  assert.equal(pickem.finals.loss_target, 3)
  assert.equal(pickem.finals.postseason.length, 5)
  assert.equal(pickem.finals.teams.length, 32)
  assert.equal(pickem.finals.teams.filter(team => team.placeholder).length, 4)
  assert.equal(new Set(pickem.finals.teams.map(team => team.team)).size, 32)
  assert.deepEqual(pickem.finals.teams.reduce((counts, team) => ({ ...counts, [team.tier]: (counts[team.tier] || 0) + 1 }), {}), { 1: 3, 2: 3, 3: 3, 4: 3, 5: 4, 6: 16 })
  for (const team of pickem.finals.teams.filter(team => !team.placeholder)) {
    assert.ok(index.teams.some(listing => listing.team === team.team), team.team)
    assert.ok(team.battle_name.length > 0, team.team)
  }
})
