# FFXIV Crafting Profit Scanner — Design Specification

## Purpose

A Python CLI tool that scans the FFXIV market board (via Universalis API) to find items where crafting from components is significantly cheaper than buying the finished product. Targets the same pattern discovered manually with submersible parts: low-volume, high-margin items whose components are either NPC-purchasable, gatherable, or cheap on the market board.

## Target User Context

- Player on EU data centers (user plays on Louisoix server)
- Has all crafters leveled, all master recipe books
- Has access to FC workshop (submersible/airship parts, housing walls, etc.)
- Gathers own materials (miner, botanist)
- Can world-visit within DC for cheapest prices
- Interested in margins of 100%+ on items with at least 1-2 sales/day

---

## Data Sources

### 1. Universalis API (market prices + sales velocity)

**Base URL:** `https://universalis.app/api/v2`

**Key endpoints:**

```
# Current listings + recent history for an item on a DC
GET /api/v2/{worldDcRegion}/{itemIds}
  ?listings=5          # number of listings to return
  &entries=10          # number of recent sales to return
  &hq=nq              # filter NQ only (most relevant for FC craft items)

# Batch: up to 100 item IDs comma-separated
GET /api/v2/Chaos/5530,5060,12913
```

**Useful response fields:**
- `listings[].pricePerUnit` — current asking prices
- `recentHistory[].pricePerUnit` — actual sale prices
- `recentHistory[].timestamp` — when it sold (unix timestamp)
- `currentAveragePrice` — average of current listings
- `averagePrice` — average of recent sales
- `regularSaleVelocity` — sales per day (NQ)
- `nqSaleVelocity` — same, explicitly NQ

**Rate limits:** Universalis asks for reasonable use. Add 100-200ms delay between requests. Batch requests where possible (up to 100 items per call).

### 2. Garland Tools API (recipe data + item metadata)

**Base URL:** `https://garlandtools.org/db`

```
# Single item data (includes recipe, ingredients, category, etc.)
GET /doc/item/en/3/{itemId}.json

# Search by name
GET /doc/browse/en/2/item.json?text=Whale-class
```

**Key response structure for recipe items:**
```json
{
  "item": {
    "id": 22527,
    "name": "Whale-class Bridge",
    "category": 56,
    "price": 0,           // NPC buy price (0 = not NPC sold)
    "sell_price": 24,     // NPC sell-to price
    "craft": [{
      "id": 22527,
      "job": 10,          // CRP=8, BSM=9, ARM=10, GSM=11, LTW=12, WVR=13, ALC=14, CUL=15
      "rlvl": 160,
      "ingredients": [
        {"id": 5093, "amount": 60},  // Steel Rivets x60
        {"id": 5058, "amount": 30},  // Steel Ingot x30
        // ... etc
      ]
    }]
  }
}
```

**Ingredient items also have `price` field** — if nonzero, that's the NPC vendor price. This is critical for calculating true crafting cost.

### 3. FFXIV Teamcraft / XIVAPI (alternative/supplementary)

Teamcraft has a public API but is less documented. XIVAPI (`https://xivapi.com`) is another option for item/recipe data. Garland Tools is recommended as primary because its data model nests recipes with ingredients cleanly.

---

## Algorithm

### Phase 1: Build candidate item list

Start with known high-margin categories, then expand:

**Priority categories (Garland Tools category IDs to verify):**
- FC Workshop crafts: Submersible parts, Airship parts
- FC Workshop crafts: Housing exterior walls (Large/Medium/Small Arms Supplier's Walls, Outfitter's Walls, Eatery Walls, etc.)
- Furnishings that require unusual crafting paths
- Intermediate crafting materials that are themselves tradeable (like Garlond Steel, Celestine)

**How to discover candidates programmatically:**
1. Query Universalis for items with `regularSaleVelocity` between 0.5 and 20 (low-medium volume — high-volume items tend to have efficient markets)
2. Filter to items that have a crafting recipe in Garland Tools
3. Filter out items with NPC vendor price > 0 (NPC-sold items rarely have crafting margins)
4. Filter out items where MB price is suspiciously high or low (< 1000 gil or > 50M gil) to avoid RMT noise and trivial items

Alternatively, a simpler bootstrapping approach:
1. Start from a **seed list** of known FC workshop items (submersible parts, airship parts, housing walls)
2. For each, fetch recipe → fetch ingredient prices → calculate margin
3. Also check if any *ingredients* are themselves profitable to craft (recursive margin check, 1 level deep)

### Phase 2: Price resolution for each candidate

For each candidate item and all its ingredients, resolve prices:

```python
def resolve_price(item_id, quantity):
    """
    Returns (price_per_unit, source) where source is one of:
    - "npc" (vendor price from Garland Tools)
    - "gc_seals" (GC quartermaster — needs manual mapping)
    - "gathered" (raw material, cost = 0 or shard cost only)
    - "mb" (market board price from Universalis)
    - "craft" (recursively calculated craft cost)
    """
```

**NPC price detection:** If Garland Tools `item.price > 0`, it's NPC-sold. Use that price.

**GC Seal items (needs a static mapping):**
```python
GC_SEAL_ITEMS = {
    5530: {"name": "Coke", "seals": 200},
    5261: {"name": "Aqueous Whetstone", "seals": 200},
    5339: {"name": "Potash", "seals": 200},
    5340: {"name": "Animal Fat", "seals": 200},
    # ... add others as discovered
}
```
For GC seal items, offer two cost modes: "free" (if user is seal-rich) or MB price.

**Gathered materials (needs a static mapping or heuristic):**
Raw ores, logs, herbs etc. can be flagged as "gathered = free" or costed at MB price. A simple heuristic: if the item has no recipe AND no NPC price AND MB price < 500 gil, it's probably a gathered material.

**Crystal/Shard/Cluster pricing:** Always pull from Universalis. These are the "real" cost of crafting when you gather everything else.

### Phase 3: Margin calculation

```python
finished_mb_price = universalis_avg_sale_price(item_id, dc="Chaos")
craft_cost = sum(resolve_price(ing_id, ing_qty) for ing_id, ing_qty in recipe.ingredients)

margin_absolute = finished_mb_price - craft_cost
margin_percent = (margin_absolute / craft_cost) * 100
profit_per_day = margin_absolute * sale_velocity
```

### Phase 4: Output

Sort by `profit_per_day` descending (or `margin_percent` — make it configurable).

Output format:
```
=== Whale-class Bridge (ID: 22527) ===
MB Price (avg sale):  1,501,500 gil
Craft Cost:             360,000 gil
Margin:               1,141,500 gil (317%)
Sales/day:                  1.5
Est. daily profit:    1,712,250 gil

Components:
  Steel Rivets      x60  @  313 ea (NPC)     = 18,780
  Steel Ingot       x30  @  258 ea (NPC)     =  7,740
  Cobalt Joint Plate x60 @ 1,400 ea (MB/craft) = 84,000
  ...
  
  [!] Cobalt Joint Plate is also craftable:
      Craft cost: ~800 ea vs MB 1,400 ea (43% savings)
```

---

## Implementation Notes

### Dependencies

```
pip install requests
```

No other dependencies needed. Pure stdlib + requests.

### Caching

Universalis data goes stale fast, but Garland Tools recipe data is essentially static between patches.

- **Cache Garland Tools responses** to `~/.ffxiv-scanner/garland/` as JSON files, indefinite TTL
- **Cache Universalis responses** to `~/.ffxiv-scanner/universalis/` with a 1-hour TTL
- Add `--no-cache` flag to force refresh

### Rate Limiting

- Universalis: max ~10 requests/second, prefer batching (100 items/request)
- Garland Tools: be polite, 200ms between requests

### CLI Interface

```bash
# Scan known FC workshop items on Chaos DC
python ffxiv_scanner.py --dc Chaos --category workshop

# Scan a specific item and its full recipe tree
python ffxiv_scanner.py --dc Chaos --item "Whale-class Bridge"
python ffxiv_scanner.py --dc Chaos --item-id 22527

# Scan with GC seal items costed as free
python ffxiv_scanner.py --dc Chaos --category workshop --gc-seals-free

# Scan with custom minimum margin
python ffxiv_scanner.py --dc Chaos --category workshop --min-margin 100

# Show cheapest world within DC for each component
python ffxiv_scanner.py --dc Chaos --item-id 22527 --show-worlds
```

### Seed Item Lists

Since discovering all profitable items programmatically is hard without a full item database, include curated seed lists:

```python
WORKSHOP_ITEMS = {
    # Submersible parts (Whale-class as example, expand to all classes)
    "whale_sub": [22527, 22528, 22529, 22530],  # Bridge, Bow, Hull, Stern
    # ... Shark-class, Unkiu-class, Coelacanth-class, Syldra-class, etc.
    
    # Airship parts
    "airship": [...]  # Enterprise, Invincible, Invincible II, Odyssey, etc.
    
    # Housing walls
    "housing_walls": [...]  # Arms Supplier, Eatery, Outfitter walls (S/M/L)
    
    # Other workshop items
    "workshop_misc": [...]  # Aetherial Wheel Stands, etc.
}
```

**To populate these lists:** query Garland Tools search for "whale-class", "shark-class", "invincible", "enterprise", "bronco", "odyssey", "tatanora", "viltgance", etc. Or scrape the consolegameswiki FC workshop page.

A good starting point is this Garland Tools search pattern:
```
https://garlandtools.org/db/#table/item&text=whale-class
https://garlandtools.org/db/#table/item&text=invincible-type
```

---

## Vendor Arbitrage Mode (v1 — include from the start)

A separate scan mode that finds NPC-sold items being resold on the MB at significant markups. Zero crafting required — pure buy-from-vendor, list-on-MB profit.

### How it works

1. Query Garland Tools for all items where `item.price > 0` (NPC vendor sold)
2. Batch-query Universalis for MB prices on those items
3. Calculate markup: `(mb_price - npc_price) / npc_price * 100`
4. Filter by minimum markup (default: 50%) and minimum sales velocity (default: 1/day)
5. Sort by estimated daily profit: `(mb_price - npc_price) * sale_velocity`

### Known high-value categories

- **Beast tribe vendor materials**: Amalj'aa (Steel Rivets, Steel Ingot), Kobold (Bomb Ash), Ixali, Sylph vendors — these require reputation and/or inconvenient travel, so players overpay on MB
- **Basic gathered materials also sold by NPCs**: Iron Ore (18 NPC → 140 MB = 677% markup observed), Copper Ore, etc.
- **Idyllshire Scrap Salvager items**: Mythrite Ingot (2,652), Holy Cedar Lumber (2,496) — HW-era mats that crafters buy in bulk
- **Housing area Material Suppliers**: Sell a wide range of low-level crafting mats

### Cross-world spread detection (submode)

Universalis returns per-world data within a DC. For any item, compare cheapest listing across all worlds vs highest recent sale price on any world. This catches:
- Items below NPC price on one world (dumped crafted stock) while selling at 2-3x NPC on another
- Volatile commodities like Steel Rivets (observed: 200 gil on Louisoix vs 690 on another Chaos world — a 3.4x spread)
- Bulk materials where one seller crashed the price on a low-pop world

```bash
# Find cross-world arbitrage opportunities within Chaos DC
python ffxiv_scanner.py --dc Chaos --mode cross-world --min-spread 50
```

**Implementation:** Universalis per-world data is available via `?listings=20` on the DC-level endpoint — each listing includes a `worldName` field. Compare min listing price (any world) vs recent sale prices on highest-price worlds. Factor in the 5% tax on the sell side.

**Key caveat for the output:** Flag items where the cheap world's listings are thin (e.g., only 3 available at 200). Buying out thin stock triggers price normalization fast, so the opportunity is time-limited. Show available quantity at the cheap price.

### CLI

```bash
# Find all vendor arbitrage opportunities on Chaos
python ffxiv_scanner.py --dc Chaos --mode vendor-arbitrage --min-markup 50

# Same but only items selling 3+ per day
python ffxiv_scanner.py --dc Chaos --mode vendor-arbitrage --min-markup 50 --min-velocity 3
```

### Implementation note

The tricky part is getting a comprehensive list of NPC-sold items. Garland Tools has this data but there's no single "give me all vendor items" endpoint. Options:
- Scrape the Garland Tools item database dump (they publish CSV/JSON exports periodically)
- Use Teamcraft's data files on GitHub: `https://github.com/ffxiv-teamcraft/ffxiv-teamcraft` — they maintain structured JSON of all items including vendor data
- Start with a curated seed list of known vendor categories and expand

Teamcraft's GitHub data is probably the best starting point — their `items.json` and `shops.json` files have comprehensive vendor data already structured.

---

## Expansion Ideas (v2+)

1. **Recursive margin scanning**: For each ingredient, check if *it* is also profitable to craft (you already found this with Cobalt Joint Plates)
2. **Cross-world arbitrage**: Find items cheaper on one Chaos world vs another
3. **Historical margin tracking**: Store scan results over time, alert when margins widen
4. **Coke efficiency calculator**: Given a Coke price, automatically determine which Coke-consuming recipes are still profitable
5. **GC seal → gil conversion rate**: Calculate effective gil-per-seal for different items to determine optimal seal spending
6. **MCP server wrapper**: Wrap the scanner as an MCP server for conversational queries from Claude Code. Expose tools like:
   - `scan_category(dc, category, min_margin)`
   - `analyze_item(dc, item_id, gc_seals_free=False)`
   - `find_cheapest_world(dc, item_id)`
   - `recipe_tree(item_id)` — full recursive cost breakdown

---

## Known Gotchas

1. **FC Workshop recipes** don't show up in normal crafting logs — they may need special handling in Garland Tools (check `item.craft[].type` or similar field)
2. **Some items are Market Prohibited** — Garland Tools should flag this, skip them
3. **HQ vs NQ matters** for intermediate crafts — submersible parts have no HQ variant, but ingredients like Garlond Steel do. The margin calculation should use NQ prices for components unless HQ is significantly different
4. **Universalis data freshness varies by world** — low-pop worlds may have data that's days old. Check the `lastUploadTime` field and flag stale data
5. **Tax**: MB sales have a tax (depends on city). Default to 5% and subtract from sale price in margin calculation
6. **Retainer listing slots are finite** — high-margin-but-1-sale-per-week items tie up a slot. The `profit_per_day` metric handles this implicitly but it's worth noting
7. **Patch cycles**: New patches can crater or inflate prices. Scan results are snapshots, not predictions
8. **Coke price variance across worlds is massive** — we saw 180 on Sagittarius vs 560 on another Chaos world. The `--show-worlds` flag should highlight this for key materials
9. **Vendor arbitrage is highly volatile** — an item can be 120% above NPC on one server and *below* NPC on another (observed with Steel Rivets: 690 vs 200 vs 313 NPC). Margins can evaporate within hours. The scanner output should include a staleness indicator and ideally timestamp when the price data was last updated per world
