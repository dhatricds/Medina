# BUGLOG.md - Medina Debug & Investigation Log

Chronological record of bugs discovered, root cause analysis, and fixes applied.
Use this to identify patterns and avoid regressions.

---

## BUG-001: A1 fixture undercounted by 2 on HCMC E200

**Date:** 2026-02-16
**Project:** HCMC (`sample/HCMC/24031_15_Elec.pdf`, page 5 = E200)
**Symptom:** Pipeline reports A1 = 46, ground truth = 48 (missing 2)
**Severity:** Medium — affects count accuracy

### Root Cause

`pdfplumber.extract_words(x_tolerance=3)` splits "A1" into two separate words `"A"` and `"1"` at 2 specific locations on the page where the inter-character gap slightly exceeds the 3px tolerance.

**Evidence:**
- Character-level extraction (`page.chars`) finds **48** A→1 pairs — exact match with ground truth
- Word-level extraction (`page.extract_words()`) finds only **46** "A1" words
- The 2 missing labels are at:
  - `x=956.5, y=595.8` — "A" and "1" extracted as separate words
  - `x=1082.5, y=593.7` — "A" and "1" extracted as separate words
- Same font (GMBJZH+Arial, 9.6pt) as all other A1 labels — just slightly wider kerning

### Affected Code

- `src/medina/plans/text_counter.py` — `_extract_plan_words()` uses `extract_words(x_tolerance=3)`
- Word-level regex matching in `_count_word_matches_filtered()` and concatenated-text matching both miss split words

### Proposed Fix

Switch from word-level regex matching to **character-level pair detection**:
1. Use `page.chars` to find letter+digit pairs that form fixture codes
2. Check that characters are adjacent (small dx, small dy)
3. Apply same exclusion zone filtering (title block, border, schedule table bbox)
4. Add font size filtering to reject non-fixture text (see BUG-002)

### Status: FIXED (2026-02-16) — character-level counting in `text_counter.py`

---

## BUG-002: E3 fixture overcounted by 1 on HCMC E200

**Date:** 2026-02-16
**Project:** HCMC (`sample/HCMC/24031_15_Elec.pdf`, page 5 = E200)
**Symptom:** Pipeline reports E3 = 5, ground truth = 4 (1 extra)
**Severity:** Medium — affects count accuracy

### Root Cause

Structural **grid line label** "E3" at the top of the floor plan is counted as a fixture. The page has architectural column grid labels across the top: `EW, E1, E2, E3, E4, E5, E6, E7, E8, E9, E10, E11`.

**Evidence:**
- 5 word-level "E3" matches found:
  1. `x=555.4, y=62.2, font_size=21.6pt` — **GRID LINE LABEL** (false positive)
  2. `x=934.0, y=362.4, font_size=9.6pt` — real fixture
  3. `x=1368.8, y=458.3, font_size=9.6pt` — real fixture
  4. `x=1087.3, y=755.1, font_size=9.6pt` — real fixture
  5. `x=1311.0, y=1184.1, font_size=9.6pt` — real fixture
- Grid labels are **21.6pt** — over 2x the size of fixture labels (9.6pt)
- Grid labels form a clear sequence: EW, E1, E2, E3, E4... evenly spaced across page top

### Affected Code

- `src/medina/plans/text_counter.py` — no font size filtering in `_count_word_matches_filtered()`
- Exclusion zones (title block, border) don't cover the grid line area at page top

### Proposed Fix

**Font size filtering:**
1. During character-level counting, record font height (`size` or `height` from char dict) for each match
2. Compute the **modal font size** across all fixture code matches (should be ~9.6pt for HCMC)
3. Reject matches whose font size deviates significantly (e.g., >1.5x the modal size)
4. This naturally filters grid labels (21.6pt), title text, and other large annotations

This mirrors the approach already used successfully for keynote counting in `plans/keynotes.py` (modal `font_h` filtering).

### Status: FIXED (2026-02-16) — modal font-size filter in `_apply_font_size_filter()`

---

## BUG-003: Short fixture codes (A, B, C, D) overcount on Anoka

**Date:** 2026-02-16 (documented from earlier validation)
**Project:** Anoka Dispensary (`sample/Anoka Dispensary/...`, page E301)
**Symptom:** Single-letter codes overcount — A=17 vs GT 14, B=11 vs GT 10, C=3 vs GT 2
**Severity:** Medium

### Root Cause

Single-character fixture codes like "A", "B", "C" match room labels, keynote references, and other standalone letters on the plan page. The regex `(?<![A-Za-z0-9])A(?![A-Za-z0-9])` correctly enforces word boundaries but can't distinguish a fixture label "A" from a room label "A" by text alone.

### Affected Code

- `src/medina/plans/text_counter.py` — `_build_code_pattern()` and matching logic
- No spatial or font-based disambiguation for single-character codes

### Proposed Fix

Combine multiple signals:
1. **Font size filtering** (same as BUG-002) — fixture labels should cluster at a consistent size
2. **Proximity to fixture symbols** — fixture codes appear near circle/rectangle drawing symbols
3. **Spatial clustering** — fixture codes on a lighting plan tend to be in the floor plan area, not in room label positions
4. **Vision fallback for short codes only** — use LLM specifically for 1-2 char codes where text ambiguity is highest

### Status: OPEN — needs investigation with character-level approach first

---

## BUG-004: Variable shadowing — `plan_codes` overwritten in pipeline.py

**Date:** 2026-02-15 (fixed)
**Project:** All projects
**Symptom:** Fixture counting skipped or wrong plans counted
**Severity:** High — affected all projects

### Root Cause

In `pipeline.py`, the variable `plan_codes` (list of lighting plan sheet codes) was being overwritten by the cross-reference filtering logic that checks if fixture codes match plan sheet codes. After the loop, `plan_codes` contained fixture codes instead of plan codes.

### Fix Applied

Renamed the variable to `found_plan_codes` to avoid shadowing.

### Status: FIXED

---

## BUG-005: VLM keynote counting unreliable (0 to 24 for same image)

**Date:** 2026-02-14 (documented from testing)
**Project:** HCMC E200
**Symptom:** Claude Vision API returns wildly different keynote counts across runs for the same image
**Severity:** Critical — made VLM unusable as primary counting method

### Root Cause

Small numbers inside geometric shapes (diamonds/hexagons) on engineering drawings are difficult for vision models. The model:
- Confuses circuit numbers (bare numbers near wiring) with keynote symbols
- Is inconsistent across runs due to sampling randomness
- Copies values from few-shot examples in prompts (example biasing)

### Fix Applied

Switched to **geometric shape detection** using pdfplumber line geometry as primary method:
1. Detect numbers enclosed by line endpoints in all 4 quadrants (TR, BR, BL, TL)
2. Two-step filtering: modal font_h from 4-quadrant candidates, then include 3-quadrant with matching font_h
3. VLM only used as fallback when geometric detection returns all zeros

**Validated:** Exact match on HCMC (#1=6, #2=1, #3=1) and Anoka (#1=4, #2=1).

### Status: FIXED — geometric detection is primary, VLM is last-resort fallback

---

## BUG-006: pdfplumber `extract_words()` x_tolerance sensitivity

**Date:** 2026-02-16 (identified during BUG-001 investigation)
**Project:** General — affects any PDF
**Symptom:** Fixture codes split into individual characters when inter-character gap exceeds tolerance
**Severity:** Medium — systemic issue underlying BUG-001

### Root Cause

`extract_words(x_tolerance=3)` uses a fixed pixel threshold to decide when adjacent characters form a word. Engineering PDFs have variable kerning — some labels have slightly wider gaps between letters and digits. Increasing x_tolerance risks merging separate nearby labels into one word.

### Key Insight

**Character-level extraction (`page.chars`) is 100% reliable** — it always returns every character with its exact position, font, and size. The word grouping step is where information is lost. For short fixture codes (1-3 chars), character-level pair detection is more robust than word-level regex.

### Proposed Fix

For fixture counting, bypass `extract_words()` entirely:
1. Use `page.chars` directly
2. Find character sequences that match fixture code patterns (letter(s) + digit(s))
3. Validate adjacency (dx < threshold, dy < threshold)
4. Apply font size modal filtering (from BUG-002)
5. Apply exclusion zone filtering (title block, border, schedule table)

### Status: FIXED (2026-02-16) — `_find_char_sequences()` replaces `extract_words()` for counting

---

## BUG-007: Boundary check false rejection due to content-stream order

**Date:** 2026-02-16
**Project:** Anoka Dispensary E301
**Symptom:** F = 6 (should be 7) — one legitimate fixture rejected by boundary check
**Severity:** Medium

### Root Cause

The character-level boundary check used `dx < _BOUNDARY_GAP` to detect adjacent
alphanumeric characters. But `page.chars` is ordered by content stream, not spatially.
A character from a completely different area of the page could have a large negative dx
(e.g., -357.5) which still satisfies `dx < 5.0`.

**Evidence:**
- F at x=415.1, y=590.1 (legitimate fixture label, 8.0pt)
- Previous char in content stream: '6' at x=768.2 (dx = -357.5)
- `-357.5 < 5.0` evaluates True, so the F was incorrectly rejected

### Fix Applied

Changed boundary checks from `dx < _BOUNDARY_GAP` to `abs(dx) < _BOUNDARY_GAP`.
This correctly rejects only characters that are truly spatially adjacent.

### Status: FIXED (2026-02-16)

---

## BUG-008: Keynote/notes text counted as fixture labels

**Date:** 2026-02-16
**Project:** DENIS-1266, Anoka Dispensary
**Symptom:** Every fixture code mentioned in KEY NOTES text adds +1 false count per page. Anoka also matched engineer certification text ("I AM **A** DULY", "PHILIP **C.** HAIGHT").
**Severity:** Medium — +1 per fixture type per page with keynotes

### Root Cause

The KEY NOTES and NOTES sections occupy the right ~15% of the page (x > 85% of page width). They contain fixture code references within text descriptions like:
- "WALL MOUNT LIGHT FIXTURE TYPE **'AL1'** AND **'AL1E'** AT 10'-0"..."
- "PENDANT MOUNT TYPE **'AL4'** LIGHTING FIXTURE AT 9'-9"..."

The exclusion zone only filtered the **bottom-right corner** (x > 80% AND y > 85%), not the full right-side notes column. Quote characters (`'`) around fixture codes didn't trigger the alphanumeric boundary check, so the matches passed through.

On Anoka, the engineer certification stamp and printed name ("PHILIP C. HAIGHT") also fell in this zone, matching single-letter fixture codes A and C.

**Evidence (DENIS-1266 Page 10):**
- AL1 at x=2305 (94.2% of width): from keynote 5 text "'AL1'"
- AL2 at x=2238 (91.4% of width): from keynote 1 text "'AL2'"
- AL4 at x=2251 (92.0% of width): from keynote 4 text "'AL4'"
- EX1 at x=2329 (95.1% of width): from keynote 2 text "'EX1'"

### Fix Applied

Added a `_LEGEND_COL_X_FRAC = 0.85` constant and a legend column exclusion zone in `_is_in_exclusion_zone()`. Any match at x > 85% of page width (at any y) is now excluded. This covers notes, keynotes, engineer stamps, and title block text.

**Impact verification:**
- HCMC: zero matches in right zone — no change
- Anoka: A 16→15 (GT=14, closer), C 3→2 (GT=2, exact match)
- DENIS-1266: all keynote text false positives removed (AL2 0→0, WL1 1→0, etc.)

### Status: FIXED (2026-02-16)

---

## BUG-009: Panel schedule entries extracted as fixture codes (DENIS 12C9)

**Date:** 2026-02-16
**Project:** DENIS DENIS-2025-12C9(639033657691230107)
**Symptom:** Pipeline extracted 35 panel circuit numbers (1, 3, 5, 7...) with descriptions like "EXIST. DATA RECEPTACLES" as fixture codes. The LIGHT FIXTURE SCHEDULE (3 rows with F1) was ignored.
**Severity:** High — completely wrong fixture inventory

### Root Cause

`_is_luminaire_table()` in `parser.py` checks first 3 rows for exclude keywords like "panel schedule" and "panelboard". However, panel schedule tables have headers like "PANEL A" or "PANEL B" — these don't match any exclude keyword. The function falls through to `return True` (ambiguous → allow).

The parser then maps "CIRCUIT DESCRIPTION" → description column and "VA" → max_va column, and circuit numbers pass `_is_data_row()` since they're short alphanumeric values.

### Fix Applied

1. Added `"circuit description"` to `_NON_LUMINAIRE_TABLE_KEYWORDS`
2. Added `_PANEL_HEADER_RE` regex to catch "PANEL A/B/C/LP-1" patterns
3. Added `_looks_like_panel_schedule()` post-parse validation: rejects tables where >60% of codes are purely numeric AND >5 entries
4. Added same validation to VLM extractor output

### Status: FIXED (2026-02-16)

---

## BUG-010: E0.0 symbols page misclassified as "schedule" (DENIS 12E2)

**Date:** 2026-02-16
**Project:** DENIS DENIS-2025-12E2(639033655256888596)
**Symptom:** Page 1 (E0.0) classified as "schedule" instead of "cover/symbols_legend". Garbage entries "UG" and "b" extracted from symbols/abbreviations tables alongside real fixtures from E4.1.
**Severity:** High — pollutes fixture inventory with non-fixture entries

### Root Cause

The title block crop area `(width*0.55, height*0.80)` was too large and captured the **sheet index listing** (which is just above the actual title block on E0.0 pages). The listing contained "ELECTRICAL SCHEDULES" (from E4.1/E4.2 descriptions), which matched the schedule keyword in `_TITLE_KEYWORDS`. Since the title block check (Priority 2) runs before prefix rules (Priority 3, which would correctly map E0.0 → SYMBOLS_LEGEND), the page was misclassified.

### Fix Applied

1. Tightened the title block crop from `height*0.80` to `height*0.85` — captures only the actual title block, not the sheet index listing above it
2. Moved symbols/legend keyword check before schedule check in `_TITLE_KEYWORDS` priority order
3. Verified no regressions across HCMC, Anoka, DENIS 1266, DENIS 12C9

### Status: FIXED (2026-02-16)

---

## BUG-011: VLM schedule fallback too restrictive

**Date:** 2026-02-16
**Project:** DENIS DENIS-2025-12C9(639033657691230107)
**Symptom:** After fixing BUG-009 (panel schedule rejection), pdfplumber returns 0 fixtures. VLM fallback should trigger but doesn't because the page has 1705 text words and no large raster images.
**Severity:** Medium — prevents VLM from extracting non-standard luminaire schedules

### Root Cause

VLM fallback in `run_schedule.py` and `pipeline.py` was gated by `has_image_based_content()` or `has_minimal_text()`. Pages with text-layer tables (non-standard format) that pdfplumber can detect but can't parse column headers were never sent to VLM.

### Fix Applied

Removed the `is_image or is_sparse` guard. VLM now triggers for **any** schedule page when pdfplumber extracts 0 fixtures. The `_looks_like_panel_schedule()` filter in the VLM extractor prevents panel schedule entries from being accepted.

### Status: FIXED (2026-02-16)

---

## PATTERN: Font size as a disambiguation signal

**Discovered:** 2026-02-16
**Applies to:** BUG-002, BUG-003, BUG-006

Fixture labels on engineering drawings have a **consistent, relatively small font size** (e.g., 9.6pt on HCMC). Other text elements that produce false matches are typically much larger:

| Text Type | Example | Font Size | Should Count? |
|-----------|---------|-----------|---------------|
| Fixture label | A1, E3, B6 | ~9.6pt | Yes |
| Grid line label | E1, E2, E3... | ~21.6pt | No |
| Room label | A, B, 101 | ~12-18pt | No |
| Title text | LIGHTING PLAN | ~18-24pt | No |
| Keynote symbol | 1, 2, 3 | ~6-8pt | No (separate counting) |

**Strategy:** Compute the modal font size across all fixture code character matches, then reject outliers. This is the same approach that works for keynote counting (`plans/keynotes.py`).

---

## PATTERN: Character-level > Word-level for short codes

**Discovered:** 2026-02-16
**Applies to:** BUG-001, BUG-003, BUG-006

For fixture codes that are 1-4 characters (which is nearly all of them), character-level extraction from `page.chars` is strictly more reliable than `extract_words()`:

- **Never splits codes** — characters always exist individually
- **Provides font metadata** — size, fontname per character (words don't)
- **Exact positions** — sub-pixel accuracy for spatial filtering
- **No tolerance tuning** — adjacency check is explicit, not implicit

Trade-off: requires building the "word grouping" logic ourselves for fixture codes specifically, but the logic is simple (find letter+digit sequences within distance thresholds).
