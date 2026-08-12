# ERPA demo script — canonical

Five turns. Identical in both builds. Each proves exactly one thing.

| # | Turn | Proves |
|---|---|---|
| 1 | *"Morning brief."* | Personalised by memory: only owned categories/regions, above the revenue floor, stored format. Flags 3 restock items — **and suppresses Berlin ThermaCore, because a PO is already open.** |
| 2 | *"Why did WarmLayer spike in the UK last week?"* | Internal data + **Tavily** (cold snap) + Notion seasonal notes. Three sources, one grounded answer. |
| 3 | *"Show me ThermaCore stock across regions."* | **Sandbox** renders a chart; surfaces the M/L sell-out against XS/XXL overhang. |
| 4 | *"Which regions are most profitable this quarter — and stop showing me Accessories."* | Margin (not revenue) computed via the semantic layer; the exclusion is **written to memory**. |
| 5 | **Restart the process**, then *"Morning brief."* | **The money shot.** Accessories gone, Berlin still suppressed, preferences intact. Persistence, not session state. |

Optional 6th (Build B only): repeat turn 2 → **semantic cache** hit, no model span in the
trace, visible latency and token delta.

## Planted data conditions (required by the script)

1. 3–4 variants below reorder point right now
2. One of them (**Berlin ThermaCore**) already has an open PO → the *already-handled* case
3. A size-curve failure: M/L sold out while XS/XXL sit
4. A region with good volume but poor margin (over-discounting)
5. One product with an abnormal return rate (sizing issue)
6. A demand spike in the last 10 days with **no internal explanation** → the Tavily hook
