# Storey splits, counted (rl-21)

`world.metrics["storey_splits"]` counts how each storey band partition split
(rl-16's size-first split): a split the dynamic program seated (`dp used`),
ranked splits that all missed and fell back to equal tiles (`dp missed`), and
families with no size catalogue to split by at all (`no catalogue` — a
composed-only family, noted on the building). Every world below is built with
the room assembler on at seed 1, PYTHONHASHSEED=0.

The fixture worlds the suite builds are listed whole: the raw fixtures carry
no `use` keys, so the assembler stays inert on them (nothing assembled, no
partition); only `ashvale-compound` with its tests' `ASHVALE_USES` uses and
the recipe compounds exercise it.

| world | assembled (cache) | partitions | dp used | dp missed | no catalogue | no width fit | catalogue notes |
|---|---|---|---|---|---|---|---|
| village_plan() | 30 | 76 | 22 | 0 | 3 | 51 | 1 |
| farm_plan() | 7 | 2 | 0 | 0 | 0 | 2 | 0 |
| ashvale-compound+uses | 17 | 29 | 0 | 0 | 0 | 29 | 0 |
| apartment-block.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ashvale-compound.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ashvale-framed.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| cyberpunk-framed.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hospital-spine.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| modern-quarter.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ship-void.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| shop-strip.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| starship-decks.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zombie-town.plan.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Reading it:

- **Partitions** counts every band the split was attempted on in the build
  that shipped (growth re-runs restart the count; a discarded entrance side's
  partitions count, its notes do not ship — hence 3 catalogues empty but one
  note: "no size catalogue for barracks" on Stable Range's storey 2).
- **dp missed** never fired: no ranked split has ever had to roll back
  through `_SplitMiss` in these worlds.
- **no width fit** is not one of the metric's three buckets; it is measured
  here for the report alone: the family's catalogue had sizes, but none could
  door onto the corridor at that band's depth, so the band kept its equal
  tiles by design (`_spec_widths` returns nothing that fits). It is the
  common outcome wherever the split was attempted and not seated.
- The determinism hashes of all four hashed worlds are unchanged by the
  counting (build_spec carries no metrics; the note lines reach metrics.json
  only).
