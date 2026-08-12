# Restock playbook

The purpose of a restock alert is to surface an unhandled decision, not every low stock
row. Start with the planner's saved threshold; Alex Moreau uses two weeks of cover.
Apply the trailing GBP 5,000 revenue floor before ranking. Scope to owned categories and
regions, and check open purchase orders and recent decisions before creating an alert.

Core products should normally be replenished when cover will fall below the threshold
before the supplier can deliver. Seasonal products require a second test: only reorder
when there are at least six full-price trading weeks before the regional exit date.
Otherwise prepare a transfer or markdown recommendation. Never count in-transit units
as on-hand, but show both in the recommendation.

Recommendation format is fixed: SKU and variant; location; current cover; four-week
rate of sale; supplier lead time and reliability; recommended quantity; concise
rationale. Round quantities up to the supplier minimum-order multiple. Flag a size-curve
problem separately when aggregate cover hides an M/L shortage or tail-size overhang.

An item is already handled when an open PO covers the shortage, a stock transfer is
booked, or the planner recorded a hold. Put it under “open actions” only if its state has
materially changed: the PO is late, demand rose more than 25%, or projected cover falls
below one week before arrival. The Berlin ThermaCore M shortage has PO
`PO-BER-THC-OPEN`; it must not appear as a new restock alert.

Escalate when projected lost sales exceed GBP 10,000, supplier reliability is below
0.90, or a core hero size will be unavailable for more than seven days. The planner,
not ERPA, approves every purchase order.
