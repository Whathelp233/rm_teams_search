function median(values) {
  if (!values.length) return 1
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

export function nativeFrameRate(frames = []) {
  const deltas = []
  for (let index = 1; index < frames.length; index += 1) {
    const delta = Number(frames[index][0]) - Number(frames[index - 1][0])
    if (delta > 0) deltas.push(delta)
  }
  return deltas.length ? 1 / median(deltas) : 1
}

function frameBounds(frames, time) {
  if (!frames.length) return [null, null]
  let low = 0, high = frames.length - 1
  while (low <= high) {
    const middle = (low + high) >> 1
    if (frames[middle][0] <= time) low = middle + 1
    else high = middle - 1
  }
  const previous = frames[Math.max(0, high)]
  return [previous, frames[Math.min(frames.length - 1, high + 1)]]
}

export function interpolatedFrame(frames = [], time = 0) {
  const [previous, next] = frameBounds(frames, time)
  if (!previous) return []
  if (!next || next === previous || next[0] <= previous[0]) return previous[1]
  const ratio = Math.max(0, Math.min(1, (time - previous[0]) / (next[0] - previous[0])))
  const nextRows = new Map(next[1].map(row => [row[0], row]))
  return previous[1].map(row => {
    const following = nextRows.get(row[0])
    if (!following || !row[10] || !following[10]) return row
    const distance = Math.hypot(following[1] - row[1], following[2] - row[2])
    if (distance > 6) return row
    const result = [...row]
    result[1] = row[1] + (following[1] - row[1]) * ratio
    result[2] = row[2] + (following[2] - row[2]) * ratio
    return result
  })
}

function penaltyRobots(events = []) {
  const result = new Set()
  for (const event of events) {
    if (!String(event.type || '').includes('牌') || event.robot === undefined) continue
    result.add(`${Math.round(Number(event.second))}:${event.robot}`)
  }
  return result
}

export function deriveDamageEffects(gameData) {
  const frames = gameData?.frames || [], robots = gameData?.robots || [], penalties = penaltyRobots(gameData?.events)
  const effects = []
  for (let index = 1; index < frames.length; index += 1) {
    const [second, rows] = frames[index], previousRows = new Map(frames[index - 1][1].map(row => [row[0], row]))
    const currentRows = new Map(rows.map(row => [row[0], row]))
    for (const row of rows) {
      const previous = previousRows.get(row[0]), damage = previous ? Number(previous[3]) - Number(row[3]) : 0
      if (!previous || damage <= 0 || penalties.has(`${Math.round(second)}:${row[0]}`)) continue
      const targetSide = robots[row[0]]?.side
      const candidates = rows.filter(candidate => robots[candidate[0]]?.side !== targetSide && candidate[10] && (candidate[8] > 0 || candidate[9] > 0))
        .sort((a, b) => Math.hypot(a[1] - row[1], a[2] - row[2]) - Math.hypot(b[1] - row[1], b[2] - row[2]))
      const position = row[10] ? row : previous[10] ? previous : null
      if (!position) continue
      const confidence = row[10] && candidates.length === 1 ? 'high' : row[10] ? 'medium' : 'low'
      const source = candidates[0]
      effects.push({
        id: `${second}-${row[0]}`, second: Number(second), target: row[0], damage: Math.round(damage),
        x: position[1], y: position[2], source: source ? { robot: source[0], x: source[1], y: source[2] } : null,
        confidence,
        basis: confidence === 'high' ? '血量下降且同秒仅一台敌方单位发弹' : confidence === 'medium' ? '血量下降已确认，伤害来源存在歧义' : '血量下降已确认，位置沿用上一有效帧',
      })
    }
  }
  return effects
}

export function activeDamageEffects(effects = [], time = 0, lifetime = .9) {
  return effects.filter(effect => time >= effect.second && time < effect.second + lifetime)
}
