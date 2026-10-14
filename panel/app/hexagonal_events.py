# =============================================================================
#  The Hexagonal Chest event, the panel's half (Kiciamol, 14 October).
#
#  While the event runs, a person's Metin stone may drop the hexagonal chest
#  of the map it was broken on; opening one gives a single refine material of
#  that map, every material of the pool at the same odds. The game's half is
#  quest/m2_hexagonal_event.lua and hexagonal_event.quest in the mt2009 image
#  (the kill handler, the map table) and the chest groups the image appends
#  to special_item_group.txt (special_item_group.hexagonal.txt); the chests
#  55000-55020 are the migrator's rows (hexagonal_world.sql), and 50037, the
#  package's own Hexagonal Treasure Chest, is the M1 one.
#
#  The event is a kind of the panel's /events page like the Moonlight chests
#  ("activate now", stop, weekly windows), but no core's playerbot_events.h
#  knows it: the quest reads a file of its own, hexagonal_event.tsv in the
#  spool, every five seconds at most and fails closed on anything it cannot
#  read (no chance, no drop). This module writes that file from the events'
#  rows and lines and the chance kept beside it, hexagonal_settings.json:
#
#      M2HEX1
#      chance<TAB><permille 0..1000>
#      now<TAB><until epoch>                  an "activate now" line
#      weekly<TAB><days 1..7,...><TAB><from minute><TAB><to minute>
#
#  A window whose end is not after its start runs over midnight. The chance
#  alone never starts the event; a world that never saved one reads 20%, a
#  saved file the panel cannot read reads 0% (a corrupt setting must not
#  quietly enable a drop). Each core answers with hexagonal_event_status.tsv
#  in its own directory (M2HEX1, written, active, permille, kills, drops).
# =============================================================================
import glob
import json
import os
import tempfile
import time
from decimal import Decimal, InvalidOperation

KIND = "hexagonal"
DEFAULT_PERMILLE = 200
SETTINGS_FILE = "hexagonal_settings.json"
STATE_FILE = "hexagonal_event.tsv"
STATUS_FILE = "hexagonal_event_status.tsv"
CATALOG_FILE = "hexagonal_catalog.json"
STATUS_GLOB = "/opt/metin2/var/channel*/*/" + STATUS_FILE
# A core whose answer is older than this is not counted as running the quest.
STATUS_FRESH_SECONDS = 120


class ChanceError(ValueError):
    """A chance the panel refuses; .key names the page's text for it."""

    def __init__(self, key):
        ValueError.__init__(self, key)
        self.key = key


def chance_permille(value):
    """'12,5' or '12.5' -> 125. 0..100 in steps of 0.1, else ChanceError."""
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise ChanceError("hex_chance_bad")
    if not number.is_finite() or not Decimal(0) <= number <= Decimal(100):
        raise ChanceError("hex_chance_range")
    units = number * 10
    if units != units.to_integral_value():
        raise ChanceError("hex_chance_step")
    return int(units)


def percent_text(permille):
    return "%g" % (permille / 10.0)


def atomic_write(path, text):
    """Written beside and renamed over: the cores read on their own clock."""
    directory = os.path.dirname(path) or "."
    fd, temporary = tempfile.mkstemp(prefix=".hexagonal_", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # The game's account reads the shared spool through its group.
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_settings(spool):
    """{'permille', 'percent', 'saved'}: 20% while nothing was saved, 0% for
    a file that cannot be read."""
    saved = True
    try:
        with open(os.path.join(spool, SETTINGS_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        value = data["permille"]
        if type(value) is not int or not 0 <= value <= 1000:
            raise ValueError("invalid stored chance")
    except FileNotFoundError:
        value, saved = DEFAULT_PERMILLE, False
    except (OSError, ValueError, KeyError, TypeError):
        value = 0
    return {"permille": value, "percent": percent_text(value), "saved": saved}


def save_settings(spool, value):
    permille = chance_permille(value)
    atomic_write(os.path.join(spool, SETTINGS_FILE),
                 json.dumps({"format": 1, "permille": permille}) + "\n")
    return permille


def hhmm(value):
    parts = str(value).split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError("invalid time")
    hour, minute = map(int, parts)
    if not 0 <= hour <= 24 or not 0 <= minute < 60 or (hour == 24 and minute):
        raise ValueError("invalid time")
    return hour * 60 + minute


def state_text(rows, nows, permille, stamp=None):
    """The quest's file for the events' rows and lines and a chance."""
    stamp = time.time() if stamp is None else stamp
    body = ["M2HEX1", "chance\t%d" % permille]
    now = nows.get(KIND)
    if now and int(now.get("until", 0)) > stamp:
        body.append("now\t%d" % int(now["until"]))
    for row in rows:
        if row.get("kind") != KIND or not row.get("on", True):
            continue
        days = ",".join(str(int(d)) for d in row.get("days", []) if 1 <= int(d) <= 7)
        if not days:
            continue
        start, end = hhmm(row["start"]), hhmm(row["end"])
        if start >= 1440:
            raise ValueError("start at 24:00")
        body.append("weekly\t%s\t%d\t%d" % (days, start, end))
    return "\n".join(body) + "\n"


def write_state(spool, rows, nows):
    atomic_write(os.path.join(spool, STATE_FILE),
                 state_text(rows, nows, read_settings(spool)["permille"]))


def status(rows, nows, stamp=None):
    """The kind's row for the page in the shape of a core's event status:
    active and until, the next start. The same weekday and overnight rules as
    the quest (m2_hex_event.active), on the panel's clock."""
    stamp = time.time() if stamp is None else stamp
    now = nows.get(KIND, {})
    until = int(now.get("until", 0)) if int(now.get("until", 0)) > stamp else 0
    windows = [r for r in rows if r.get("kind") == KIND and r.get("on", True) and r.get("days")]
    next_start = 0
    local = time.localtime(stamp)
    # mktime resolves each local midnight on its own, a DST day included.
    for delta in range(-1, 9):
        midnight = time.mktime((local.tm_year, local.tm_mon, local.tm_mday + delta, 0, 0, 0, 0, 0, -1))
        day = time.localtime(midnight)
        for row in windows:
            if day.tm_wday + 1 not in row["days"]:
                continue
            start_min, end_min = hhmm(row["start"]), hhmm(row["end"])
            start = time.mktime((day.tm_year, day.tm_mon, day.tm_mday,
                                 start_min // 60, start_min % 60, 0, 0, 0, -1))
            end_day = day.tm_mday + (1 if end_min <= start_min else 0)
            end = time.mktime((day.tm_year, day.tm_mon, end_day, end_min // 60, end_min % 60, 0, 0, 0, -1))
            if start <= stamp < end:
                until = max(until, int(end))
            elif start > stamp:
                next_start = min(next_start or int(start), int(start))
    return {"scheduled": bool(windows), "active": bool(until), "value": 0, "until": until,
            "next_start": next_start, "next_value": 0, "written": int(stamp),
            "map": 0, "next_map": 0, "host": False}


_CATALOG = {}


def catalog(path=None):
    """The chests, their maps and materials, and the maps with no chest."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), CATALOG_FILE)
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return {"chests": [], "skipped": []}
    cached = _CATALOG.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {"chests": [], "skipped": []}
    _CATALOG[path] = (mtime, data)
    return data


def runtime_status(pattern=None, stamp=None):
    """What each core that loaded the quest last wrote, fresh ones only."""
    pattern = pattern or STATUS_GLOB
    stamp = time.time() if stamp is None else stamp
    found = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="ascii") as fh:
                fields = fh.read(1024).strip().split("\t")
            if len(fields) != 6 or fields[0] != "M2HEX1":
                continue
            _version, written, active, permille, kills, drops = fields
            if stamp - int(written) > STATUS_FRESH_SECONDS:
                continue
            found.append({"core": os.path.basename(os.path.dirname(path)),
                          "channel": os.path.basename(os.path.dirname(os.path.dirname(path))),
                          "written": int(written), "active": active == "1",
                          "permille": int(permille), "kills": int(kills), "drops": int(drops)})
        except (OSError, ValueError):
            continue
    return found
