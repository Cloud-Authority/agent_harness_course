# Kata merchandising glossary

This is the canonical vocabulary used in trading reviews and in the ERPA semantic
layer. Metric labels must link to the definitions below; do not invent a calculation
from the wording of a question.

**Cover weeks** is available stock divided by average weekly units over the trailing
four complete weeks: `(on_hand - reserved) / (units_28d / 4)`. Show `>52` when there
were no sales rather than dividing by zero. In-transit stock is reported separately and
is never counted as available cover.

**Sell-through (ST%)** is units sold divided by units received during the requested
window. Returns reduce units sold. Always state the window. **Size curve** is each
size's share of units within a product/colour. Compare actual demand with the regional
target curve; a product may have adequate total stock and still have a broken curve.

**Net revenue** is `qty × unit_price × (1 - discount)` less returned value. **Gross
margin** is net revenue less `qty × unit_cost`. **Gross margin percent** divides gross
margin by net revenue. **GMROI** divides trailing-12-month gross margin by average
inventory cost. “Most profitable” means gross margin value unless the question
explicitly asks for rate or GMROI.

**Core** products replenish throughout the year. **Seasonal** products normally mark
down rather than replenish after the final regional intake. **Actioned** means an owner
has raised a PO, approved a markdown, or logged a dated decision. ERPA must suppress
actioned items from attention lists while continuing to show them under open actions.

Common aliases: `cover` → cover weeks; `ST%` → sell-through; `margin` → gross margin;
`ROS` → rate of sale; `WOS` → weeks of supply. Currency is shown in the trading
region's currency; consolidated course examples use GBP-equivalent values.
