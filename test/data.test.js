import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { teamStrength } from '../src/domain.js'

const readJson = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'))

test('all published teams use complete score schema 3.0', () => {
  const index = readJson('../public/data/index.json')
  assert.equal(index.schema_version, '3.0.0')
  assert.equal(index.data_version, 'score-3.0.0')
  assert.equal(index.teams.length, 96)
  const dimensions = ['firepower', 'objective', 'spatial', 'defense', 'resource', 'adaptability']
  for (const listing of index.teams) {
    const team = readJson(`../public/data/teams/${listing.slug}.json`)
    assert.equal(team.schema_version, '3.0.0', listing.team)
    assert.equal(team.data_version, 'score-3.0.0', listing.team)
    assert.equal('consistency_analysis' in team, false, listing.team)
    for (const dimension of dimensions) {
      const detail = team[`${dimension}_analysis`]
      assert.equal(detail.version, '3.0.0', `${listing.team} ${dimension}`)
      const reconstructed = Object.entries(detail.weights)
        .reduce((total, [key, weight]) => total + detail.components[key] * weight, 0)
      assert.ok(Math.abs(reconstructed - team.scores[dimension]) < .12, `${listing.team} ${dimension}`)
    }
    assert.ok(Math.abs(teamStrength(team) - team.strength_analysis.score) < .15, listing.team)
    assert.equal(team.score_confidence.enters_score, false, listing.team)
  }
})
