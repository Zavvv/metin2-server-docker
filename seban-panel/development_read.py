"""Read compact core snapshots without interpreting logs or changing AI policy."""
import csv
import time
from collections import Counter, defaultdict

STATES = ("NO_PROJECT", "SAVING", "MATERIAL_MISSING", "OFFER_UNREACHABLE",
          "RISK_BLOCKED", "WAITING_READY", "TRAVELLING", "AT_SMITH")


def read_development(paths, now=None):
    now = time.time() if now is None else now
    selected = {}
    for channel, path in paths:
        try:
            modified = path.stat().st_mtime
            if now - modified > 180 or modified > now + 30:
                continue
            with path.open(encoding="ascii", errors="strict", newline="") as source:
                for row in csv.DictReader(source, delimiter="\t"):
                    try:
                        pid, level, profile = (int(row[k]) for k in ("pid", "level", "profile"))
                        if pid <= 0 or not 1 <= level <= 255 or not 0 <= profile < 4 or row["state"] not in STATES:
                            continue
                        parsed = dict(row, pid=pid, level=level, profile=profile, channel=int(channel),
                                      weapon_plus=int(row["weapon_plus"]), body_plus=int(row["body_plus"]),
                                      material=int(row["material"]), budget=max(0, int(row["budget"])))
                        if pid not in selected or modified > selected[pid][0]:
                            selected[pid] = (modified, parsed)
                    except (KeyError, ValueError, TypeError):
                        continue
        except (OSError, UnicodeError):
            continue
    bots = [entry[1] for entry in selected.values()]
    states, profiles, missing = Counter(), Counter(), Counter()
    groups = defaultdict(lambda: {"count": 0, "weapon": [], "body": []})
    for row in bots:
        states[row["state"]] += 1
        profiles[row["profile"]] += 1
        if row["material"] and row["state"] in ("MATERIAL_MISSING", "OFFER_UNREACHABLE"):
            missing[row["material"]] += 1
        group = groups["1–34" if row["level"] < 35 else "35–54" if row["level"] < 55 else "55+"]
        group["count"] += 1
        for key in ("weapon", "body"):
            plus = row[key + "_plus"]
            if 0 <= plus <= 9:
                group[key].append(plus)
    return {"count": len(bots), "states": {s: states[s] for s in STATES},
            "profiles": [profiles[i] for i in range(4)], "missing": missing.most_common(10),
            "groups": [{"level": level, "count": group["count"],
                        "weapon": round(sum(group["weapon"]) / len(group["weapon"]), 2) if group["weapon"] else None,
                        "body": round(sum(group["body"]) / len(group["body"]), 2) if group["body"] else None}
                       for level, group in sorted(groups.items())]}


def read_reset(paths, request):
    done = total = 0
    active = failed = False
    seen = 0
    for _, path in paths:
        try:
            with path.open(encoding="ascii", newline="") as source:
                row = next(csv.DictReader(source, delimiter="\t"), {})
            if (row.get("request") != request or not request or
                    time.time()-int(row.get("updated_unix",0))>180):
                continue
            seen += 1
            failed |= row.get("failed") == "1"
            done += max(0, int(row["done"]))
            total += max(0, int(row["total"]))
            active |= row.get("active") == "1"
        except (OSError, ValueError, KeyError, UnicodeError):
            continue
    return {"done": done, "total": total, "active": active, "failed": failed,
            "state": "error" if failed else "running" if active else "complete" if seen else "waiting"}
