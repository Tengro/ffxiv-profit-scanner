#!/usr/bin/env python3
"""FFXIV Crafting Profit Scanner — find profitable crafting, vendor arbitrage, and cross-world spreads."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="FFXIV Market Board profit scanner",
    )
    parser.add_argument("--dc", default="Chaos", help="Data center name (default: Chaos)")
    parser.add_argument("--world", default="Louisoix",
                        help="Home world for selling prices (default: Louisoix)")
    parser.add_argument(
        "--mode", default="craft",
        choices=["craft", "vendor-arbitrage", "cross-world", "discover", "gather", "scrape-seeds"],
        help="Scan mode (default: craft)",
    )
    parser.add_argument("--category", help="Item category to scan (e.g., 'workshop')")
    parser.add_argument("--item", help="Search for item by name")
    parser.add_argument("--item-id", type=int, help="Scan a specific item by ID")
    parser.add_argument("--gc-seals-free", action="store_true", help="Treat GC seal items as free")
    parser.add_argument("--no-cache", action="store_true", help="Force fresh API calls")
    parser.add_argument("--stale-ok", action="store_true", help="Use cached data even if expired")
    parser.add_argument("--min-price", type=float, default=50000,
                        help="Minimum avg sale price for discovery mode (default: 50000)")
    parser.add_argument("--min-margin", type=float, default=0, help="Minimum margin %% for craft scan")
    parser.add_argument("--min-markup", type=float, default=50, help="Minimum markup %% for vendor arbitrage")
    parser.add_argument("--min-spread", type=float, default=50, help="Minimum spread %% for cross-world mode")
    parser.add_argument("--min-velocity", type=float, default=0.5, help="Minimum sales/day")
    parser.add_argument("--show-worlds", action="store_true", help="Show per-world prices")
    parser.add_argument("--sort-by", default="profit_per_day", choices=["profit_per_day", "margin_pct"],
                        help="Sort order (default: profit_per_day)")
    parser.add_argument("--min-level", type=int, default=0, help="Miner level (gather mode)")
    parser.add_argument("--btn-level", type=int, default=0, help="Botanist level (gather mode)")
    parser.add_argument("--fsh-level", type=int, default=0, help="Fisher level (gather mode)")

    args = parser.parse_args()

    # Resolve item name to ID if --item is used
    item_ids = None
    if args.item_id:
        item_ids = [args.item_id]
    elif args.item:
        from scanner.api.garland import search_items
        results = search_items(args.item)
        if not results:
            print(f"No items found matching '{args.item}'", file=sys.stderr)
            sys.exit(1)
        if len(results) == 1:
            item_ids = [results[0]["id"]]
            print(f"Found: {results[0]['name']} (ID: {results[0]['id']})")
        else:
            print(f"Multiple items found for '{args.item}':")
            for r in results[:20]:
                print(f"  ID: {r['id']:>6}  {r['name']}")
            print(f"\nUse --item-id to select a specific item.")
            sys.exit(0)

    if args.mode == "craft":
        from scanner.modes.craft_scan import run
        run(
            dc=args.dc,
            world=args.world,
            item_ids=item_ids,
            category=args.category,
            gc_seals_free=args.gc_seals_free,
            no_cache=args.no_cache,
            allow_stale=args.stale_ok,
            min_margin=args.min_margin,
            sort_by=args.sort_by,
            show_worlds=args.show_worlds,
        )
    elif args.mode == "vendor-arbitrage":
        from scanner.modes.vendor_arbitrage import run
        run(
            dc=args.dc,
            world=args.world,
            no_cache=args.no_cache,
            allow_stale=args.stale_ok,
            min_markup=args.min_markup,
            min_velocity=args.min_velocity,
            show_worlds=args.show_worlds,
        )
    elif args.mode == "cross-world":
        from scanner.modes.cross_world import run
        run(
            dc=args.dc,
            item_ids=item_ids,
            category=args.category,
            no_cache=args.no_cache,
            allow_stale=args.stale_ok,
            min_spread=args.min_spread,
            min_velocity=args.min_velocity,
            show_worlds=args.show_worlds,
        )
    elif args.mode == "discover":
        from scanner.modes.discover import run
        run(
            dc=args.dc,
            world=args.world,
            no_cache=args.no_cache,
            allow_stale=args.stale_ok,
            min_price=args.min_price,
            min_velocity=args.min_velocity,
            min_margin=args.min_margin,
            sort_by=args.sort_by,
            show_worlds=args.show_worlds,
        )
    elif args.mode == "gather":
        from scanner.modes.gather_scan import run
        run(
            dc=args.dc,
            world=args.world,
            no_cache=args.no_cache,
            allow_stale=args.stale_ok,
            min_price=args.min_price,
            min_velocity=args.min_velocity,
            min_level=args.min_level,
            btn_level=args.btn_level,
            fsh_level=args.fsh_level,
        )
    elif args.mode == "scrape-seeds":
        from scanner.modes.scrape_seeds import run
        run(dc=args.dc, no_cache=args.no_cache)


if __name__ == "__main__":
    main()
