#!/usr/bin/env python3
"""FFXIV Market Board Profit Scanner v1.0"""

import argparse
import sys


# FFXIV crafter job names for CLI args
CRAFT_JOBS = ["crp", "bsm", "arm", "gsm", "ltw", "wvr", "alc", "cul"]


def main():
    parser = argparse.ArgumentParser(
        description="FFXIV Market Board profit scanner",
    )
    parser.add_argument("--dc", default="Chaos", help="Data center name (default: Chaos)")
    parser.add_argument("--world", default="Louisoix",
                        help="Home world for selling prices (default: Louisoix)")
    parser.add_argument(
        "--mode", default="crafting",
        choices=["workshop", "crafting", "vendor-arbitrage", "gather", "hunter", "scrape-seeds"],
        help="Scan mode (default: crafting)",
    )
    parser.add_argument("--item", help="Search for item by name")
    parser.add_argument("--item-id", type=int, help="Scan a specific item by ID")
    parser.add_argument("--gc-seals-free", action="store_true", help="Treat GC seal items as free")
    parser.add_argument("--no-cache", action="store_true", help="Force fresh API calls")
    parser.add_argument("--stale-ok", action="store_true", help="Use cached data even if expired")
    parser.add_argument("--min-price", type=float, default=100,
                        help="Minimum avg sale price (default: 100)")
    parser.add_argument("--min-margin", type=float, default=0, help="Minimum margin %% for workshop scan")
    parser.add_argument("--min-markup", type=float, default=50, help="Minimum markup %% for vendor arbitrage")
    parser.add_argument("--min-velocity", type=float, default=0.5, help="Minimum sales/day")
    parser.add_argument("--sort-by", default="gil_per_day",
                        choices=["gil_per_day", "mb_price", "velocity"],
                        help="Sort order (default: gil_per_day)")
    # Gather job levels
    parser.add_argument("--min-level", type=int, default=0, help="Miner level (gather mode)")
    parser.add_argument("--btn-level", type=int, default=0, help="Botanist level (gather mode)")
    parser.add_argument("--fsh-level", type=int, default=0, help="Fisher level (gather mode)")
    # Crafter job levels
    for job in CRAFT_JOBS:
        parser.add_argument(f"--{job}-level", type=int, default=0,
                            help=f"{job.upper()} level (crafting mode)")

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

    if args.mode == "workshop":
        from scanner.modes.craft_scan import run
        run(
            dc=args.dc,
            world=args.world,
            item_ids=item_ids,
            gc_seals_free=args.gc_seals_free,
            no_cache=args.no_cache,
            allow_stale=args.stale_ok,
            min_margin=args.min_margin,
        )
    elif args.mode == "crafting":
        from scanner.modes.crafting_scan import run
        # Build job levels dict from CLI args
        job_levels = {}
        for job in CRAFT_JOBS:
            level = getattr(args, f"{job}_level")
            if level > 0:
                job_levels[job.upper()] = level
        run(
            dc=args.dc,
            world=args.world,
            no_cache=args.no_cache,
            allow_stale=args.stale_ok,
            job_levels=job_levels,
            min_price=args.min_price,
            min_velocity=args.min_velocity,
            sort_by=args.sort_by,
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
    elif args.mode == "hunter":
        from scanner.modes.hunter_scan import run
        run(
            dc=args.dc,
            world=args.world,
            no_cache=args.no_cache,
            allow_stale=args.stale_ok,
            min_price=args.min_price,
            min_velocity=args.min_velocity,
        )
    elif args.mode == "scrape-seeds":
        from scanner.modes.scrape_seeds import run
        run(dc=args.dc, no_cache=args.no_cache)


if __name__ == "__main__":
    main()
