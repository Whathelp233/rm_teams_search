# Design QA

- Source visual truth: `https://search.scutbot.cn/search?query=rm_search` and `/tmp/rm-search-reference-chromium.png`
- Implementation: `/tmp/rm-teams-after-chromium-v2.png`, `/tmp/rm-teams-after-firefox.png`, `/tmp/rm-teams-after-mobile-v2.png`
- Full comparison: `/tmp/rm-design-qa-comparison.png`
- Focused comparison: `/tmp/rm-design-qa-focused.png`
- Viewports: 1440×900 desktop and 390×844 mobile
- State: Guangdong University of Technology, team overview, comfortable density

## Findings

- No actionable P0, P1, or P2 findings remain.
- The reference site's light palette was intentionally replaced by the approved dark-only tactical theme. Its structural language is retained: sticky top navigation, narrow filter rail, restrained card grid, compact controls, subtle borders, and progressive disclosure.
- Typography uses the existing system/Noto Sans SC stack with clearer size and weight hierarchy. Numeric KPIs use tabular alignment and remain legible in both browsers.
- Spacing and layout rhythm match the reference proportions while supporting denser tactical data. Desktop cards align to a consistent grid; mobile cards collapse without horizontal page overflow.
- Colors and visual tokens are consistent across navigation, filters, cards, evidence states, and focus rings. Red/blue remain reserved for real team sides in map data.
- The field map remains the real competition-map raster. No visible source asset was replaced by CSS art, placeholder art, emoji, or an approximate map.
- Copy consistently distinguishes facts, inferred damage, score confidence, and probabilistic predictions.

## Comparison history

1. Initial mobile comparison found a P2 issue: radar-axis labels and long x-axis values were clipped at 390px.
2. The radar radius and mobile label sizing were reduced, and bar-axis values were compacted to `k` notation.
3. The revised 390×844 capture shows all six radar labels and the damage chart within the card boundary.

## Interaction and browser evidence

- Chrome and Firefox: default Guangdong overview, seven team tabs, role view, tournament view, lazy heatmap, and comparison flow tested.
- Mobile: filter drawer opens and closes; the document has no horizontal overflow.
- Browser console and page-error streams were empty across the primary flows.
- Focused comparison was used because navigation, filter density, KPI hierarchy, chart labels, and card spacing needed readable inspection beyond the full-page comparison.

## Follow-up polish

- P3: the horizontally scrollable team-tab row could gain a subtle edge fade on very narrow screens.
- P3: chart tooltips could later receive richer keyboard equivalents.

final result: passed
