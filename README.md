# FFXIV Market Board Scanner v1.0

CLI + GUI tool that scans the FFXIV market board to find profitable activities for your character. Uses [Universalis](https://universalis.app/) for market data and [Garland Tools](https://garlandtools.org/) for recipe/item data.

All modes are **world-specific** — you sell where you play.

## Setup

```bash
pip install requests nicegui
```

## Modes

### Crafting (default)

Find profitable items to craft based on your crafter levels. Shows MB price, velocity, and estimated gil/day.

```bash
# What can my CUL 90 and WVR 80 craft profitably?
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --cul-level 90 --wvr-level 80

# Higher filters
python3 ffxiv_scanner.py --dc Chaos --world Louisoix --cul-level 100 --min-price 500 --min-velocity 2
```

Available crafter flags: `--crp-level`, `--bsm-level`, `--arm-level`, `--gsm-level`, `--ltw-level`, `--wvr-level`, `--alc-level`, `--cul-level`

### Gather

Find profitable items to gather based on your gatherer levels.

```bash
python3 ffxiv_scanner.py --mode gather --dc Chaos --world Louisoix --min-level 90 --btn-level 87
```

### Hunter

Find profitable mob-drop materials (hides, horns, meat, bones, etc.). Uses item-side detection — works across all expansions.

```bash
python3 ffxiv_scanner.py --mode hunter --dc Chaos --world Louisoix --min-price 200
```

### Vendor Arbitrage

Find NPC-sold items being resold on the MB at significant markups. Zero crafting required.

```bash
# Default: 50%+ markup, 0.5+ sales/day
python3 ffxiv_scanner.py --mode vendor-arbitrage --dc Chaos --world Louisoix

# Stricter filters
python3 ffxiv_scanner.py --mode vendor-arbitrage --dc Chaos --world Louisoix --min-markup 200 --min-velocity 5
```

### Workshop

Full margin analysis for FC workshop items (submersibles, airships, housing walls). Includes ingredient cost breakdown.

```bash
python3 ffxiv_scanner.py --mode workshop --dc Chaos --world Louisoix

# Scan a specific item
python3 ffxiv_scanner.py --mode workshop --dc Chaos --world Louisoix --item "Whale-class Bridge"

# Treat GC seal items as free
python3 ffxiv_scanner.py --mode workshop --dc Chaos --world Louisoix --gc-seals-free
```

### Seed Scraper

Discover items for workshop and vendor modes.

```bash
python3 ffxiv_scanner.py --mode scrape-seeds --dc Chaos
```

## GUI

```bash
python3 app.py
```

Opens a NiceGUI web interface with tabs for all scan modes.

## How pricing works

### Outlier-resistant pricing

Sale prices use a robust average instead of Universalis's raw `averagePrice`, which can be skewed by RMT transactions. The algorithm:

1. Compute the **median** of recent sales
2. Filter out any sale more than **3x away** from the median
3. Average the remaining sales

### Ingredient cost resolution (Workshop mode)

Costs are resolved in priority order:

1. **GC seals** — free if `--gc-seals-free`, otherwise MB price
2. **Crystals** — always MB price
3. **NPC vendor** — uses vendor buy price from Garland Tools
4. **Gathered** — treated as free if no recipe, no NPC price, and MB < 500 gil
5. **Market board** — world-specific robust average of recent sales

A 5% tax is applied to all revenue.

## CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `--dc` | `Chaos` | Data center name |
| `--world` | `Louisoix` | Home world for selling prices |
| `--mode` | `crafting` | `crafting`, `gather`, `hunter`, `vendor-arbitrage`, `workshop`, `scrape-seeds` |
| `--item` | — | Search for item by name |
| `--item-id` | — | Scan a specific item by ID |
| `--gc-seals-free` | off | Treat GC seal items as zero cost (workshop mode) |
| `--no-cache` | off | Force fresh API calls |
| `--stale-ok` | off | Use cached data even if expired |
| `--min-price` | `100` | Minimum avg sale price |
| `--min-margin` | `0` | Minimum margin % (workshop mode) |
| `--min-markup` | `50` | Minimum markup % (vendor-arbitrage mode) |
| `--min-velocity` | `0.5` | Minimum sales per day |
| `--sort-by` | `gil_per_day` | `gil_per_day`, `mb_price`, or `velocity` |
| `--crp-level` | `0` | Carpenter level (crafting mode) |
| `--bsm-level` | `0` | Blacksmith level (crafting mode) |
| `--arm-level` | `0` | Armorer level (crafting mode) |
| `--gsm-level` | `0` | Goldsmith level (crafting mode) |
| `--ltw-level` | `0` | Leatherworker level (crafting mode) |
| `--wvr-level` | `0` | Weaver level (crafting mode) |
| `--alc-level` | `0` | Alchemist level (crafting mode) |
| `--cul-level` | `0` | Culinarian level (crafting mode) |
| `--min-level` | `0` | Miner level (gather mode) |
| `--btn-level` | `0` | Botanist level (gather mode) |
| `--fsh-level` | `0` | Fisher level (gather mode) |

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
app.py                        # NiceGUI web interface
scanner/
  cache.py                    # JSON file cache with TTL
  pricing.py                  # Price resolution + margin calculation
  output.py                   # Terminal formatting
  data/
    seeds.py                  # Seed data loader
  api/
    garland.py                # Garland Tools API client
    universalis.py            # Universalis API client (with outlier-resistant pricing)
  modes/
    craft_scan.py             # Workshop profit scan (full margin analysis)
    crafting_scan.py          # Crafting scan (by class + level, price/velocity)
    hunter_scan.py            # Mob-drop material scan
    gather_scan.py            # Gathering scan (by class + level)
    vendor_arbitrage.py       # NPC vendor markup scan
    scrape_seeds.py           # Item discovery + seed generation
```
