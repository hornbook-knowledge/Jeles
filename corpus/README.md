# Knowledge corpus seed

Structured research JSON files that feed the jeles verified-corpus store.
Each file contains pairs (claim + explanation), evidence (source URLs),
and edges (cross-domain relationships).

## Scale

- 87 source files across ~40 domains
- **1223** raw pair-shaped entries in the JSON (85 files carry a `pairs` list;
  2 are plain lists of adversarial *challenge* records, not pair sets),
  composing to **1163** question/answer nuggets — 835 commons (verified, credited to the public record they cite, unsealed) + 328 asserted.
  The remaining 36 entries share the `pairs` key without the question/answer
  shape (reasoning about the corpus rounds, not claims in it) and compose to
  nothing. Measured 2026-10-19 with `jeles-seed --dry-run`; see
  `tests/test_corpus_counts.py`.
- 2105 evidence entries with real source URLs
- The `core_*` files are the reference shelf: general knowledge written as
  library cards, each a short settled answer plus one or two pointers to
  where the full account lives (Britannica, Wikipedia, NASA, NIH, USGS, the
  Library of Congress and similar). Ten cover how everyday things work; the
  rest cover mathematics, astronomy, life science, the human body, world
  geography, ecology and earth systems, world history, government and civics,
  language and writing, libraries and literature, the arts and music, beliefs
  and philosophy, and a general reference shelf.
- 3 rounds of adversarial verification (fact-check, steel-man, contradiction challenge)

## Load into a jeles store

```bash
pip install -e .
python corpus/compose.py --origin-prefix=seed corpus/seed/*.json
```

This writes each pair as an `asserted` nugget (machine-proposed, not
human-verified). The compose script requires `jeles.corpus` to be
importable.

## Domains covered

| Category | Domains |
|----------|---------|
| Core science | Forces, heat/light/sound, electricity, materials, food/body, weather, measurement, money, transportation, digital |
| AI research | RAG, agent memory, KG grounding, distillation, multi-agent |
| Modern infrastructure | Internet, energy, food systems, healthcare, cities |
| People (contemporary) | AI pioneers, tech power, ethics/safety, scandals, open source, scientists, whistleblowers, infrastructure, media, rights |
| People (historical) | Scientists, political power, liberation, thinkers, artists |
| Economics, law, environment, education, war | R8 batch |
| Media, health, labor | R9 batch |
| Cross-domain wiring | Power-accountability, ethics-creation, credit-erasure, infrastructure-control, and more |
| Adversarial passes | Fact-check, steel-man, contradiction challenge (3 rounds) |

## Provenance

All entries are `asserted` (machine-proposed from public sources). None
are `human`-verified. The adversarial passes correct factual errors and
surface contradictions, but they are machine-generated corrections of
machine-generated claims.
