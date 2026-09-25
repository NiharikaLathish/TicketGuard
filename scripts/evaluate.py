"""Score fraud detection against the generator's ground truth and time each detector.

    python -m scripts.evaluate      (writes dumps/evaluation.json)
"""
import json
import time
from pathlib import Path

from app import detection

ROOT = Path(__file__).resolve().parent.parent


def score(found: set, expected: set) -> dict:
    tp = len(found & expected)
    p = tp / len(found) if found else 0.0
    r = tp / len(expected) if expected else 0.0
    return {"expected": len(expected), "found": len(found), "true_positives": tp,
            "precision": round(p, 3), "recall": round(r, 3)}


def timed(fn):
    t0 = time.time()
    out = fn()
    return out, round(time.time() - t0, 2)


def main():
    truth = json.loads((ROOT / "dumps" / "ground_truth.json").read_text())
    res = {}

    cyc, t = timed(detection.detect_cycles)
    res["circular_resale"] = {**score({a for c in cyc for a in c["accounts"]},
                                      {a for ring in truth["circular_resale"] for a in ring}), "seconds": t}
    com, t = timed(detection.detect_communities)
    res["bot_ring"] = {**score({a for c in com for a in c["accounts"]},
                               {a for ring in truth["bot_ring"] for a in ring}), "seconds": t}
    hub, t = timed(detection.detect_hubs)
    res["hub_account"] = {**score({h["account_id"] for h in hub}, set(truth["hub_account"])), "seconds": t}
    pri, t = timed(lambda: detection.detect_pricing(limit=5000))
    res["price_manipulation"] = {**score({p["ticket_id"] for p in pri}, set(truth["price_manipulation"])), "seconds": t}

    (ROOT / "dumps" / "evaluation.json").write_text(json.dumps(res, indent=1))
    print(f"{'pattern':20} {'expected':>8} {'found':>6} {'precision':>10} {'recall':>7} {'secs':>6}")
    for k, v in res.items():
        print(f"{k:20} {v['expected']:>8} {v['found']:>6} {v['precision']:>10} {v['recall']:>7} {v['seconds']:>6}")


if __name__ == "__main__":
    main()
