#!/usr/bin/env python3
"""NiceGUI frontend for the FFXIV Market Board Profit Scanner v1.0."""

from nicegui import ui, run

from scanner.modes import craft_scan, vendor_arbitrage, gather_scan, hunter_scan, crafting_scan, scrape_seeds
from scanner.data.seeds import _load_seeds, reload_seeds, SEEDS_PATH
from scanner.output import gil
from scanner import cache

# Known FFXIV data centers
DATA_CENTERS = [
    "Chaos", "Light",  # EU
    "Aether", "Crystal", "Dynamis", "Primal",  # NA
    "Elemental", "Gaia", "Mana", "Meteor",  # JP
    "Materia",  # OCE
]


def _format_age(seconds: float) -> str:
    """Human-readable age string."""
    if seconds < 60:
        return f"{seconds:.0f}s ago"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m ago"
    if seconds < 86400:
        h = seconds / 3600
        return f"{h:.1f}h ago"
    d = seconds / 86400
    return f"{d:.1f}d ago"


async def _show_stale_dialog(age_str: str, run_fn):
    """Show a dialog asking user whether to use stale cache or refresh."""
    dialog = ui.dialog()

    async def _use_cached():
        dialog.close()
        await run_fn(allow_stale=True)

    async def _refresh():
        dialog.close()
        await run_fn(allow_stale=False)

    with dialog, ui.card():
        ui.label(f"Cached price data is {age_str}.").classes("text-subtitle1")
        ui.label("Use cached data or fetch fresh prices from Universalis?")
        with ui.row().classes("justify-end w-full gap-2 mt-2"):
            ui.button(f"Use cached ({age_str})", icon="cached",
                      on_click=_use_cached).props("flat")
            ui.button("Refresh prices", icon="refresh",
                      on_click=_refresh)
    dialog.open()


async def _check_cache_freshness() -> tuple[bool, str]:
    """Check Universalis cache and return (is_fresh, age_description).

    Returns (True, "") if cache is fresh or empty.
    Returns (False, "Xh ago") if cache exists but is stale.
    """
    age = cache.namespace_age("universalis")
    if age is None:
        return True, ""
    ttl = cache.NAMESPACE_TTL.get("universalis", 10800)
    if age <= ttl:
        return True, _format_age(age)
    return False, _format_age(age)


def with_cache_check(state: dict, run_fn):
    """Wrap a scan function with stale-cache dialog logic."""
    async def _on_click():
        if state["no_cache"]:
            await run_fn(allow_stale=False)
            return
        is_fresh, age_str = await _check_cache_freshness()
        if is_fresh:
            await run_fn(allow_stale=False)
        else:
            await _show_stale_dialog(age_str, run_fn)
    return _on_click


def create_app():
    # --- Shared state ---
    state = {
        "dc": "Chaos",
        "world": "Louisoix",
        "gc_seals_free": False,
        "no_cache": False,
    }

    # --- Page ---
    ui.page_title("FFXIV Market Scanner")

    # --- Header ---
    with ui.row().classes("w-full items-center gap-4 p-4 bg-blue-grey-9"):
        ui.label("FFXIV Market Scanner").classes("text-h5 text-white")
        ui.space()
        dc_select = ui.select(
            DATA_CENTERS, value=state["dc"], label="Data Center",
            on_change=lambda e: state.update(dc=e.value),
        ).classes("w-40")
        world_input = ui.input(
            "Home World", value=state["world"],
            on_change=lambda e: state.update(world=e.value),
        ).classes("w-40")
        ui.switch("GC Seals Free",
                  on_change=lambda e: state.update(gc_seals_free=e.value))
        ui.switch("No Cache",
                  on_change=lambda e: state.update(no_cache=e.value))

        async def _clear_cache():
            await run.io_bound(cache.clear)
            ui.notify("Cache cleared!", type="positive")

        ui.button("Clear Cache", icon="delete_sweep", on_click=_clear_cache).props("flat dense")

    # --- Tabs ---
    with ui.tabs().classes("w-full") as tabs:
        crafting_tab = ui.tab("Crafting", icon="handyman")
        gather_tab = ui.tab("Gather", icon="park")
        hunter_tab = ui.tab("Hunter", icon="pets")
        vendor_tab = ui.tab("Vendor", icon="store")
        workshop_tab = ui.tab("Workshop", icon="build")
        seeds_tab = ui.tab("Seeds", icon="storage")

    with ui.tab_panels(tabs, value=crafting_tab).classes("w-full"):

        # ===================== CRAFTING =====================
        with ui.tab_panel(crafting_tab):
            _build_crafting_panel(state)

        # ===================== GATHER =====================
        with ui.tab_panel(gather_tab):
            _build_gather_panel(state)

        # ===================== HUNTER =====================
        with ui.tab_panel(hunter_tab):
            _build_hunter_panel(state)

        # ===================== VENDOR ARBITRAGE =====================
        with ui.tab_panel(vendor_tab):
            _build_vendor_panel(state)

        # ===================== WORKSHOP =====================
        with ui.tab_panel(workshop_tab):
            _build_workshop_panel(state)

        # ===================== SEEDS =====================
        with ui.tab_panel(seeds_tab):
            _build_seeds_panel(state)


def _build_workshop_panel(state: dict):
    min_margin = {"value": 0.0}
    sort_by = {"value": "profit_per_day"}

    # Hint about seeds
    seeds = _load_seeds()
    if not seeds:
        ui.label(
            "No seeds found. Go to the Seeds tab and run the scraper first, "
            "then use Discovery to find more items."
        ).classes("text-warning p-2 bg-yellow-1 rounded w-full")
    elif not seeds.get("discovered"):
        ui.label(
            "Scanning workshop items only. Run Discovery mode to find more profitable crafts."
        ).classes("text-info p-2 bg-blue-1 rounded w-full")

    with ui.row().classes("items-center gap-4 p-2"):
        ui.number("Min Margin %", value=0, min=0, format="%.0f",
                  on_change=lambda e: min_margin.update(value=e.value or 0)).classes("w-32")
        ui.select({"profit_per_day": "Profit/Day", "margin_pct": "Margin %"},
                  value="profit_per_day", label="Sort By",
                  on_change=lambda e: sort_by.update(value=e.value)).classes("w-40")
        scan_btn = ui.button("Scan", icon="play_arrow")
        spinner = ui.spinner(size="lg")
        spinner.visible = False
        status = ui.label("")

    _fmt_gil = "val => val != null ? val.toLocaleString('en-US', {maximumFractionDigits: 0}) : ''"
    _fmt_pct = "val => val != null ? val.toFixed(0) + '%' : ''"
    _fmt_dec = "val => val != null ? val.toFixed(1) : ''"
    _fmt_age = "val => { if (!val) return '?'; let s = val > 1e12 ? val/1000 : val; let m = Math.floor((Date.now()/1000 - s)/60); if (m < 60) return m + 'm ago'; let h = Math.floor(m/60); if (h < 24) return h + 'h ' + (m%60) + 'm ago'; return Math.floor(h/24) + 'd ago'; }"
    columns = [
        {"name": "name", "label": "Item", "field": "name", "sortable": True, "align": "left"},
        {"name": "mb_price", "label": "MB Price", "field": "mb_price", "sortable": True, ":format": _fmt_gil},
        {"name": "craft_cost", "label": "Craft Cost", "field": "craft_cost", "sortable": True, ":format": _fmt_gil},
        {"name": "margin", "label": "Margin", "field": "margin", "sortable": True, ":format": _fmt_gil},
        {"name": "margin_pct", "label": "Margin %", "field": "margin_pct", "sortable": True, ":format": _fmt_pct},
        {"name": "velocity", "label": "Sales/day", "field": "velocity", "sortable": True, ":format": _fmt_dec},
        {"name": "profit_per_day", "label": "Profit/day", "field": "profit_per_day", "sortable": True, ":format": _fmt_gil},
        {"name": "last_updated", "label": "Updated", "field": "last_updated", "sortable": True, ":format": _fmt_age},
    ]
    table = ui.table(columns=columns, rows=[], row_key="item_id").classes("w-full")
    detail_container = ui.column().classes("w-full")

    def _show_ingredients(e):
        detail_container.clear()
        if not e.args or not e.args.get("name"):
            return
        row = e.args
        # Find the full result
        for r in _craft_results:
            if r.name == row["name"]:
                with detail_container:
                    with ui.card().classes("w-full"):
                        ui.label(f"Ingredients for {r.name}").classes("text-subtitle1")
                        for ing in r.ingredient_costs:
                            source = ing.source.upper()
                            line = f"{ing.name} x{ing.amount} @ {gil(ing.price_per_unit)} ea ({source}) = {gil(ing.total_cost)}"
                            ui.label(line).classes("font-mono text-sm")
                            if ing.craft_alternative is not None:
                                ui.label(
                                    f"  Craftable: ~{gil(ing.craft_alternative)} ea "
                                    f"({ing.craft_savings_pct:.0f}% savings)"
                                ).classes("font-mono text-sm text-positive")
                break

    table.on("rowClick", _show_ingredients)

    _craft_results = []

    async def _run_scan(allow_stale: bool = False):
        nonlocal _craft_results
        scan_btn.disable()
        spinner.visible = True
        status.text = "Scanning..."
        detail_container.clear()
        try:
            results = await run.io_bound(
                craft_scan.scan,
                dc=state["dc"], world=state["world"],
                gc_seals_free=state["gc_seals_free"],
                no_cache=state["no_cache"],
                allow_stale=allow_stale,
                min_margin=min_margin["value"],
                sort_by=sort_by["value"],
            )
            _craft_results = results
            table.rows = [
                {
                    "item_id": r.item_id,
                    "name": r.name,
                    "mb_price": r.mb_price,
                    "craft_cost": r.craft_cost,
                    "margin": r.margin,
                    "margin_pct": r.margin_pct,
                    "velocity": r.sale_velocity,
                    "profit_per_day": r.profit_per_day,
                    "last_updated": r.last_upload_time,
                }
                for r in results
            ]
            table.update()
            status.text = f"{len(results)} items found"
        except Exception as e:
            status.text = f"Error: {e}"
            ui.notify(f"Scan failed: {e}", type="negative")
        finally:
            spinner.visible = False
            scan_btn.enable()

    scan_btn.on_click(with_cache_check(state, _run_scan))


def _build_vendor_panel(state: dict):
    min_markup = {"value": 50.0}
    min_velocity = {"value": 0.5}

    with ui.row().classes("items-center gap-4 p-2"):
        ui.number("Min Markup %", value=50, min=0, format="%.0f",
                  on_change=lambda e: min_markup.update(value=e.value or 0)).classes("w-32")
        ui.number("Min Velocity", value=0.5, min=0, step=0.1, format="%.1f",
                  on_change=lambda e: min_velocity.update(value=e.value or 0)).classes("w-32")
        scan_btn = ui.button("Scan", icon="play_arrow")
        spinner = ui.spinner(size="lg")
        spinner.visible = False
        status = ui.label("")

    _fmt_gil = "val => val != null ? val.toLocaleString('en-US', {maximumFractionDigits: 0}) : ''"
    _fmt_pct = "val => val != null ? val.toFixed(0) + '%' : ''"
    _fmt_dec = "val => val != null ? val.toFixed(1) : ''"
    _fmt_age = "val => { if (!val) return '?'; let s = val > 1e12 ? val/1000 : val; let m = Math.floor((Date.now()/1000 - s)/60); if (m < 60) return m + 'm ago'; let h = Math.floor(m/60); if (h < 24) return h + 'h ' + (m%60) + 'm ago'; return Math.floor(h/24) + 'd ago'; }"
    columns = [
        {"name": "name", "label": "Item", "field": "name", "sortable": True, "align": "left"},
        {"name": "npc_price", "label": "NPC Price", "field": "npc_price", "sortable": True, ":format": _fmt_gil},
        {"name": "mb_price", "label": "MB Price", "field": "mb_price", "sortable": True, ":format": _fmt_gil},
        {"name": "markup_pct", "label": "Markup %", "field": "markup_pct", "sortable": True, ":format": _fmt_pct},
        {"name": "velocity", "label": "Sales/day", "field": "velocity", "sortable": True, ":format": _fmt_dec},
        {"name": "daily_profit", "label": "Profit/day", "field": "daily_profit", "sortable": True, ":format": _fmt_gil},
        {"name": "last_updated", "label": "Updated", "field": "last_updated", "sortable": True, ":format": _fmt_age},
    ]
    table = ui.table(columns=columns, rows=[], row_key="item_id").classes("w-full")

    async def _run_scan(allow_stale: bool = False):
        scan_btn.disable()
        spinner.visible = True
        status.text = "Scanning..."
        try:
            results = await run.io_bound(
                vendor_arbitrage.scan,
                dc=state["dc"], world=state["world"],
                no_cache=state["no_cache"],
                allow_stale=allow_stale,
                min_markup=min_markup["value"],
                min_velocity=min_velocity["value"],
            )
            table.rows = [
                {
                    "item_id": r["item_id"],
                    "name": r["name"],
                    "npc_price": r["npc_price"],
                    "mb_price": r["mb_price"],
                    "markup_pct": r["markup_pct"],
                    "velocity": r["velocity"],
                    "daily_profit": r["daily_profit"],
                    "last_updated": r.get("last_updated", 0),
                }
                for r in results
            ]
            table.update()
            status.text = f"{len(results)} opportunities found"
        except Exception as e:
            status.text = f"Error: {e}"
            ui.notify(f"Scan failed: {e}", type="negative")
        finally:
            spinner.visible = False
            scan_btn.enable()

    scan_btn.on_click(with_cache_check(state, _run_scan))



def _build_gather_panel(state: dict):
    min_level = {"value": 0}
    btn_level = {"value": 0}
    fsh_level = {"value": 0}
    min_price = {"value": 100.0}
    min_velocity = {"value": 1.0}

    ui.label(
        "Set your gathering job levels (0 = skip that job). "
        "Scans only gatherable items — fast even on first run."
    ).classes("text-info p-2 bg-blue-1 rounded w-full")

    with ui.row().classes("items-center gap-4 p-2"):
        ui.number("MIN Level", value=0, min=0, max=100, format="%.0f",
                  on_change=lambda e: min_level.update(value=int(e.value or 0))).classes("w-28")
        ui.number("BTN Level", value=0, min=0, max=100, format="%.0f",
                  on_change=lambda e: btn_level.update(value=int(e.value or 0))).classes("w-28")
        ui.number("FSH Level", value=0, min=0, max=100, format="%.0f",
                  on_change=lambda e: fsh_level.update(value=int(e.value or 0))).classes("w-28")
    with ui.row().classes("items-center gap-4 p-2"):
        ui.number("Min Price", value=100, min=0, format="%.0f",
                  on_change=lambda e: min_price.update(value=e.value or 0)).classes("w-32")
        ui.number("Min Velocity", value=1.0, min=0, step=0.1, format="%.1f",
                  on_change=lambda e: min_velocity.update(value=e.value or 0)).classes("w-32")
        scan_btn = ui.button("Scan", icon="play_arrow")
        spinner = ui.spinner(size="lg")
        spinner.visible = False

    progress_label = ui.label("").classes("p-2")
    progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
    progress_bar.visible = False

    _fmt_gil = "val => val != null ? val.toLocaleString('en-US', {maximumFractionDigits: 0}) : ''"
    _fmt_dec = "val => val != null ? val.toFixed(1) : ''"
    _fmt_age = "val => { if (!val) return '?'; let s = val > 1e12 ? val/1000 : val; let m = Math.floor((Date.now()/1000 - s)/60); if (m < 60) return m + 'm ago'; let h = Math.floor(m/60); if (h < 24) return h + 'h ' + (m%60) + 'm ago'; return Math.floor(h/24) + 'd ago'; }"
    columns = [
        {"name": "name", "label": "Item", "field": "name", "sortable": True, "align": "left"},
        {"name": "job", "label": "Job", "field": "job", "sortable": True},
        {"name": "level", "label": "Level", "field": "level", "sortable": True},
        {"name": "location", "label": "Location", "field": "location", "sortable": True, "align": "left"},
        {"name": "timed", "label": "Timed", "field": "timed", "sortable": True},
        {"name": "mb_price", "label": "MB Price", "field": "mb_price", "sortable": True, ":format": _fmt_gil},
        {"name": "velocity", "label": "Sales/day", "field": "velocity", "sortable": True, ":format": _fmt_dec},
        {"name": "gil_per_day", "label": "Gil/day", "field": "gil_per_day", "sortable": True, ":format": _fmt_gil},
        {"name": "bargain", "label": "Bargain", "field": "bargain", "sortable": True, "align": "left"},
        {"name": "last_updated", "label": "Updated", "field": "last_updated", "sortable": True, ":format": _fmt_age},
    ]
    table = ui.table(columns=columns, rows=[], row_key="item_id").classes("w-full")

    async def _run_scan(allow_stale: bool = False):
        scan_btn.disable()
        spinner.visible = True
        progress_bar.visible = True
        progress_bar.value = 0
        progress_label.text = "Starting gather scan..."

        def _on_progress(phase, total, msg):
            progress_bar.value = phase / total
            progress_label.text = f"Phase {phase}/{total}: {msg}"

        try:
            results = await run.io_bound(
                gather_scan.scan,
                dc=state["dc"], world=state["world"],
                no_cache=state["no_cache"],
                allow_stale=allow_stale,
                min_price=min_price["value"],
                min_velocity=min_velocity["value"],
                min_level=min_level["value"],
                btn_level=btn_level["value"],
                fsh_level=fsh_level["value"],
                on_progress=_on_progress,
            )
            table.rows = [
                {
                    "item_id": r["item_id"],
                    "name": r["name"],
                    "job": r["job"],
                    "level": r["level"],
                    "location": r["location"],
                    "timed": "Yes" if r["is_timed"] else "",
                    "mb_price": r["mb_price"],
                    "velocity": r["velocity"],
                    "gil_per_day": r["gil_per_day"],
                    "bargain": (
                        f"{r['bargain']['world']}: {r['bargain']['price']:,} x{r['bargain']['qty']} (-{r['bargain']['discount_pct']}%)"
                        if r.get("bargain") else ""
                    ),
                    "last_updated": r.get("last_updated", 0),
                }
                for r in results
            ]
            table.update()
            progress_label.text = f"Done — {len(results)} gathering opportunities found"
        except Exception as e:
            progress_label.text = f"Error: {e}"
            ui.notify(f"Gather scan failed: {e}", type="negative")
        finally:
            spinner.visible = False
            progress_bar.visible = False
            scan_btn.enable()

    scan_btn.on_click(with_cache_check(state, _run_scan))


def _build_hunter_panel(state: dict):
    min_price = {"value": 100.0}
    min_velocity = {"value": 1.0}

    ui.label(
        "Find profitable mob-drop materials (hides, horns, meat, bones, etc.). "
        "Scans all marketable items, identifies hunting materials via Garland. "
        "First run is slow (~3-5 min) as it checks items against Garland; subsequent runs use cache."
    ).classes("text-info p-2 bg-blue-1 rounded w-full")

    with ui.row().classes("items-center gap-4 p-2"):
        ui.number("Min Price", value=100, min=0, format="%.0f",
                  on_change=lambda e: min_price.update(value=e.value or 0)).classes("w-32")
        ui.number("Min Velocity", value=1.0, min=0, step=0.1, format="%.1f",
                  on_change=lambda e: min_velocity.update(value=e.value or 0)).classes("w-32")
        scan_btn = ui.button("Scan", icon="play_arrow")
        spinner = ui.spinner(size="lg")
        spinner.visible = False

    progress_label = ui.label("").classes("p-2")
    progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
    progress_bar.visible = False

    _fmt_gil = "val => val != null ? val.toLocaleString('en-US', {maximumFractionDigits: 0}) : ''"
    _fmt_dec = "val => val != null ? val.toFixed(1) : ''"
    _fmt_age = "val => { if (!val) return '?'; let s = val > 1e12 ? val/1000 : val; let m = Math.floor((Date.now()/1000 - s)/60); if (m < 60) return m + 'm ago'; let h = Math.floor(m/60); if (h < 24) return h + 'h ' + (m%60) + 'm ago'; return Math.floor(h/24) + 'd ago'; }"
    columns = [
        {"name": "name", "label": "Item", "field": "name", "sortable": True, "align": "left"},
        {"name": "mb_price", "label": "MB Price", "field": "mb_price", "sortable": True, ":format": _fmt_gil},
        {"name": "velocity", "label": "Sales/day", "field": "velocity", "sortable": True, ":format": _fmt_dec},
        {"name": "gil_per_day", "label": "Gil/day", "field": "gil_per_day", "sortable": True, ":format": _fmt_gil},
        {"name": "bargain", "label": "Bargain", "field": "bargain", "sortable": True, "align": "left"},
        {"name": "last_updated", "label": "Updated", "field": "last_updated", "sortable": True, ":format": _fmt_age},
    ]
    table = ui.table(columns=columns, rows=[], row_key="item_id").classes("w-full")

    async def _run_scan(allow_stale: bool = False):
        scan_btn.disable()
        spinner.visible = True
        progress_bar.visible = True
        progress_bar.value = 0
        progress_label.text = "Starting hunter scan..."

        def _on_progress(phase, total, msg):
            progress_bar.value = phase / total
            progress_label.text = f"Phase {phase}/{total}: {msg}"

        try:
            results = await run.io_bound(
                hunter_scan.scan,
                dc=state["dc"], world=state["world"],
                no_cache=state["no_cache"],
                allow_stale=allow_stale,
                min_price=min_price["value"],
                min_velocity=min_velocity["value"],
                on_progress=_on_progress,
            )
            table.rows = [
                {
                    "item_id": r["item_id"],
                    "name": r["name"],
                    "mb_price": r["mb_price"],
                    "velocity": r["velocity"],
                    "gil_per_day": r["gil_per_day"],
                    "bargain": (
                        f"{r['bargain']['world']}: {r['bargain']['price']:,} x{r['bargain']['qty']} (-{r['bargain']['discount_pct']}%)"
                        if r.get("bargain") else ""
                    ),
                    "last_updated": r.get("last_updated", 0),
                }
                for r in results
            ]
            table.update()
            progress_label.text = f"Done — {len(results)} hunting opportunities found"
        except Exception as e:
            progress_label.text = f"Error: {e}"
            ui.notify(f"Hunter scan failed: {e}", type="negative")
        finally:
            spinner.visible = False
            progress_bar.visible = False
            scan_btn.enable()

    scan_btn.on_click(with_cache_check(state, _run_scan))


def _build_crafting_panel(state: dict):
    job_levels = {
        "CRP": {"value": 0}, "BSM": {"value": 0}, "ARM": {"value": 0}, "GSM": {"value": 0},
        "LTW": {"value": 0}, "WVR": {"value": 0}, "ALC": {"value": 0}, "CUL": {"value": 0},
    }
    min_price = {"value": 100.0}
    min_velocity = {"value": 1.0}

    ui.label(
        "Set your crafter levels (0 = skip). Scans all marketable items, identifies "
        "what you can craft, and shows what sells well. First run is slow (~3-5 min); "
        "subsequent runs use cache."
    ).classes("text-info p-2 bg-blue-1 rounded w-full")

    with ui.row().classes("items-center gap-4 p-2 flex-wrap"):
        for job in ["CRP", "BSM", "ARM", "GSM", "LTW", "WVR", "ALC", "CUL"]:
            ui.number(job, value=0, min=0, max=100, format="%.0f",
                      on_change=lambda e, j=job: job_levels[j].update(value=int(e.value or 0))).classes("w-20")
    with ui.row().classes("items-center gap-4 p-2"):
        ui.number("Min Price", value=100, min=0, format="%.0f",
                  on_change=lambda e: min_price.update(value=e.value or 0)).classes("w-32")
        ui.number("Min Velocity", value=1.0, min=0, step=0.1, format="%.1f",
                  on_change=lambda e: min_velocity.update(value=e.value or 0)).classes("w-32")
        scan_btn = ui.button("Scan", icon="play_arrow")
        spinner = ui.spinner(size="lg")
        spinner.visible = False

    progress_label = ui.label("").classes("p-2")
    progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
    progress_bar.visible = False

    _fmt_gil = "val => val != null ? val.toLocaleString('en-US', {maximumFractionDigits: 0}) : ''"
    _fmt_dec = "val => val != null ? val.toFixed(1) : ''"
    _fmt_age = "val => { if (!val) return '?'; let s = val > 1e12 ? val/1000 : val; let m = Math.floor((Date.now()/1000 - s)/60); if (m < 60) return m + 'm ago'; let h = Math.floor(m/60); if (h < 24) return h + 'h ' + (m%60) + 'm ago'; return Math.floor(h/24) + 'd ago'; }"
    columns = [
        {"name": "name", "label": "Item", "field": "name", "sortable": True, "align": "left"},
        {"name": "job", "label": "Job", "field": "job", "sortable": True},
        {"name": "level", "label": "Level", "field": "level", "sortable": True},
        {"name": "mb_price", "label": "MB Price", "field": "mb_price", "sortable": True, ":format": _fmt_gil},
        {"name": "velocity", "label": "Sales/day", "field": "velocity", "sortable": True, ":format": _fmt_dec},
        {"name": "gil_per_day", "label": "Gil/day", "field": "gil_per_day", "sortable": True, ":format": _fmt_gil},
        {"name": "bargain", "label": "Bargain", "field": "bargain", "sortable": True, "align": "left"},
        {"name": "last_updated", "label": "Updated", "field": "last_updated", "sortable": True, ":format": _fmt_age},
    ]
    table = ui.table(columns=columns, rows=[], row_key="item_id").classes("w-full")

    async def _run_scan(allow_stale: bool = False):
        scan_btn.disable()
        spinner.visible = True
        progress_bar.visible = True
        progress_bar.value = 0
        progress_label.text = "Starting crafting scan..."

        def _on_progress(phase, total, msg):
            progress_bar.value = phase / total
            progress_label.text = f"Phase {phase}/{total}: {msg}"

        # Build job levels dict
        levels = {j: d["value"] for j, d in job_levels.items() if d["value"] > 0}

        try:
            results = await run.io_bound(
                crafting_scan.scan,
                dc=state["dc"], world=state["world"],
                no_cache=state["no_cache"],
                allow_stale=allow_stale,
                job_levels=levels,
                min_price=min_price["value"],
                min_velocity=min_velocity["value"],
                on_progress=_on_progress,
            )
            table.rows = [
                {
                    "item_id": r["item_id"],
                    "name": r["name"],
                    "job": r["job"],
                    "level": r["level"],
                    "mb_price": r["mb_price"],
                    "velocity": r["velocity"],
                    "gil_per_day": r["gil_per_day"],
                    "bargain": (
                        f"{r['bargain']['world']}: {r['bargain']['price']:,} x{r['bargain']['qty']} (-{r['bargain']['discount_pct']}%)"
                        if r.get("bargain") else ""
                    ),
                    "last_updated": r.get("last_updated", 0),
                }
                for r in results
            ]
            table.update()
            progress_label.text = f"Done — {len(results)} crafting opportunities found"
        except Exception as e:
            progress_label.text = f"Error: {e}"
            ui.notify(f"Crafting scan failed: {e}", type="negative")
        finally:
            spinner.visible = False
            progress_bar.visible = False
            scan_btn.enable()

    scan_btn.on_click(with_cache_check(state, _run_scan))


def _build_seeds_panel(state: dict):
    stats_container = ui.column().classes("w-full p-2")

    def _refresh_stats():
        stats_container.clear()
        seeds = _load_seeds()
        with stats_container:
            if not seeds:
                ui.label("No seeds.json found. Run the seed scraper first.").classes("text-italic")
                return

            scraped_at = seeds.get("scraped_at", "unknown")
            ui.label(f"Last scraped: {scraped_at}").classes("text-subtitle2")
            ui.separator()

            workshop = seeds.get("workshop", {})
            total_workshop = sum(len(v) for v in workshop.values())
            ui.label(f"Workshop items: {total_workshop}").classes("text-body1")
            for sub, items in workshop.items():
                ui.label(f"  {sub}: {len(items)}").classes("text-body2 ml-4")

            ui.label(f"Vendor items: {len(seeds.get('vendor', []))}").classes("text-body1")
            ui.label(f"GC seal items: {len(seeds.get('gc_seal', []))}").classes("text-body1")
            ui.label(f"Popular crafts: {len(seeds.get('popular_crafts', []))}").classes("text-body1")

            discovered = seeds.get("discovered", [])
            if discovered:
                ui.label(f"Discovered items: {len(discovered)}").classes("text-body1")

    _refresh_stats()

    ui.separator()

    with ui.row().classes("items-center gap-4 p-2"):
        scrape_btn = ui.button("Refresh Seeds", icon="refresh")
        spinner = ui.spinner(size="lg")
        spinner.visible = False

    progress_label = ui.label("").classes("p-2")

    async def _run_scrape():
        scrape_btn.disable()
        spinner.visible = True
        progress_label.text = "Starting seed scraper..."

        def _on_progress(phase, total, msg):
            progress_label.text = f"Phase {phase}/{total}: {msg}"

        try:
            seeds = await run.io_bound(
                scrape_seeds.scan,
                dc=state["dc"],
                no_cache=state["no_cache"],
                on_progress=_on_progress,
            )
            scrape_seeds.save_seeds(seeds)
            reload_seeds()

            progress_label.text = "Seeds updated successfully!"
            ui.notify("Seeds refreshed!", type="positive")
            _refresh_stats()
        except Exception as e:
            progress_label.text = f"Error: {e}"
            ui.notify(f"Scrape failed: {e}", type="negative")
        finally:
            spinner.visible = False
            scrape_btn.enable()

    scrape_btn.on_click(_run_scrape)


def _can_use_native() -> bool:
    try:
        import webview
        # Check if a GUI backend is actually available (GTK or QT)
        from webview import guilib
        guilib.initialize()
        return True
    except Exception:
        return False


create_app()
if _can_use_native():
    ui.run(title="FFXIV Market Scanner", port=8080, reload=False, native=True)
else:
    ui.run(title="FFXIV Market Scanner", port=8080, reload=False)
