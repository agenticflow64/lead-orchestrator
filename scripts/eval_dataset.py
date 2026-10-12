"""Run docs/test-leads.md through the live classifier and print accuracy metrics.

Usage:
    set -a; source .env; set +a
    .venv/bin/python scripts/eval_dataset.py [--api] [--base-url http://localhost:8000]

Without --api it calls the classifier in-process (no HTTP server needed).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.classifier import classify, classify_by_rules  # noqa: E402


def load_dataset() -> list[dict]:
    rows = []
    for line in (ROOT / "docs" / "test-leads.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|(.*?)\|\s*(\w+)\s*\|\s*(\w+)\s*\|", line)
        if m:
            rows.append(
                {"num": int(m.group(1)), "text": m.group(2).strip(),
                 "expected_type": m.group(3), "expected_urgency": m.group(4)}
            )
    return rows


def classify_via_api(base_url: str, text: str) -> dict:
    import httpx

    update = {
        "update_id": 900000,
        "message": {
            "message_id": 1,
            "from": {"id": 1, "is_bot": False, "first_name": "Eval"},
            "chat": {"id": 1, "type": "private"},
            "date": int(time.time()),
            "text": text,
        },
    }
    t0 = time.monotonic()
    r = httpx.post(f"{base_url}/webhook/telegram", json=update, timeout=120)
    dt = time.monotonic() - t0
    r.raise_for_status()
    body = r.json()
    lead = httpx.get(f"{base_url}/api/leads", params={"type": body["type"]}, timeout=30).json()
    mine = max(lead, key=lambda x: x["id"])
    return {
        "type": mine["type"], "urgency": mine["urgency"], "name": mine["name"],
        "contact": mine["contact"], "summary": mine["summary"],
        "provider": mine["llm_provider"], "ms": int(dt * 1000),
    }


EXPECTED_FIELDS = {
    1: ("Александр", "a.petrov@company.ru"),
    2: ("Марина", "+7 912 345-67-89"),
    3: ("Дмитрий", ""),
    4: ("", "8 800 555-35-35"),
    5: ("Иван", "ivan@mail.ru"),
    6: ("Ольга", "+7 900 123-45-67"),
    7: ("", ""),
    8: ("", ""),
    9: ("Елена", ""),
    10: ("Сергей", ""),
    11: ("Роман", "roman@agency.dev"),
    12: ("", "@maketalk"),
    13: ("", ""),
    14: ("", ""),
    15: ("", ""),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", action="store_true", help="go through a running HTTP service")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--rules", action="store_true", help="evaluate the regex fallback instead of the LLM")
    args = parser.parse_args()

    dataset = load_dataset()
    results = []
    for row in dataset:
        t0 = time.monotonic()
        if args.api:
            prediction = classify_via_api(args.base_url, row["text"])
        elif args.rules:
            prediction = classify_by_rules(row["text"])
            prediction["provider"] = "rules"
            prediction["ms"] = int((time.monotonic() - t0) * 1000)
        else:
            prediction = classify(row["text"])
            prediction["ms"] = int((time.monotonic() - t0) * 1000)
        prediction["num"] = row["num"]
        prediction["expected_type"] = row["expected_type"]
        prediction["expected_urgency"] = row["expected_urgency"]
        results.append(prediction)
        marker = "ok" if prediction["type"] == row["expected_type"] else "MISS"
        print(
            f"#{row['num']:>2} [{marker}] type={prediction['type']:<15} urgency={prediction['urgency']:<7} "
            f"name={prediction['name']!r:<14} contact={prediction['contact']!r:<24} "
            f"provider={prediction['provider']} {prediction['ms']} ms"
        )

    n = len(results)
    type_ok = sum(r["type"] == r["expected_type"] for r in results)
    urg_ok = sum(r["urgency"] == r["expected_urgency"] for r in results)
    field_total = field_ok = 0
    for r in results:
        exp_name, exp_contact = EXPECTED_FIELDS[r["num"]]
        for predicted, expected in ((r["name"], exp_name), (r["contact"], exp_contact)):
            field_total += 1
            field_ok += predicted.strip().lower() == expected.strip().lower()
    summaries_ok = sum(1 for r in results if r["summary"].strip())
    avg_ms = sum(r["ms"] for r in results) / n

    per_type = {}
    for r in results:
        bucket = per_type.setdefault(r["expected_type"], [0, 0])
        bucket[1] += 1
        bucket[0] += r["type"] == r["expected_type"]

    print("\n=== METRICS (demo run) ===")
    print(f"type accuracy:        {type_ok}/{n} = {type_ok / n:.0%}")
    for t, (ok, total) in sorted(per_type.items()):
        print(f"  {t:<16} {ok}/{total}")
    print(f"urgency accuracy:    {urg_ok}/{n} = {urg_ok / n:.0%}")
    print(f"field extraction:    {field_ok}/{field_total} = {field_ok / field_total:.0%}")
    print(f"summary non-empty:   {summaries_ok}/{n}")
    print(f"avg classification:  {avg_ms:.0f} ms (provider mix: {sorted({r['provider'] for r in results})})")

    out = ROOT / "data" / "eval_results.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"raw results: {out}")


if __name__ == "__main__":
    main()
