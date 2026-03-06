# FFXIV Crafting Profit Scanner

CLI tool that scans the FFXIV market board to find profitable crafting opportunities, vendor arbitrage, and cross-world price spreads. Uses [Universalis](https://universalis.app/) for market data and [Garland Tools](https://garlandtools.org/) for recipe/item data.

## Setup

```bash
pip install requests
```

First run: scrape item seeds to build the local database of scannable items.

```bash
python3 ffxiv_scanner.py --mode scrape-seeds --dc Chaos
```

This discovers:
- **Workshop items** (submersibles, airships, housing walls) via Garland Tools search
- **NPC vendor items** (~3,600 items in the 10-5000 gil range) from [Teamcraft](https://github.com/ffxiv-teamcraft/ffxiv-teamcraft) data, filtered by MB velocity
- **Popular crafts** with active market board sales

Results are saved to `~/.ffxiv-scanner/seeds.json` and reused by all scan modes. Re-run after major patches to pick up new items.

## Usage

### Craft profit scan

Find items where crafting is cheaper than buying on the market board. Scans workshop items by default.

```bash
# Scan all workshop items (submersibles, airships, housing walls)
python3 ffxiv_scanner.py --dc Chaos --world Louisoix

# Scan a specific item
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --item-id 22527
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --item "Whale-class Bridge"

# Filter by minimum margin, sort by margin %
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --min-margin 100 --sort-by margin_pct

# Treat GC seal items (Coke, etc.) as free
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --gc-seals-free

# Show per-world ingredient prices
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --item-id 22527 --show-worlds
```

### Vendor arbitrage

Find NPC-sold items being resold on the MB at significant markups. Zero crafting required. Scans ~400+ vendor items discovered by the seed scraper.

```bash
# Find vendor markup opportunities (default: 50%+ markup, 0.5+ sales/day)
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --mode vendor-arbitrage

# Stricter filters
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --mode vendor-arbitrage --min-markup 200 --min-velocity 5
```

### Cross-world spread

Find items with large price differences between worlds within a DC.

```bash
python3 ffxiv_scanner.py --dc Chaos --mode cross-world --min-spread 50
```

### Market discovery

Scan the entire marketable item list (~16,700 items) to find craftable items with high margins that aren't in the seed lists. Queries Universalis for all tradeable items, filters by price and velocity, then checks Garland for recipes and calculates margins.

```bash
# Default: items >= 50k avg sale price, >= 0.5 sales/day
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --mode discover

# Lower threshold to catch mid-range items (more results, slower)
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --mode discover --min-price 10000

# High-value only
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --mode discover --min-price 500000 --min-margin 50
```

Newly discovered craftable items are automatically saved to `seeds.json` for future craft scans.

## How pricing works

### Home world vs DC-wide

- **Revenue** uses your home world's (`--world`) recent sale prices and sale velocity — what you'd actually earn listing on your server
- **Ingredient costs** use DC-wide prices, since you can world-visit to buy the cheapest materials

### Outlier-resistant pricing

Sale prices are computed using a robust average instead of trusting Universalis's raw `averagePrice`, which can be skewed by RMT transactions (e.g., a single 20M gil "sale" of a 10 gil item). The algorithm:

1. Compute the **median** of recent sales
2. Filter out any sale more than **3x away** from the median (both high and low)
3. Average the remaining sales

This eliminates RMT cover-up transactions and price manipulation while preserving legitimate price variation.

### Ingredient cost resolution

Costs are resolved in priority order:

1. **GC seals** — free if `--gc-seals-free`, otherwise MB price
2. **Crystals** — always MB price
3. **NPC vendor** — uses vendor buy price from Garland Tools
4. **Gathered** — treated as free if no recipe, no NPC price, and MB < 500 gil
5. **Market board** — DC-wide robust average of recent sales

A 5% tax is applied to all revenue (sell side).

For each ingredient that has its own crafting recipe, a 1-level recursive check shows whether crafting it yourself would be cheaper than buying on the MB.

## CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `--dc` | `Chaos` | Data center name |
| `--world` | `Louisoix` | Home world for selling prices |
| `--mode` | `craft` | `craft`, `vendor-arbitrage`, `cross-world`, `discover`, `scrape-seeds` |
| `--category` | — | Item category filter (e.g., `workshop`) |
| `--item` | — | Search for item by name |
| `--item-id` | — | Scan a specific item by Garland Tools ID |
| `--gc-seals-free` | off | Treat GC seal items as zero cost |
| `--no-cache` | off | Force fresh API calls (ignore cache) |
| `--min-price` | `50000` | Minimum avg sale price (discover mode) |
| `--min-margin` | `0` | Minimum margin % (craft/discover mode) |
| `--min-markup` | `50` | Minimum markup % (vendor-arbitrage mode) |
| `--min-spread` | `50` | Minimum spread % (cross-world mode) |
| `--min-velocity` | `0.5` | Minimum sales per day |
| `--show-worlds` | off | Show per-world prices for ingredients |
| `--sort-by` | `profit_per_day` | `profit_per_day` or `margin_pct` |

## Caching

API responses are cached to `~/.ffxiv-scanner/`:

- **Garland Tools** (recipes, item data): cached indefinitely (static between patches)
- **Universalis** (market prices): cached for 3 hours

Use `--no-cache` to force fresh data.

## Data sources

- **[Universalis API](https://universalis.app/docs)** — real-time market board listings, sale history, and velocity
- **[Garland Tools API](https://garlandtools.org/)** — item metadata, crafting recipes, NPC vendor prices
- **[Teamcraft data](https://github.com/ffxiv-teamcraft/ffxiv-teamcraft)** — comprehensive NPC shop listings (used by seed scraper)

## Project structure

```
ffxiv_scanner.py              # CLI entry point
scanner/
  cache.py                    # JSON file cache with TTL
  pricing.py                  # Price resolution + margin calculation
  output.py                   # Terminal formatting
  data/
    seeds.py                  # Seed data loader (from ~/.ffxiv-scanner/seeds.json)
  api/
    garland.py                # Garland Tools API client
    universalis.py            # Universalis API client (with outlier-resistant pricing)
  modes/
    craft_scan.py             # Crafting profit scan
    vendor_arbitrage.py       # NPC vendor markup scan
    cross_world.py            # Cross-world price spread scan
    discover.py               # Full market discovery scan
    scrape_seeds.py           # Item discovery + seed generation
```
