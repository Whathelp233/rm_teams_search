import { gzipSync } from 'node:zlib'
import { readFileSync, readdirSync } from 'node:fs'

const root = new URL('../dist/', import.meta.url)
const html = readFileSync(new URL('index.html', root), 'utf8')
const entrySource = html.match(/<script[^>]+src="([^"]+\.js)"/)?.[1]
const entryPath = entrySource?.includes('/assets/') ? `assets/${entrySource.split('/assets/')[1]}` : entrySource?.replace(/^\.\//, '').replace(/^\//, '')
if (!entryPath) throw new Error('unable to find production entry script')

const gzipBytes = path => gzipSync(readFileSync(new URL(path, root))).byteLength
const entryGzip = gzipBytes(entryPath)
const cssSource = html.match(/href="([^"]+\.css)"/)?.[1]
const cssPath = cssSource?.includes('/assets/') ? `assets/${cssSource.split('/assets/')[1]}` : cssSource?.replace(/^\.\//, '').replace(/^\//, '')
const cssGzip = cssPath ? gzipBytes(cssPath) : 0
const catalog = JSON.parse(readFileSync(new URL('data/v4/catalog.json', root), 'utf8'))
const defaultTeam = catalog.teams.find(team => team.team === '广东工业大学') || catalog.teams[0]
const dataGzip = gzipBytes('data/v4/catalog.json') + gzipBytes(`data/v4/teams/${defaultTeam.slug}/overview.json`)
const maps = readdirSync(new URL('assets/', root)).filter(file => file.endsWith('.map'))

const limits = { entry: 150 * 1024, css: 15 * 1024, initialData: 80 * 1024 }
if (entryGzip > limits.entry) throw new Error(`entry JS ${entryGzip} exceeds ${limits.entry} gzip bytes`)
if (cssGzip > limits.css) throw new Error(`CSS ${cssGzip} exceeds ${limits.css} gzip bytes`)
if (dataGzip > limits.initialData) throw new Error(`initial data ${dataGzip} exceeds ${limits.initialData} gzip bytes`)
if (maps.length) throw new Error(`production source maps must be disabled: ${maps.join(', ')}`)

console.log(JSON.stringify({ entry_js_gzip_kb: +(entryGzip / 1024).toFixed(1), css_gzip_kb: +(cssGzip / 1024).toFixed(1), initial_data_gzip_kb: +(dataGzip / 1024).toFixed(1), source_maps: maps.length }, null, 2))
