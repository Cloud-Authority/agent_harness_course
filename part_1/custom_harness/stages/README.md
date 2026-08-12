# Custom ERPA — six independently runnable stages

Run any stage from the course root; each initialises only what it needs and is safe to
repeat. Local mode needs no credentials.

```bash
python part_1/custom_harness/stages/stage_01_single_turn.py
python part_1/custom_harness/stages/stage_02_memory.py
python part_1/custom_harness/stages/stage_03_semantic_layer.py
python part_1/custom_harness/stages/stage_04_skills.py
python part_1/custom_harness/stages/stage_05_tools.py
python part_1/custom_harness/stages/stage_06_complete_harness.py
```

The files are intentionally small: open two adjacent stages in a diff to see exactly
which harness layer enters the system.
