"""Regression tests for the 5 training PDFs."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from medina.team.orchestrator import run_team


def run_test(name, source, work_dir, expected_fixtures, expected_keynotes, needs_vlm=False):
    print("=" * 60)
    print(f"TEST: {name}")
    print("=" * 60)

    if needs_vlm:
        from medina.config import get_config
        cfg = get_config()
        if not cfg.anthropic_api_key:
            print("SKIPPED (no API key for VLM)")
            return True

    t0 = time.time()
    try:
        result = run_team(source, work_dir)
    except Exception as e:
        print(f"FAILED: {e}")
        return False
    elapsed = time.time() - t0

    json_path = Path(work_dir + ".json")
    if not json_path.exists():
        print(f"FAILED: output JSON not found at {json_path}")
        return False

    with open(json_path) as f:
        data = json.load(f)

    fixtures = data["fixtures"]
    keynotes = data["keynotes"]
    total = sum(f["total"] for f in fixtures)
    print(f"Time: {elapsed:.1f}s")
    print(f"Fixtures: {len(fixtures)} types, {total} total")
    print(f"Keynotes: {len(keynotes)}")

    ok = True

    # Validate fixture counts
    fixture_map = {f["code"]: f["total"] for f in fixtures}
    for code, exp_count in expected_fixtures.items():
        got = fixture_map.get(code)
        if got is None:
            print(f"  MISS: fixture {code} not found (expected {exp_count})")
            ok = False
        elif got != exp_count:
            print(f"  DIFF: {code}: got {got}, expected {exp_count}")
            ok = False

    if ok:
        print("  Fixtures: ALL MATCH")

    # Validate keynotes
    kn_map = {str(kn["keynote_number"]): kn["total"] for kn in keynotes}
    kn_ok = True
    for num, exp_count in expected_keynotes.items():
        got = kn_map.get(str(num))
        if got is None:
            print(f"  MISS: keynote #{num} not found (expected {exp_count})")
            kn_ok = False
        elif got != exp_count:
            print(f"  DIFF: keynote #{num}: got {got}, expected {exp_count}")
            kn_ok = False

    if kn_ok:
        print("  Keynotes: ALL MATCH")

    qa = data.get("qa_report", {})
    print(f"  QA: {qa.get('overall_confidence', 0):.1%}")
    print()

    return ok and kn_ok


def main():
    all_pass = True

    # Test 1: HCMC - 13 fixtures, keynotes #1=6,#2=1,#3=1
    ok = run_test(
        "HCMC (24031_15_Elec)",
        "train/24031_15_Elec.pdf",
        "output/test_hcmc",
        {"A1": 48, "A6": 14, "B1": 4, "B6": 26, "C4": 1, "D6": 8,
         "D7": 1, "E3": 4, "E4": 3, "L5": 3, "U2": 2, "U3": 7, "U4": 4},
        {"1": 6, "2": 1, "3": 1},
    )
    all_pass = all_pass and ok

    # Test 2: DENIS-11CD - 0 fixtures, 0 keynotes, 3 plans
    ok = run_test(
        "DENIS-11CD",
        "train/DENIS DENIS-2025-11CD(639033655788547115).pdf",
        "output/test_11cd",
        {},  # No schedule -> 0 fixtures
        {},  # 0 keynotes
    )
    all_pass = all_pass and ok

    # Test 3: DENIS-1220 - 2 fixtures, 4 keynotes
    ok = run_test(
        "DENIS-1220",
        "train/DENIS DENIS-2025-1220(639033657190693031).pdf",
        "output/test_1220",
        {"R1": 11, "S3": 30},
        {"1": 1, "2": 6, "3": 1, "4": 3},
    )
    all_pass = all_pass and ok

    # Test 4: DENIS-12E2 - 5 fixtures, 57 total
    ok = run_test(
        "DENIS-12E2",
        "train/DENIS DENIS-2025-12E2(639033655256888596).pdf",
        "output/test_12e2",
        {"A6": 45, "B1": 2, "D6": 8, "E1": 2, "F4": 0},
        {},  # keynotes vary
    )
    all_pass = all_pass and ok

    # Test 5: DENIS-1266 (VLM required) - 14 fixtures, 32 total
    ok = run_test(
        "DENIS-1266 (VLM)",
        "train/DENIS DENIS-2025-1266(639033656633682925).pdf",
        "output/test_1266",
        {},  # VLM fixture codes vary, just check it doesn't crash
        {},
        needs_vlm=True,
    )
    all_pass = all_pass and ok

    print("=" * 60)
    if all_pass:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 60)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
