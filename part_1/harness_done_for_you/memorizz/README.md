# MemoRizz assistant harness

The [`assistant/`](assistant/) directory contains the complete ERPA assistant notebook
and interactive appbook. It demonstrates MemoRizz with Oracle AI Database, Toolbox,
Skillbox, E2B, MCP, semantic caching, context engineering, durable human approval,
delegation, shared memory, and observability.

```bash
cd assistant/appbook
./run.sh

# From the repository root, verify persistence across separate processes:
python part_1/scripts/restart_proof.py --build memorizz
```
