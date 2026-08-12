"""Stable Kata catalogue definitions shared by both ERPA builds.

The catalogue is deliberately data, not a random generator.  Both harnesses therefore
talk about the same SKU names even when their storage adapters differ.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
REGIONS = ["JP", "UK", "US", "EU", "SEA"]


@dataclass(frozen=True)
class ProductLine:
    code: str
    name: str
    category: str
    fabric: str
    is_core: bool
    base_price: float
    unit_cost: float
    colours: tuple[str, ...]
    styles: tuple[str, ...]


PRODUCT_LINES = (
    ProductLine("THC", "ThermaCore", "Outerwear", "recycled down", False, 129.90, 41.00,
                ("Black", "Navy", "Olive"), ("Jacket", "Vest", "Long Coat", "Light Jacket", "Hooded Coat", "Parka")),
    ProductLine("WML", "WarmLayer", "Innerwear", "thermal knit", True, 19.90, 4.80,
                ("Black", "White", "Grey"), ("Crew", "V Neck", "Turtle", "Legging", "Long Sleeve", "Extra Warm")),
    ProductLine("ARL", "AirLight", "Innerwear", "breathable mesh", True, 14.90, 3.40,
                ("White", "Black", "Beige"), ("Crew", "V Neck", "Tank", "Camisole", "Brief", "Long Sleeve")),
    ProductLine("PCT", "PureCotton", "Tops", "supima cotton", True, 14.90, 3.10,
                ("White", "Black", "Navy"), ("Crew Tee", "Relaxed Tee", "Polo", "Long Sleeve", "Oxford", "Henley")),
    ProductLine("TDN", "TrueDenim", "Bottoms", "selvedge denim", True, 49.90, 15.20,
                ("Indigo", "Black", "Stone Wash"), ("Slim", "Straight", "Wide", "Relaxed", "Cropped", "Utility")),
    ProductLine("SLG", "SoftLounge", "Loungewear", "brushed jersey", False, 34.90, 9.60,
                ("Grey", "Navy", "Charcoal"), ("Jogger", "Hoodie", "Crew", "Short", "Robe", "Set")),
    ProductLine("FSH", "FieldShell", "Outerwear", "coated ripstop", False, 89.90, 27.50,
                ("Black", "Khaki", "Slate"), ("Jacket", "Parka", "Anorak", "Vest", "Long Coat", "Packable")),
    ProductLine("DKN", "DailyKnit", "Tops", "merino blend", False, 39.90, 12.10,
                ("Camel", "Charcoal", "Cream"), ("Crew", "V Neck", "Cardigan", "Polo", "Vest", "Turtle")),
    ProductLine("ETR", "EaseTrouser", "Bottoms", "stretch twill", True, 39.90, 11.40,
                ("Black", "Navy", "Taupe"), ("Slim", "Straight", "Wide", "Cropped", "Pleated", "Cargo")),
    ProductLine("CAL", "CarryAll", "Accessories", "recycled nylon", True, 24.90, 6.20,
                ("Black", "Olive"), ("Mini Bag", "Tote", "Backpack", "Sling", "Pouch", "Weekender")),
)


def iter_products() -> Iterator[dict]:
    """Yield exactly 60 products and roughly 1,100 apparel variants."""
    for line in PRODUCT_LINES:
        for index, style in enumerate(line.styles, start=1):
            # Alternate two and three colours: 60 × 2.5 × 7 = 1,050 variants.
            colours = line.colours[: 2 + (index % 2)]
            yield {
                "sku": f"KTA-{line.code}-{index:02d}",
                "name": f"{line.name} {style}",
                "line": line.name,
                "category": line.category,
                "collection": line.name,
                "season": "CORE" if line.is_core else ("AW26" if line.category == "Outerwear" else "SS26"),
                "base_price": line.base_price + (index - 1) * 3,
                "unit_cost": line.unit_cost + (index - 1) * 0.9,
                "fabric": line.fabric,
                "is_core": int(line.is_core),
                "colours": colours,
            }


def variant_id(sku: str, colour: str, size: str) -> str:
    return f"{sku}-{colour[:3].upper().replace(' ', '')}-{size}"
