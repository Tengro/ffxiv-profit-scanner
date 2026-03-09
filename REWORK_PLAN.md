# Scanner Rework Plan — Mode Consolidation

## Summary

Restructure scan modes around the player's actual workflow: "what can I do with my
character to make money?" Each mode corresponds to a real activity, is world-specific
(you sell where you play), and level-gated (you can only do what your class can do).

## Changes Overview

| Current | After | Notes |
|---------|-------|-------|
| Craft (workshop-only seeds) | **Workshop** (FC workshop items only) | Small, static category — keep simple |
| Discover (all marketable → craftable) | **Crafting** (by class + level) | Like gather: "CUL 90, WVR 80" → what can I profitably craft? |
| Cross-World | **Shelved** | Remove from GUI + TCS for now |
| Vendor Arbitrage | **Vendor** (world-specific) | Already mostly world-first, clean up DC fallback |
| Gather | *(unchanged)* | Already world-specific after recent fix |
| Hunter | *(new, just added)* | Already world-specific |

## Detailed Plan

### 1. Shelve Cross-World

**Old scanner (NiceGUI):**
- Remove Cross-World tab from `app.py`
- Keep `scanner/modes/cross_world.py` file (don't delete — just unplug from UI)
- Remove from CLI choices in `ffxiv_scanner.py`

**TCS:**
- Remove Cross-World page from frontend router + sidebar
- Remove `cross_world` from scheduler scan modes
- Keep backend scan mode code + API endpoint (just stop calling it)
- Remove `CrossWorldResult` from frontend types (or leave unused)

### 2. Workshop Tab (rename current Craft)

Minimal change — the current craft scan already works with workshop seed IDs.

**Old scanner:**
- Rename "Craft" tab → "Workshop" in `app.py`
- Make it world-specific: pass `world` as price target instead of DC
  - Currently: fetches DC-wide ingredient prices, then optional world-specific finished item prices
  - After: fetch world-specific for everything (same as gather/hunter approach)
- Keep the ingredient breakdown display

**TCS:**
- Rename `/craft` → `/workshop` in router
- Update sidebar label + icon

### 3. New Crafting Tab (replaces Discover)

Same pattern as gather/hunter — "given my class levels, what can I profitably craft?"

**Flow (implemented — simplified, no margin calc):**
1. Get all marketable item IDs from Universalis
2. Lightweight price scan (world-specific) → filter by velocity only
3. Check Garland for each candidate → keep if craftable with matching job + level
   - Recipe data: `item.craft[0].job` (8=CRP, 9=BSM, 10=ARM, 11=GSM, 12=LTW, 13=WVR, 14=ALC, 15=CUL)
   - Recipe data: `item.craft[0].lvl` (recipe level)
   - Cache result permanently under `garland` namespace (like hunter)
4. Full outlier-resistant price fetch for craftable items
5. Filter by min_price + min_velocity, sort by gil/day (price × 0.95 × velocity)

*Note: Full margin calculation (ingredient costs) deferred to TCS.*

**UI inputs (old scanner):**
- CRP / BSM / ARM / GSM / LTW / WVR / ALC / CUL level inputs (0 = skip, like gather jobs)
- Min price, Min velocity, Min margin %
- Sort by: profit/day or margin%

**Key difference from current Discover:**
- Level-gated (not "scan everything above 50k")
- World-specific prices throughout (not DC → world refinement)
- Velocity-only pre-filter at step 2 (outlier-resistant price check at step 5)
- No seed saving — the Garland cache handles item data persistence

**FFXIV Craft Job IDs:**
```
8  = CRP (Carpenter)
9  = BSM (Blacksmith)
10 = ARM (Armorer)
11 = GSM (Goldsmith)
12 = LTW (Leatherworker)
13 = WVR (Weaver)
14 = ALC (Alchemist)
15 = CUL (Culinarian)
```

### 4. Vendor Arbitrage — World-Specific

**Current state:** Already uses `world or dc` (line 19 of vendor_arbitrage.py).
If world is provided, it's already world-specific.

**Changes:**
- Old scanner UI: ensure world is always passed (it already is via `state["world"]`)
- Remove DC-only fallback messaging — just always show world in header
- TCS: ensure frontend always sends world param

Minimal code change — mostly cosmetic.

### 5. TCS Alignment

After old scanner changes are tested, mirror to TCS:

**Backend:**
- Add `hunter` scan mode to scheduler + API
- Rename `craft` → `workshop` scan mode
- Replace `discover` with new `crafting` scan mode (level-gated)
- Remove `cross_world` from scheduler (keep endpoint for backwards compat)
- All modes use world-specific pricing

**Frontend:**
- Remove Cross-World page
- Rename Craft → Workshop
- Add Hunter page (same columns as gather minus job/level/location)
- Add Crafting page (same columns as current craft, plus crafter job column)
- Update dashboard cards

**API models:**
- Add `HunterResult` Pydantic model
- Add `CraftingResult` (like CraftResult but with `craft_job` field)
- Keep `CraftResult` as `WorkshopResult` (or just rename)

## Implementation Order

1. ~~**Old scanner: Shelve cross-world** — remove tab + CLI entry~~ ✅ DONE
2. ~~**Old scanner: Rename Craft → Workshop** — cosmetic rename, ensure world-specific~~ ✅ DONE
3. ~~**Old scanner: New Crafting mode** — the big one, follows hunter scan pattern~~ ✅ DONE (simplified: price/velocity only, no margin calc)
4. ~~**Old scanner: Vendor world-specific cleanup** — minor~~ ✅ DONE (already world-specific)
5. ~~**Test all modes end-to-end** on old scanner~~ ✅ DONE (all modes tested live)
6. ~~**TCS: Mirror changes** — backend modes, frontend pages, API models~~ ✅ DONE

## Files to Modify (Old Scanner)

| File | Change |
|------|--------|
| `app.py` | Remove Cross-World tab, rename Craft → Workshop, add Crafting tab |
| `ffxiv_scanner.py` | Remove `cross-world` choice, add `crafting` choice, rename `craft` → `workshop` |
| `scanner/modes/craft_scan.py` | Rename to `workshop_scan.py` or just update to be world-specific |
| `scanner/modes/discover.py` | Replace with new `crafting_scan.py` (level-gated) |
| `scanner/api/garland.py` | Add `check_craftable_items()` helper (like `check_hunting_items()`) |
| `scanner/output.py` | Add `print_crafting_result()` if needed |

## Files to Modify (TCS)

| File | Change |
|------|--------|
| `backend/scheduler.py` | Update scan modes dict |
| `backend/api/routers/scans.py` | Add HunterResult, CraftingResult models; rename CraftResult → WorkshopResult |
| `backend/scanner/modes/` | Mirror old scanner changes |
| `frontend/src/router.tsx` | Update routes |
| `frontend/src/pages/` | Add hunter.tsx, crafting.tsx; rename craft.tsx → workshop.tsx; remove cross-world.tsx |
| `frontend/src/components/layout/sidebar.tsx` | Update nav items |
| `frontend/src/types/api.ts` | Update result types |
| `TODO.md` | Update roadmap |
