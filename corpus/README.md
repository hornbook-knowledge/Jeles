# Knowledge corpus seed

Structured research JSON files that feed the jeles verified-corpus store.
Each file contains pairs (claim + explanation), evidence (source URLs),
and edges (cross-domain relationships).

## Scale

- 74 source files across ~30 domains
- 1369 pairs when composed
- 2105 evidence entries with real source URLs
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
