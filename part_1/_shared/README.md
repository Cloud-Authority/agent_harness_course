# Shared source of truth

Both builds import this directory. Do not fork its files into a build.

- `seed/catalogue.py` defines 60 stable Kata products and 1,029 variants.
- `seed/generate_seed_data.py` deterministically builds 5,000 customers, 40,000 orders
  and exactly 90,000 order lines at the fixed `2026-09-29` teaching snapshot.
- `seed/schema.sql` is the Oracle enterprise + harness schema.
- `fixtures/memory_fixtures.json` seeds semantic, episodic and procedural memory.
- `fixtures/notion_pages/` contains 12 complete institutional-knowledge pages.
- `runtime/` is the read-only business facade and comparable trace contract.
- `demo_script.md` is the canonical five-turn story.

The generator validates the four low-stock variants, open Berlin PO, product/variant
scale and transaction volumes. Its CSV export is the loading contract for Oracle and
the optional Mongo enterprise mirror.

```bash
python part_1/_shared/seed/generate_seed_data.py --force
python part_1/_shared/seed/generate_seed_data.py --target csv
python part_1/_shared/seed/generate_seed_data.py --validate-only
```
