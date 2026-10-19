# =============================================================================
#  /market -- the snapshot of every offer (Iwakura's Patch 12, point 1J).
#
#  "Panel NIE skanuje wszystkich sklepow przy kazdym zapytaniu." Every 60 s
#  while somebody looks at the page (every fifteen minutes otherwise, so the
#  week of prices goes on being written), the ikashop tables are read once -
#  player.item's IKASHOP_OFFLINESHOP lines in chunks along the primary key,
#  read-only, a pause between chunks - and turned into an SQLite database in
#  the panel's memory with the columns every filter and sort reads and an
#  index on each the spec names. A request is one or two statements on it
#  (tests/market_preview_test.py measures them at 200 000 offers); the next
#  snapshot is built aside and swapped in whole, so nobody reads half of one.
#
#  An offer's usual price (Iwakura's Patch 15, point 18C5): the median of the
#  running offers of the same thing - its vnum (which is its plus), its
#  variant, the same count of bonus lines - where there are five or more, and
#  otherwise the one price of a piece his sheet prices (price.py, the bots'
#  playerbot_gear_price_rules.h in Python) or, for anything else, his sheet's
#  day price. A bargain is 25% under it; over 70% the offer is "Cena
#  nietypowa" and written down for the panel's diagnostics
#  (market_preview_unusual.tsv beside the history).
#
#  The week of prices is the panel's own for the chart: Patch 9's market index
#  lives in each core's memory and keeps no history, so every listing the
#  snapshot sees is written once, by its item id, into a small SQLite file
#  beside the panel's other files (market_history.sqlite), and an hour's
#  median of each kind.
# =============================================================================

import json
import os
import re
import sqlite3
import threading
import time

try:
    from . import price, rules, sheet
except ImportError:                                  # loaded as plain modules by a test
    import price                                     # noqa: F401
    import rules                                     # noqa: F401
    import sheet                                     # noqa: F401

ITEM_CHUNK = 20000
CHUNK_PAUSE = 0.05                    # between two chunks: the core's queries first
STATEMENT_SECONDS = 20
ACTIVE_SECONDS = 60                   # "Co 60 s budowana jest migawka"
IDLE_SECONDS = 15 * 60
VIEWED_KEEPS_ACTIVE = 5 * 60
REFRESH_MIN_SECONDS = 15              # "nie wymusza jej przebudowy czesciej niz co 15 s"
FIRST_BUILD_DELAY = 45                # after the panel starts: the database first
PROTO_SECONDS = 3600
HISTORY_KEEP_DAYS = 8
COUNT_CACHE_KEYS = 64
SUPPLY_TAIL_BYTES = 256 * 1024
UNUSUAL_FILE = "market_preview_unusual.tsv"

OFFER_COLUMNS = ("id", "owner", "vnum", "var", "cat", "sub", "plus", "lvl", "cls", "price", "cnt", "unit",
                 "nb", "nmax", "tiers", "avg", "skl",
                 "a0", "v0", "a1", "v1", "a2", "v2", "a3", "v3", "a4", "v4", "a5", "v5", "a6", "v6",
                 "ks", "s0", "s1", "s2", "emp", "ch", "map", "bot", "running", "ref", "bkey", "odd",
                 "rare", "rcnt",
                 "rsrc", "fref", "rn")
SCHEMA = (
    "CREATE TABLE offers (id INTEGER PRIMARY KEY, owner INT, vnum INT, var INT, cat INT, sub INT, plus INT, "
    "lvl INT, cls INT, price INT, cnt INT, unit REAL, nb INT, nmax INT, tiers INT, avg INT, skl INT, "
    "a0 INT, v0 INT, a1 INT, v1 INT, a2 INT, v2 INT, a3 INT, v3 INT, a4 INT, v4 INT, a5 INT, v5 INT, "
    "a6 INT, v6 INT, ks INT, s0 INT, s1 INT, s2 INT, emp INT, ch INT, map INT, bot INT, running INT, "
    "ref REAL, bkey INT, odd INT, rare INT, rcnt INT, "
    "rsrc INT, fref REAL, rn INT)",
    "CREATE TABLE kinds (vnum INT, var INT, norm TEXT, PRIMARY KEY (vnum, var)) WITHOUT ROWID",
    "CREATE TABLE shops (owner INTEGER PRIMARY KEY, norm TEXT)",
)
# "Indeksy na: kategoria, vnum, plus, wymagany poziom, cena, cena za sztuke,
# procent okazji, krolestwo, kanal" - and the shop, for "tylko ten sklep".
INDEXES = (
    "CREATE INDEX o_cat ON offers (cat, sub)",
    "CREATE INDEX o_vnum ON offers (vnum, var)",
    "CREATE INDEX o_plus ON offers (plus)",
    "CREATE INDEX o_lvl ON offers (lvl)",
    "CREATE INDEX o_price ON offers (price)",
    "CREATE INDEX o_unit ON offers (unit)",
    "CREATE INDEX o_bkey ON offers (bkey)",
    "CREATE INDEX o_emp ON offers (emp)",
    "CREATE INDEX o_ch ON offers (ch)",
    "CREATE INDEX o_owner ON offers (owner)",
)

DAMAGE_POINTS = (rules.POINT_SKILL_DAMAGE, rules.POINT_AVERAGE_DAMAGE)


class Proto(object):
    """What the snapshot needs of one item_proto row."""
    __slots__ = ("vnum", "type", "subtype", "antiflag", "level", "values", "applies", "plus", "refined_vnum")

    def __init__(self, vnum, itype, subtype, antiflag=0, level=0, values=(0,) * 6, applies=(), plus=-1, refined_vnum=0):
        self.vnum, self.type, self.subtype, self.antiflag = int(vnum), int(itype), int(subtype), int(antiflag)
        self.level, self.values, self.applies, self.plus = int(level), tuple(values), tuple(applies), int(plus)
        self.refined_vnum = int(refined_vnum)


def variant_of(proto, socket0):
    """What tells two lines of one vnum apart as goods: a book's skill, a
    marble's monster; nothing for the rest (a piece's plus is its vnum)."""
    if proto is None:
        return 0
    if proto.type in (rules.ITEM_SKILLBOOK, rules.ITEM_SKILLFORGET, rules.ITEM_POLYMORPH):
        return int(socket0 or 0)
    return 0


class Snapshot(object):
    """One built snapshot: an in-memory SQLite database and the dictionaries
    that render its rows. Read-only once built; a lock serializes the
    connection's statements (sqlite3 connections are not for two threads at
    once)."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.lock = threading.Lock()
        self.generated_at = 0.0
        self.build_ms = 0
        self.offers = 0
        self.shops = {}            # owner: dict(name, map, x, y, ch, running, seller, bot, emp)
        self.protos = {}
        self.tops = {}
        self.bonus_points = ()
        self.stones = ()           # soul stone vnums seen in sockets
        self.counts = {}           # rules.count_key -> {(cat, sub): n}
        self.variants = {}         # (vnum, var): socket0 to name it by
        self.icons = {}            # vnum: its icon's URL, "" for the "?" (icons.IconSet.build_map)
        self.world_age = -1        # the world's age in seconds, -1 unknown (Patch 13.5, point 5)
        self.attr_sets = {}        # world.item_attr: {point: ((lv1..lv5), (set levels))} (price.table_max)
        self.yang_pct = 100        # the yang rate's multiplier on his sheet, percent
        self.index_milli = 1000    # the price index, thousandths
        self.unusual = []          # Patch 15, 18C6: the offers over 70% under their usual price

    def execute(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def category_counts(self, f):
        key = rules.count_key(f)
        with self.lock:
            cached = self.counts.get(key)
        if cached is not None:
            return cached
        where, params = rules.build_where(f, ignore_category=True)
        rows = self.execute("SELECT cat, sub, COUNT(*) FROM offers WHERE " + where + " GROUP BY cat, sub", params)
        counts = {(int(c), int(s)): int(n) for c, s, n in rows}
        with self.lock:
            if len(self.counts) >= COUNT_CACHE_KEYS:
                self.counts.clear()
            self.counts[key] = counts
        return counts

    def page(self, f):
        """(rows as dicts of OFFER_COLUMNS, total, counts) for a filter."""
        counts = self.category_counts(f)
        if "cat" in f:
            total = sum(n for (c, s), n in counts.items() if c == f["cat"] and ("sub" not in f or s == f["sub"]))
        else:
            total = sum(counts.values())
        per, page = f.get("per", rules.DEFAULT_PER), f.get("page", 1)
        pages = max(1, (total + per - 1) // per)
        page = min(page, pages)
        where, params = rules.build_where(f)
        rows = self.execute("SELECT " + ", ".join(OFFER_COLUMNS) + " FROM offers WHERE " + where +
                            " ORDER BY " + rules.order_by(f) + " LIMIT ? OFFSET ?",
                            list(params) + [per, (page - 1) * per])
        return [dict(zip(OFFER_COLUMNS, r)) for r in rows], total, counts, page, pages


def offer_lines_of(attrs):
    """(ordinary lines [(point, value)], average, skill) of an offer's seven
    attribute pairs: a weapon's average and skill damage are no lines."""
    lines, avg, skl = [], 0, 0
    for point, value in attrs:
        point, value = int(point or 0), int(value or 0)
        if not point or not value:
            continue
        if point == rules.POINT_AVERAGE_DAMAGE:
            avg = value
        elif point == rules.POINT_SKILL_DAMAGE:
            skl = value
        else:
            lines.append((point, value))
    return lines, avg, skl


def gear_price(proto, vnum, plus, attrs, sockets, attr_sets, yang_pct, index_milli, keep, protos):
    """The one price of a piece his sheet prices (price.compose of its
    facts), with the facts; (None, None) for anything else."""
    if proto is None or proto.type not in (rules.ITEM_WEAPON, rules.ITEM_ARMOR) or plus < 0:
        return None, None
    facts = price.offer_facts(proto, vnum, plus, attrs, sockets, attr_sets, yang_pct, index_milli, keep, protos)
    if facts is None:
        return None, None
    composed = price.compose(facts)
    if facts.pricing_options.get('precise') and composed['priced']:
        c9 = price.verified_c9(proto, vnum, plus, protos, facts.rows, facts.curve_pct, facts.inflation)
        quote = price.listing_quote(composed, c9, facts.pricing_options)
        composed.update(price=quote['price'], price_reasons=quote['reasons'], price_conflict=quote['conflict'])
    return (composed if composed["priced"] else None), facts


@price.overrides.synchronized
def build_snapshot(items, protos, shops, owners, tops, names, references, day_price, gm_owners=(), world_age=-1,
                   samples=None, attr_sets=None, yang_pct=100, index_milli=1000):
    """A Snapshot of offer lines.

    items: iterable of (id, owner, vnum, count, s0, s1, s2, ((type, value) x7), price)
    protos: {vnum: Proto}
    shops: {owner: (map, x, y, channel, running, shop name)}
    owners: {owner: (name, bot, empire)}
    tops: {point: top roll}
    names: {(vnum, var): (pl name, en name)} - every kind's two names, for the search
    references, samples: the week's medians of before Patch 15, point 18C5
             (History.compute_references), no longer what a usual price is;
             accepted and unused
    day_price: function(vnum) -> unit price of an upgrade material, 0 for none
    world_age: the world's age in seconds (DbSource.world_age), -1 unknown
    attr_sets: world.item_attr as price.table_max reads it
    yang_pct, index_milli: the yang rate's multiplier and the price index the
             one price of a piece of gear is scaled by
    """
    started = time.time()
    snap = Snapshot()
    snap.protos, snap.tops = protos, tops
    snap.attr_sets = attr_sets or {}
    snap.yang_pct, snap.index_milli = int(yang_pct or 100), int(index_milli or 1000)
    cur = snap.conn.cursor()
    for statement in SCHEMA:
        cur.execute(statement)
    # Patch 13, 5A: the pieces of each kind on all the running counters, read
    # before the rows are written so each row carries its kind's count.
    pieces = {}
    # Patch 14, point 3: the level-30 weapons at +0..+3 of each family on each
    # kingdom's running counters, as the cores' census counts them.
    level30 = {}
    for _item_id, owner, vnum, count, s0, _s1, _s2, _attrs, price in items:
        proto = protos.get(vnum)
        shop = shops.get(owner)
        if proto is None or price is None or price <= 0 or not shop or not shop[4]:
            continue
        key = (vnum, variant_of(proto, s0))
        pieces[key] = pieces.get(key, 0) + max(1, int(count or 1))
        family = rules.level30_cut_family(vnum) if proto.type == rules.ITEM_WEAPON else -1
        if family >= 0:
            kingdom = rules.level30_market_key(shop[0], owners.get(owner, ("", False, 0))[2])
            level30[(kingdom, family)] = level30.get((kingdom, family), 0) + max(1, int(count or 1))
    snap.level30_units = level30
    snap.level30_at = time.time()
    # Patch 15, 18C5: the running offers of each thing - vnum, variant, count
    # of bonus lines - and the median of their unit prices where there are
    # five or more: the usual price "wzgledem rynku, a nie samego wzoru".
    market = {}
    for _item_id, owner, vnum, count, s0, _s1, _s2, attrs, line_price in items:
        proto = protos.get(vnum)
        shop = shops.get(owner)
        if proto is None or line_price is None or line_price <= 0 or not shop or not shop[4]:
            continue
        key = (vnum, variant_of(proto, s0), len(offer_lines_of(attrs)[0]))
        market.setdefault(key, []).append(float(line_price) / max(1, int(count or 1)))
    medians = {key: (rules.median(units), len(units)) for key, units in market.items()
               if len(units) >= rules.MARKET_MIN_OFFERS}
    classes, kinds, points, stones = {}, set(), set(), set()
    batch = []
    insert = "INSERT INTO offers (" + ", ".join(OFFER_COLUMNS) + ") VALUES (" + ", ".join("?" * len(OFFER_COLUMNS)) + ")"
    for item_id, owner, vnum, count, s0, s1, s2, attrs, price in items:
        proto = protos.get(vnum)
        if proto is None or price is None or price <= 0:
            continue
        count = max(1, int(count or 1))
        shop = shops.get(owner)
        seller = owners.get(owner, ("", False, 0))
        var = variant_of(proto, s0)
        key = (vnum, var)
        if key not in classes:
            classes[key] = (rules.classify(proto.type, proto.subtype, vnum, s0),
                            rules.class_mask(proto.type, proto.antiflag, vnum, s0))
            snap.variants[key] = int(s0 or 0)
        (cat, sub), cls = classes[key]
        kinds.add(key)
        lines, avg, skl, nmax, tiers = [], 0, 0, 0, 0
        cols = []
        for point, value in attrs:
            point, value = int(point or 0), int(value or 0)
            cols.extend((point, value))
            if not point or not value:
                continue
            if point == rules.POINT_AVERAGE_DAMAGE:
                avg = value
            elif point == rules.POINT_SKILL_DAMAGE:
                skl = value
            else:
                lines.append((point, value))
                points.add(point)
                if rules.is_max_line(point, value, tops):
                    nmax += 1
                tiers += rules.line_tier(point)
        while len(cols) < 14:
            cols.append(0)
        sockets = []
        for s in (s0, s1, s2):
            s = int(s or 0)
            if proto.type in (rules.ITEM_WEAPON, rules.ITEM_ARMOR) and rules.SOUL_STONES[0] <= s <= rules.SOUL_STONES[1]:
                sockets.append(s)
                stones.add(s)
            else:
                sockets.append(0)
        unit = float(price) / count
        plus = proto.plus
        gplus = rules.gear_plus(proto.type, vnum, plus)
        # Patch 15, point 18C1: a piece his sheet prices asks the bots' own
        # one price - Patch 14, point 3's cut of a level-30 weapon at +0..+3
        # among its facts.
        keep = rules.level30_cut_keep(vnum, gplus, len(lines), avg, world_age, level30,
                                      rules.level30_market_key(shop[0] if shop else 0, seller[2]),
                                      snap.level30_at) if proto.type == rules.ITEM_WEAPON else None
        composed, facts = gear_price(proto, vnum, gplus, attrs, (s0, s1, s2), snap.attr_sets, snap.yang_pct,
                                     snap.index_milli, keep, protos)
        if facts is not None:
            # A line at its maximum as the price reads it (Max HP from 1500).
            nmax = sum(1 for line in facts.lines if line.at_top and line.ordinary)
        fref, frsrc = 0.0, rules.REF_NONE
        if composed is not None:
            fref, frsrc = float(composed["price"]), rules.REF_SHEET
        elif vnum in sheet.REFINE_MATERIALS:
            fref, frsrc = float(day_price(vnum) or 0), rules.REF_MATERIAL
        elif facts is None:
            # Patch 13.5, point 5: a Moonlight chest's reference in a world's
            # first day is the share its bots ask.
            fref = float(day_price(vnum, proto, s0, plus) or 0) * rules.young_world_factor(vnum, world_age)
            frsrc = rules.REF_SHEET
        if fref <= 0:
            fref, frsrc = 0.0, rules.REF_NONE
        # Patch 15, 18C5: five running offers of the same thing make the
        # market's median the usual price; fewer, the one price.
        market_ref = medians.get((vnum, var, len(lines)))
        if market_ref is not None:
            ref, rsrc, rn = float(market_ref[0]), rules.REF_MARKET, market_ref[1]
        else:
            ref, rsrc, rn = fref, frsrc, 0
        pct = rules.bargain_pct(unit, ref) if ref > 0 else None
        # 18C6: over 70% under it is no bargain but a price to look at.
        odd = rules.is_unusual(pct)
        if odd and len(snap.unusual) < rules.UNUSUAL_KEEP:
            snap.unusual.append({"id": item_id, "vnum": vnum, "plus": gplus, "var": var, "owner": owner,
                                 "bot": 1 if seller[1] else 0, "lines": lines, "avg": avg, "skl": skl,
                                 "unit": unit, "ref": ref, "pct": pct, "rsrc": rsrc, "rn": rn, "fref": fref,
                                 "how": rules.formula_text(composed)})
        bot = 1 if seller[1] else 0
        on_market = pieces.get(key, 0)
        batch.append((item_id, owner, vnum, var, cat, sub, plus, proto.level, cls, int(price), count, unit,
                      len(lines), nmax, tiers, avg, skl) + tuple(cols) +
                     (sum(1 for s in sockets if s), sockets[0], sockets[1], sockets[2],
                      int(seller[2] or 0), int(shop[3]) if shop else 0, int(shop[0]) if shop else 0, bot,
                      1 if shop and shop[4] else 0, ref,
                      rules.NO_REFERENCE_KEY if odd else rules.bargain_key(pct), 1 if odd else 0,
                      1 if rules.is_rare(on_market) else 0, on_market,
                      rsrc, fref, rn))
        if len(batch) >= 5000:
            cur.executemany(insert, batch)
            batch = []
    if batch:
        cur.executemany(insert, batch)
    rows = []
    for key in kinds:
        pl, en = names.get(key, ("", ""))
        rows.append((key[0], key[1], rules.normalize(pl + " | " + en)))
    cur.executemany("INSERT OR REPLACE INTO kinds VALUES (?, ?, ?)", rows)
    shop_rows = []
    for owner, shop in shops.items():
        seller = owners.get(owner, ("", False, 0))
        snap.shops[owner] = {"name": shop[5], "map": int(shop[0]), "x": int(shop[1]), "y": int(shop[2]),
                             "ch": int(shop[3]), "running": bool(shop[4]), "seller": seller[0],
                             "bot": bool(seller[1]), "emp": int(seller[2] or 0)}
        shop_rows.append((owner, rules.normalize(seller[0] + " | " + shop[5])))
    cur.executemany("INSERT OR REPLACE INTO shops VALUES (?, ?)", shop_rows)
    for statement in INDEXES:
        cur.execute(statement)
    cur.execute("ANALYZE")
    snap.conn.commit()
    snap.offers = snap.execute("SELECT COUNT(*) FROM offers")[0][0]
    snap.bonus_points = tuple(sorted(points | set(sheet.BONUS_TIERS)))
    snap.stones = tuple(sorted(stones))
    snap.world_age = int(world_age if world_age is not None else -1)
    snap.generated_at = time.time()
    snap.build_ms = int((snap.generated_at - started) * 1000)
    return snap


# -----------------------------------------------------------------------------
#  The week of prices.
# -----------------------------------------------------------------------------
class History(object):
    """market_history.sqlite: each listing once by its item id, and an hour's
    median of each kind. One writer (the snapshot thread)."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.references = {}
        self.samples = {}                # Patch 14, 6B: the bases behind each median
        self.references_at = 0.0
        self._ready = False

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        if not self._ready:
            conn.execute("CREATE TABLE IF NOT EXISTS seen (item_id INTEGER PRIMARY KEY, vnum INT, plus INT, "
                         "var INT, base REAL, first_ts INT)")
            conn.execute("CREATE INDEX IF NOT EXISTS seen_kind ON seen (vnum, plus, var, first_ts)")
            conn.execute("CREATE TABLE IF NOT EXISTS hourly (hour INT, vnum INT, plus INT, var INT, n INT, "
                         "median REAL, low REAL, PRIMARY KEY (vnum, plus, var, hour))")
            conn.commit()
            self._ready = True
        return conn

    def record(self, lines, now=None):
        """lines: [(item_id, vnum, plus, var, unit, base)] of the running offers."""
        now = int(now or time.time())
        hour = now // 3600
        per_kind = {}
        for item_id, vnum, plus, var, unit, base in lines:
            per_kind.setdefault((vnum, plus, var), []).append(unit)
        with self.lock:
            conn = self._connect()
            try:
                conn.executemany("INSERT OR IGNORE INTO seen VALUES (?, ?, ?, ?, ?, ?)",
                                 ((i, v, p, w, b, now) for i, v, p, w, u, b in lines))
                conn.executemany("INSERT OR REPLACE INTO hourly VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 ((hour, v, p, w, len(units), rules.median(units), min(units))
                                  for (v, p, w), units in per_kind.items()))
                horizon = now - HISTORY_KEEP_DAYS * 86400
                conn.execute("DELETE FROM seen WHERE first_ts < ?", (horizon,))
                conn.execute("DELETE FROM hourly WHERE hour < ?", (horizon // 3600,))
                conn.commit()
            finally:
                conn.close()

    def compute_references(self, now=None):
        """{(vnum, plus, var): median base unit} of the kinds with five
        listings or more in seven days."""
        now = int(now or time.time())
        out, values, last, samples = {}, [], None, {}
        with self.lock:
            conn = self._connect()
            try:
                cursor = conn.execute("SELECT vnum, plus, var, base FROM seen WHERE first_ts >= ? "
                                      "ORDER BY vnum, plus, var", (now - rules.HISTORY_DAYS * 86400,))
                for vnum, plus, var, base in cursor:
                    key = (vnum, plus, var)
                    if key != last:
                        if last is not None and len(values) >= rules.HISTORY_MIN_OFFERS:
                            out[last] = rules.median(values)
                            samples[last] = tuple(values)
                        last, values = key, []
                    if base and base > 0:
                        values.append(base)
                if last is not None and len(values) >= rules.HISTORY_MIN_OFFERS:
                    out[last] = rules.median(values)
                    samples[last] = tuple(values)
            finally:
                conn.close()
        self.references, self.samples, self.references_at = out, samples, time.time()
        return out

    def chart(self, vnum, plus, var, now=None):
        """[(hour start, median, low, lines)] of the last seven days."""
        now = int(now or time.time())
        with self.lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT hour, median, low, n FROM hourly WHERE vnum = ? AND plus = ? AND var = ? "
                                    "AND hour >= ? ORDER BY hour",
                                    (int(vnum), int(plus), int(var), (now - rules.HISTORY_DAYS * 86400) // 3600)
                                    ).fetchall()
            finally:
                conn.close()
        return [(int(h) * 3600, float(m or 0), float(lo or 0), int(n or 0)) for h, m, lo, n in rows]


# -----------------------------------------------------------------------------
#  The database's side: what one build reads, read-only.
# -----------------------------------------------------------------------------
def _text(value):
    if isinstance(value, (bytes, bytearray)):
        for encoding in ("cp1250", "utf-8", "latin1"):
            try:
                return bytes(value).decode(encoding)
            except UnicodeDecodeError:
                pass
        return bytes(value).decode("cp1250", "replace")
    return str(value or "")


def _ids(ids):
    return "(" + ",".join(str(int(i)) for i in sorted(set(ids))) + ")" if ids else "(NULL)"


class DbSource(object):
    """Reads one build's worth from MariaDB through the panel's connection.
    Every statement is a SELECT under max_statement_time; the item lines come
    in chunks along the primary key with a pause between, so the cores' own
    queries are never queued behind one long scan."""

    def __init__(self, ns):
        self.ns = ns
        self._protos = None
        self._protos_at = 0.0
        self._tops = {}
        self._attr_sets = {}

    def attr_sets(self):
        """world.item_attr's lines by their sets (read with the protos)."""
        return self._attr_sets

    def connect(self):
        conn = self.ns.db()
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION max_statement_time = %s", (STATEMENT_SECONDS,))
                cur.execute("SET SESSION TRANSACTION READ ONLY")
        except Exception:                            # noqa: BLE001 - MySQL lacks the first; carry on
            pass
        return conn

    def protos(self, conn):
        if self._protos is not None and time.time() - self._protos_at < PROTO_SECONDS:
            return self._protos, self._tops
        out = {}
        with conn.cursor() as cur:
            cur.execute("SELECT vnum, type, subtype, antiflag, limittype0, limitvalue0, limittype1, limitvalue1, "
                        "value0, value1, value2, value3, value4, value5, applytype0, applyvalue0, applytype1, "
                        "applyvalue1, applytype2, applyvalue2, refined_vnum, CAST(locale_name AS BINARY) AS name "
                        "FROM player.item_proto")
            for r in cur.fetchall():
                level = 0
                for k in (0, 1):
                    if int(r.get("limittype%d" % k) or 0) == 1:
                        level = int(r.get("limitvalue%d" % k) or 0)
                applies = tuple((int(r.get("applytype%d" % k) or 0), int(r.get("applyvalue%d" % k) or 0))
                                for k in range(3) if int(r.get("applytype%d" % k) or 0))
                _base, plus = rules.split_plus(_text(r.get("name")))
                vnum = int(r["vnum"] or 0)
                out[vnum] = Proto(vnum, r.get("type") or 0, r.get("subtype") or 0, r.get("antiflag") or 0, level,
                                  tuple(int(r.get("value%d" % k) or 0) for k in range(6)), applies, plus, r.get('refined_vnum') or 0)
            tops = {}
            # Patch 15, 18C1: a line's top on the piece's own attribute set,
            # as the core reads it (GetPlayerBotBonusMaxRoll): the normal
            # table's five levels and each set's level.
            sets = {}
            try:
                cur.execute("SELECT apply+0 AS p, lv1, lv2, lv3, lv4, lv5, weapon, body, wrist, foots, neck, head, "
                            "shield, ear FROM world.item_attr")
                for r in cur.fetchall():
                    point = int(r["p"] or 0)
                    if point and point not in sets:
                        sets[point] = (tuple(int(r["lv%d" % k] or 0) for k in range(1, 6)),
                                       tuple(int(r[c] or 0) for c in ("weapon", "body", "wrist", "foots", "neck",
                                                                      "head", "shield", "ear")))
            except Exception:                        # noqa: BLE001 - an older table: the fifth level for all
                sets = {}
            self._attr_sets = sets
            for table in ("world.item_attr", "world.item_attr_rare"):
                try:
                    cur.execute("SELECT apply+0 AS p, GREATEST(lv1, lv2, lv3, lv4, lv5) AS top FROM " + table)
                    for r in cur.fetchall():
                        point, top = int(r["p"] or 0), int(r["top"] or 0)
                        if point and top > tops.get(point, 0):
                            tops[point] = top
                except Exception:                    # noqa: BLE001 - no rare table on some worlds
                    pass
        self._protos, self._tops, self._protos_at = out, tops, time.time()
        return out, tops

    def shops(self, conn):
        out = {}
        with conn.cursor() as cur:
            cur.execute("SELECT owner, duration, `map`, x, y, channel, CAST(name AS BINARY) AS name "
                        "FROM player.ikashop_offlineshop")
            for r in cur.fetchall():
                out[int(r["owner"])] = (int(r["map"] or 0), int(r["x"] or 0), int(r["y"] or 0),
                                        int(r["channel"] or 0), int(r["duration"] or 0) > 0,
                                        _text(r.get("name")).strip())
        return out

    def owners(self, conn, pids):
        out = {}
        pids = sorted(pids)
        with conn.cursor() as cur:
            for i in range(0, len(pids), 1000):
                cur.execute("SELECT p.id, CAST(p.name AS BINARY) AS name, "
                            "(LEFT(a.login, 10) = 'playerbot_') AS bot, "
                            "(SELECT pi.empire FROM player.player_index pi WHERE pi.id = p.account_id) AS emp "
                            "FROM player.player p LEFT JOIN account.account a ON a.id = p.account_id "
                            "WHERE p.id IN " + _ids(pids[i:i + 1000]))
                for r in cur.fetchall():
                    out[int(r["id"])] = (_text(r.get("name")).strip(), bool(int(r.get("bot") or 0)),
                                         int(r.get("emp") or 0))
        return out

    def items(self, conn, sleep=time.sleep):
        last, out = 0, []
        columns = ["id", "owner_id", "vnum", "`count`", "socket0", "socket1", "socket2"]
        for k in range(7):
            columns += ["attrtype%d" % k, "attrvalue%d" % k]
        with conn.cursor() as cur:
            while True:
                cur.execute("SELECT " + ", ".join(columns) + ", "
                            "CAST(JSON_UNQUOTE(JSON_EXTRACT(ikashop_data, '$.yang')) AS UNSIGNED) AS yang "
                            "FROM player.item WHERE `window` = 'IKASHOP_OFFLINESHOP' AND id > %s "
                            "AND ikashop_data IS NOT NULL AND ikashop_data <> '' ORDER BY id LIMIT %s",
                            (last, ITEM_CHUNK))
                rows = cur.fetchall()
                for r in rows:
                    attrs = tuple((int(r.get("attrtype%d" % k) or 0), int(r.get("attrvalue%d" % k) or 0))
                                  for k in range(7))
                    out.append((int(r["id"]), int(r["owner_id"]), int(r["vnum"]), int(r.get("count") or 1),
                                int(r.get("socket0") or 0), int(r.get("socket1") or 0), int(r.get("socket2") or 0),
                                attrs, int(r.get("yang") or 0)))
                if len(rows) < ITEM_CHUNK:
                    break
                last = int(rows[-1]["id"])
                sleep(CHUNK_PAUSE)
        return out

    def world_age(self, conn):
        """The world's age in seconds as the cores read it for the price index
        and the Moonlight chest (playerbot_session_realism_rules::WorldAgeSql:
        the oldest account, which the seed makes with the install); -1 when
        there is none or the read fails."""
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(GREATEST(0, TIMESTAMPDIFF(SECOND, MIN(c.create_time), NOW())), -1) "
                            "AS age FROM account.account c WHERE c.create_time > '1971-01-01'")
                row = cur.fetchone()
        except Exception:                            # noqa: BLE001 - an unknown age is an old world's
            return -1
        if not row:
            return -1
        value = row.get("age") if isinstance(row, dict) else row[0]
        try:
            return int(value if value is not None else -1)
        except (TypeError, ValueError):
            return -1

    def yang_rate(self):
        try:
            return int(self.ns.read_rates().get("yang", 100) or 100)
        except Exception:                            # noqa: BLE001
            return 100

    def supply(self):
        """({vnum: modifier permille}, index milli) from the newest rows of the
        cores' playerbot_price_index.tsv (#PB11I1)."""
        newest, modifiers, index = {}, {}, (0, 1000)
        for folder in tuple(self.ns.get("IWAKURA_CORE_DIRS") or ()):
            path = os.path.join(folder, "playerbot_price_index.tsv")
            try:
                with open(path, "rb") as fh:
                    head = fh.readline(64).decode("ascii", "replace").strip()
                    if head != "#PB11I1":
                        continue
                    fh.seek(0, os.SEEK_END)
                    fh.seek(max(0, fh.tell() - SUPPLY_TAIL_BYTES))
                    tail = fh.read().decode("ascii", "replace").splitlines()[1:]
            except OSError:
                continue
            for line in tail:
                parts = line.split("\t")
                if len(parts) != 6:
                    continue
                try:
                    ts, milli, _trend, vnum, _supply, modifier = (int(p) for p in parts)
                except ValueError:
                    continue
                if ts >= newest.get(vnum, -1):
                    newest[vnum], modifiers[vnum] = ts, modifier
                if ts >= index[0]:
                    index = (ts, milli)
        return modifiers, index[1]

    def persons(self):
        """The characters "moja postac" may be: of an account that is no bot's
        and no game master's (common.gmlist), newest play first."""
        conn = self.ns.db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT p.id, CAST(p.name AS BINARY) AS name, p.job, p.level, p.last_play "
                            "FROM player.player p JOIN account.account a ON a.id = p.account_id "
                            "WHERE LEFT(a.login, 10) <> 'playerbot_' AND NOT EXISTS (SELECT 1 FROM common.gmlist g "
                            "WHERE g.mName = p.name AND g.mAuthority <> 'PLAYER') "
                            "ORDER BY p.last_play DESC LIMIT 40")
                return [{"pid": int(r["id"]), "name": _text(r.get("name")).strip(), "job": int(r.get("job") or 0),
                         "cls": rules.job_class(r.get("job")), "level": int(r.get("level") or 0)}
                        for r in cur.fetchall()]
        finally:
            conn.close()


class Store(object):
    """The current snapshot, the thread that renews it and the history."""

    def __init__(self, ns, history_path, source=None, names=None, icons=None):
        self.ns = ns
        self.source = source or DbSource(ns)
        self.names = names              # function(vnum, socket0) -> (pl, en)
        self.icons = icons              # icons.IconSet: one vnum -> icon map a snapshot (Patch 13, point 6)
        self.history = History(history_path)
        self.current = None
        self.lock = threading.Lock()
        self.building = False
        self.last_error = ""
        self.viewed_at = 0.0
        self.requested_at = 0.0
        self.thread = None
        self.stop = False

    def viewed(self):
        self.viewed_at = time.time()

    def request_refresh(self):
        """A rebuild now, unless the snapshot is younger than fifteen seconds."""
        snap = self.current
        if snap is not None and time.time() - snap.generated_at < REFRESH_MIN_SECONDS:
            return False
        self.requested_at = time.time()
        return True

    def start(self, first_delay=FIRST_BUILD_DELAY):
        with self.lock:
            if self.thread is not None:
                return
            self.thread = threading.Thread(target=self._run, args=(first_delay,), name="market-preview",
                                           daemon=True)
            self.thread.start()

    def _run(self, first_delay):
        wake = time.time() + first_delay
        attempted = 0.0
        while not self.stop:
            now = time.time()
            # A request is served once, and never sooner than fifteen seconds
            # after the last attempt - a database that keeps failing is asked
            # four times a minute at most, not every second.
            if self.requested_at and now - attempted >= REFRESH_MIN_SECONDS and \
                    (self.current is None or self.requested_at > self.current.generated_at):
                wake = now
            if now >= wake:
                attempted = now
                self.requested_at = 0.0
                self.rebuild()
                active = time.time() - self.viewed_at < VIEWED_KEEPS_ACTIVE
                wake = time.time() + (ACTIVE_SECONDS if active else IDLE_SECONDS)
            time.sleep(1.0)

    def rebuild(self):
        if self.building:
            return self.current
        self.building = True
        try:
            snap = self._build()
            self.current = snap
            self.last_error = ""
            return snap
        except Exception as exc:                     # noqa: BLE001 - the page says so; the old snapshot stays
            self.last_error = "%s: %s" % (type(exc).__name__, str(exc)[:300])
            try:
                self.ns.app.logger.exception("market preview: snapshot failed")
            except Exception:                        # noqa: BLE001
                pass
            return self.current
        finally:
            self.building = False

    def _build(self):
        src = self.source
        conn = src.connect()
        try:
            protos, tops = src.protos(conn)
            shops = src.shops(conn)
            items = src.items(conn)
            owners = src.owners(conn, {i[1] for i in items} | set(shops))
            ages = getattr(src, "world_age", None)
            world_age = ages(conn) if ages else -1
        finally:
            try:
                conn.close()
            except Exception:                        # noqa: BLE001
                pass
        modifiers, index_milli = src.supply()
        yang_pct = rules.yang_rate_price_pct(src.yang_rate())
        attr_sets = src.attr_sets() if hasattr(src, "attr_sets") else {}

        def day_price(vnum, proto=None, socket0=0, plus=-1):
            if proto is None:                       # an upgrade material: the supply's day price
                base = getattr(sheet, 'CUSTOM_PRICES', {}).get(vnum, sheet.MATERIALS.get(vnum, 0))
                return base * yang_pct / 100.0 * index_milli / 1000.0 * modifiers.get(vnum, 1000) / 1000.0
            base = rules.sheet_price(proto.type, vnum, socket0, plus)
            return base * yang_pct / 100.0 * index_milli / 1000.0

        names = {}
        for item in items:
            proto = protos.get(item[2])
            key = (item[2], variant_of(proto, item[4]))
            if key not in names:
                names[key] = self.names(item[2], item[4]) if self.names else ("", "")
        snap = build_snapshot(items, protos, shops, owners, tops, names, {}, day_price, world_age=world_age,
                              attr_sets=attr_sets, yang_pct=yang_pct, index_milli=index_milli)
        self._write_unusual(snap)
        snap.icons = self._icon_map(protos, items)
        self._record_history(snap, items, protos)
        return snap

    def _write_unusual(self, snap):
        """Patch 15, 18C6: "zapisac przedmiot do diagnostyki panelu (vnum,
        plus, bonusy, cena oferty, cena odniesienia, z czego wyliczona)" -
        market_preview_unusual.tsv beside the history, the build's whole
        list, written aside and renamed over the last one; a line in the
        panel's log when there are any. A full disk costs the list, not the
        page."""
        path = os.path.join(os.path.dirname(os.path.abspath(self.history.path)), UNUSUAL_FILE)
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(rules.unusual_header() + "\n")
                for entry in snap.unusual:
                    fh.write(rules.unusual_row(snap.generated_at or time.time(), entry) + "\n")
            os.replace(tmp, path)
            if snap.unusual:
                self.ns.app.logger.info("market preview: %d offers at an unusual price (over %d%% under the "
                                        "usual), see %s", len(snap.unusual), rules.UNUSUAL_PCT, path)
        except Exception:                            # noqa: BLE001
            try:
                self.ns.app.logger.exception("market preview: unusual list failed")
            except Exception:                        # noqa: BLE001
                pass

    def _icon_map(self, protos, items):
        """The snapshot's one vnum -> icon map (Patch 13, point 6), built here
        and never per card; a broken icon set costs the pictures, not the page."""
        if self.icons is None:
            return {}
        try:
            self.icons.reload()
            return self.icons.build_map(protos, {item[2] for item in items})
        except Exception:                            # noqa: BLE001
            try:
                self.ns.app.logger.exception("market preview: icon map failed")
            except Exception:                        # noqa: BLE001
                pass
            return {}

    def _record_history(self, snap, items, protos):
        """Every running line's unit price for the chart, and its unit price
        over what its lines and plus ask (the one price over the plain sheet,
        price.compose) as the base of before - no reference reads it since
        Patch 15, point 18C5. An offer at an unusual price is left out."""
        rows = snap.execute("SELECT id, vnum, plus, var, unit, a0, v0, a1, v1, a2, v2, a3, v3, a4, v4, a5, v5, "
                            "a6, v6, lvl, bot, map, emp, avg, nb, fref, s0, s1, s2 FROM offers "
                            "WHERE running = 1 AND odd = 0")
        lines = []
        for r in rows:
            proto = protos.get(r[1])
            mult = 1.0
            if proto is not None and proto.type in (rules.ITEM_WEAPON, rules.ITEM_ARMOR) and r[25]:
                plain = rules.sheet_price(proto.type, r[1], 0, r[2])
                plain = plain * snap.yang_pct / 100.0 * snap.index_milli / 1000.0 if plain else 0
                if plain > 0:
                    mult = float(r[25]) / plain
            lines.append((r[0], r[1], r[2], r[3], r[4], r[4] / mult if mult else r[4]))
        try:
            self.history.record(lines)
        except Exception:                            # noqa: BLE001 - a full disk costs the chart, not the page
            try:
                self.ns.app.logger.exception("market preview: history write failed")
            except Exception:                        # noqa: BLE001
                pass
