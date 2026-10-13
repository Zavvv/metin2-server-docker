# =============================================================================
#  /market -- the market preview's pure rules (Iwakura's Patch 12, point 1).
#
#  No Flask, no database: what a request's parameters mean, the one list of
#  categories, the SQL a filter becomes (fixed text, every value a parameter),
#  the sort orders, a price as a player writes it, a name as a search reads
#  it, the usual price and the bargain (the price of a piece of gear itself is
#  price.py, the bots' own), the unusual price, the bonus lines' ratings and
#  the TP's answers. tests/market_preview_test.py tests all
#  of it; snapshot.py and __init__.py are what asks it.
# =============================================================================

import math
import re
import time
import unicodedata

try:
    from . import sheet
except ImportError:                                  # loaded as a plain module by a test
    import sheet                                     # noqa: F401

# -----------------------------------------------------------------------------
#  Categories - the one place to add one (spec 1D). The numbers are the
#  snapshot's `cat`/`sub` columns; a category's own sub 0 is "nothing finer".
#  classify() below is what puts an item into them, from item_proto's type and
#  subtype as Iwakura's export counts lines_by_kind (IWAKURA_SHOP_KINDS), with
#  the finer splits the page asks for.
# -----------------------------------------------------------------------------
CATEGORIES = (
    # key, id, pl, en, ((sub key, sub id, pl, en), ...)
    ("weapons", 1, "Bronie", "Weapons", (
        ("swords", 1, "Miecze", "Swords"),
        ("twohanded", 2, "Broń dwuręczna", "Two-handed"),
        ("daggers", 3, "Sztylety", "Daggers"),
        ("bows", 4, "Łuki", "Bows"),
        ("bells", 5, "Dzwony", "Bells"),
        ("fans", 6, "Wachlarze", "Fans"))),
    ("armour", 2, "Zbroje", "Armour", ()),
    ("shields_helmets", 3, "Tarcze i hełmy", "Shields and helmets", (
        ("shields", 1, "Tarcze", "Shields"),
        ("helmets", 2, "Hełmy", "Helmets"))),
    ("jewellery", 4, "Biżuteria", "Jewellery", (
        ("bracelets", 1, "Bransolety", "Bracelets"),
        ("necklaces", 2, "Naszyjniki", "Necklaces"),
        ("earrings", 3, "Kolczyki", "Earrings"))),
    ("boots", 5, "Buty", "Boots", ()),
    ("books", 6, "Księgi umiejętności", "Skill books", (
        ("warrior", 1, "Wojownik", "Warrior"),
        ("ninja", 2, "Ninja", "Ninja"),
        ("sura", 3, "Sura", "Sura"),
        ("shaman", 4, "Szaman", "Shaman"),
        ("forget", 5, "Księgi Zapomnienia", "Forgetting books"),
        ("passive", 6, "Księgi pasywne", "Passive books"))),
    ("soul_stones", 7, "Kamienie duszy", "Soul stones", (
        ("g0", 1, "+0", "+0"), ("g1", 2, "+1", "+1"), ("g2", 3, "+2", "+2"),
        ("g3", 4, "+3", "+3"), ("g4", 5, "+4", "+4"))),
    ("chests", 8, "Skrzynie", "Chests", ()),
    ("usable", 9, "Mikstury i użytkowe", "Potions and usables", ()),
    ("materials", 10, "Materiały", "Materials", (
        ("refine", 1, "Ulepszacze", "Upgrade materials"),
        ("ores", 2, "Rudy i przetopy", "Ores and smelted ores"),
        ("herbs", 3, "Zioła", "Herbs"),
        ("fish", 4, "Ryby", "Fish"))),
    ("other", 11, "Inne", "Other", ()),
)
CATEGORY_BY_KEY = {c[0]: c for c in CATEGORIES}
CATEGORY_BY_ID = {c[1]: c for c in CATEGORIES}
SUB_BY_KEY = {(c[0], s[0]): s[1] for c in CATEGORIES for s in c[4]}
CAT_WEAPONS = 1
CAT_BOOKS = 6
CAT_MATERIALS = 10

# item_length.h (mt2009)
ITEM_WEAPON, ITEM_ARMOR, ITEM_USE, ITEM_AUTOUSE, ITEM_MATERIAL, ITEM_SPECIAL = 1, 2, 3, 4, 5, 6
ITEM_METIN, ITEM_FISH, ITEM_ROD, ITEM_RESOURCE, ITEM_SKILLBOOK = 10, 12, 13, 14, 17
ITEM_QUEST, ITEM_POLYMORPH, ITEM_TREASURE_BOX, ITEM_TREASURE_KEY = 18, 19, 20, 21
ITEM_SKILLFORGET, ITEM_GIFTBOX, ITEM_POTION = 22, 23, 36
WEAPON_SUBS = {0: 1, 3: 2, 1: 3, 2: 4, 4: 5, 5: 6}          # sword, two-handed, dagger, bow, bell, fan
ARMOR_SUBS = {0: (2, 0), 1: (3, 2), 2: (3, 1), 3: (4, 1), 4: (5, 0), 5: (4, 2), 6: (4, 3)}
# The price sheet's slot of an armour subtype, and a weapon's (PRICE_SLOT_*).
ARMOR_PRICE_SLOT = {0: 2, 1: 1, 2: 4, 3: 16, 4: 8, 5: 32, 6: 64}
WEAPON_PRICE_SLOT = 128
# The general skill book carries its skill in socket 0; the Instr. books are
# 50400 + the skill (item_proto).
SKILL_BOOK_GENERAL = 50300
SKILL_BOOK_INSTR = (50401, 50599)
# Books read by the skill window that are no class's: the Leadership books,
# the combo, languages, polymorph, riding and gathering (book_rules.h; the
# horse books are 50060/50061).
PASSIVE_BOOKS = frozenset(list(range(50301, 50307)) + list(range(50311, 50317)) + [50060, 50061, 50600])
HERBS = frozenset(list(range(50721, 50741)) + [50056])
ORES = (50601, 50640)                                    # ores, smelted ores, the diamond
SOUL_STONES = (28000, 28999)

# Skill ids by class (the four classes' skill groups, skill_proto).
_CLASS_SKILLS = (
    (0, set(range(1, 6)) | set(range(16, 21))),          # warrior
    (1, set(range(31, 36)) | set(range(46, 52))),        # ninja
    (2, set(range(61, 67)) | set(range(76, 82))),        # sura
    (3, set(range(91, 97)) | set(range(106, 112))),      # shaman
)
# The four classes as bits of the snapshot's `cls`, and the item_proto
# antiflags that forbid each (ITEM_ANTIFLAG_WARRIOR .. SHAMAN).
CLASS_BITS = (1, 2, 4, 8)
CLASS_ANTIFLAGS = (1 << 2, 1 << 3, 1 << 4, 1 << 5)
ALL_CLASSES = 15
CLASS_KEYS = ("warrior", "ninja", "sura", "shaman")


def skill_class(skill):
    for job, skills in _CLASS_SKILLS:
        if int(skill or 0) in skills:
            return job
    return -1


def book_skill(vnum, socket0):
    vnum = int(vnum or 0)
    if vnum == SKILL_BOOK_GENERAL:
        return int(socket0 or 0)
    if SKILL_BOOK_INSTR[0] <= vnum <= SKILL_BOOK_INSTR[1]:
        return vnum - 50400
    return 0


def classify(itype, subtype, vnum, socket0=0, refine_materials=None):
    """(cat, sub) of an item: the page's categories, from the proto."""
    itype, subtype, vnum = int(itype or 0), int(subtype or 0), int(vnum or 0)
    refine = sheet.REFINE_MATERIALS if refine_materials is None else refine_materials
    if itype == ITEM_WEAPON:
        sub = WEAPON_SUBS.get(subtype)
        return (1, sub) if sub else (11, 0)
    if itype == ITEM_ARMOR:
        return ARMOR_SUBS.get(subtype, (11, 0))
    if itype == ITEM_SKILLBOOK:
        job = skill_class(book_skill(vnum, socket0))
        return (6, job + 1) if job >= 0 else (6, 6)
    if itype == ITEM_SKILLFORGET:
        return (6, 5)
    if vnum in PASSIVE_BOOKS:
        return (6, 6)
    if itype == ITEM_METIN:
        if SOUL_STONES[0] <= vnum <= SOUL_STONES[1]:
            grade = (vnum // 100) % 10
            return (7, grade + 1) if grade <= 4 else (7, 0)
        return (7, 0)
    if itype in (ITEM_TREASURE_BOX, ITEM_GIFTBOX):
        return (8, 0)
    if vnum in HERBS:
        return (10, 3)
    if ORES[0] <= vnum <= ORES[1]:
        return (10, 2)
    if itype == ITEM_FISH:
        return (10, 4)
    if vnum in refine or itype == ITEM_MATERIAL or (itype == ITEM_RESOURCE):
        return (10, 1)
    if itype in (ITEM_USE, ITEM_AUTOUSE, ITEM_POTION, ITEM_POLYMORPH):
        return (9, 0)
    return (11, 0)


def class_mask(itype, antiflag, vnum=0, socket0=0):
    """The classes that may use the item, as CLASS_BITS. A skill book is its
    skill's class's; gear is what its antiflags leave; anything else, all."""
    if int(itype or 0) == ITEM_SKILLBOOK:
        job = skill_class(book_skill(vnum, socket0))
        return CLASS_BITS[job] if job >= 0 else ALL_CLASSES
    if int(itype or 0) not in (ITEM_WEAPON, ITEM_ARMOR):
        return ALL_CLASSES
    mask = 0
    for bit, anti in zip(CLASS_BITS, CLASS_ANTIFLAGS):
        if not int(antiflag or 0) & anti:
            mask |= bit
    return mask


def job_class(job):
    """A character's class (0 warrior, 1 ninja, 2 sura, 3 shaman) from its
    race (char.h MAIN_RACE: the class is the race modulo four)."""
    return int(job or 0) % 4


# -----------------------------------------------------------------------------
#  Names as a search reads them: "luk z rogu" finds "Łuk Z Rogu Jelenia".
# -----------------------------------------------------------------------------
_PL_FOLD = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
_PLUS_TAIL = re.compile(r"\s*\+\s*(\d{1,2})\s*$")


def normalize(text):
    """Lower case, no Polish letters (nor any other accent), single spaces."""
    text = str(text or "").translate(_PL_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def split_plus(name):
    """("Miecz", 7) of "Miecz+7"; (name, -1) without one."""
    name = str(name or "").strip()
    m = _PLUS_TAIL.search(name)
    if not m:
        return name, -1
    return name[:m.start()].rstrip(), int(m.group(1))


def like_pattern(query):
    """A LIKE pattern of a normalized fragment, its wildcards escaped."""
    q = normalize(query)
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# -----------------------------------------------------------------------------
#  A price as a player writes it: 500k, 1.5kk, 2kkk, 1 500 000.
# -----------------------------------------------------------------------------
PRICE_MAX = 10 ** 13
_PRICE_K = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(k{1,4})$")
_PRICE_GROUPS = re.compile(r"^\d{1,3}(?:[ .,_]\d{3})+$")


def parse_price(text):
    """The yang a text means, or None for an empty field; ValueError for one
    that means nothing."""
    s = str(text if text is not None else "").strip().lower().replace(" ", " ")
    if not s:
        return None
    s = re.sub(r"\s*yang$", "", s)
    m = _PRICE_K.match(s.replace(" ", ""))
    if m:
        number = m.group(1).replace(",", ".")
        whole, _, frac = number.partition(".")
        scale = 1000 ** len(m.group(2))
        value = int(whole) * scale
        if frac:
            value += int(frac) * scale // (10 ** len(frac))
    elif s.isdigit():
        value = int(s)
    elif _PRICE_GROUPS.match(s):
        value = int(re.sub(r"[ .,_]", "", s))
    else:
        raise ValueError(text)
    if value < 0 or value > PRICE_MAX:
        raise ValueError(text)
    return value


def format_price(value):
    """A yang amount as the page prints it: 1 500 000."""
    return "{:,}".format(int(value or 0)).replace(",", " ")


# -----------------------------------------------------------------------------
#  Filters: every parameter is read against a whitelist, and becomes fixed SQL
#  text with its value as a parameter. Nothing of a request is pasted.
# -----------------------------------------------------------------------------
SORTS = {
    # key: ORDER BY of the offers table (fixed text)
    "deals": "bkey DESC, id DESC",
    "price_asc": "price ASC, id DESC",
    "price_desc": "price DESC, id DESC",
    "unit_asc": "unit ASC, id DESC",
    "plus_desc": "plus DESC, price ASC, id DESC",
    "plus_asc": "plus ASC, price ASC, id DESC",
    "level_desc": "lvl DESC, price ASC, id DESC",
    "level_asc": "lvl ASC, price ASC, id DESC",
    "bonus_count": "nb DESC, nmax DESC, price ASC, id DESC",
    "tier_sum": "tiers DESC, nb DESC, price ASC, id DESC",
    "newest": "id DESC",
}
# The price sorts read the unit price when the page shows unit prices.
UNIT_SORTS = {"price_asc": "unit ASC, id DESC", "price_desc": "unit DESC, id DESC"}
DEFAULT_SORT = "deals"
PER_PAGE = (25, 50, 100)
DEFAULT_PER = 50
MAX_PAGE = 100000
DEFAULT_DEAL_PCT = 40
# Iwakura's Patch 14, point 6B: "Okazja = oferta tansza o min. 25% od zwyklej
# ceny." The badge (Patch 12's "Plakietka tylko, gdy X >= 10%") from 25%, as
# the box under its "?" says - and the Bargain Hunter's own 75% of the day
# price (playerbot_market_habit_rules.h, IsBargain).
DEAL_BADGE_PCT = 25
# Iwakura's Patch 15, point 18C6: "Bezpiecznik: roznica ponad 70% -> zamiast
# 'Okazja' pokazac 'Cena nietypowa' (szara etykieta) i zapisac przedmiot do
# diagnostyki panelu". An offer over UNUSUAL_PCT under its usual price is no
# bargain - it sorts with the offers that have no usual price - and the
# build writes it down (snapshot.Store._write_unusual), UNUSUAL_KEEP at most.
UNUSUAL_PCT = 70
UNUSUAL_KEEP = 2000
NO_REFERENCE_KEY = -1000000          # sorts last under "Najlepsze okazje"
MAX_BONUS_FILTERS = 3
TEXT_MAX = 60
LEVEL_MAX = 255
PLUS_MAX = 19
DAMAGE_MAX = 200

DEFAULTS = {
    "q": "", "cat": "", "sub": "", "pmin": "", "pmax": "", "unit": "0", "lmin": "", "lmax": "",
    "rmin": "", "rmax": "", "cls": "", "mine": "0", "me": "", "nbmin": "", "maxonly": "0", "nmaxmin": "",
    "avgmin": "", "avgmax": "", "sklmin": "", "sklmax": "", "ks": "", "emp": "", "seller": "", "sname": "",
    "shop": "", "vnum": "", "deals": "0", "dmin": str(DEFAULT_DEAL_PCT), "expired": "0",
    "var": "", "rare": "0", "sort": DEFAULT_SORT, "page": "1", "per": str(DEFAULT_PER),
    "b1": "", "b1v": "", "b2": "", "b2v": "", "b3": "", "b3v": "",
}
# The parameters a URL may carry; anything else is ignored.
PARAMS = tuple(DEFAULTS)


def _int(value, low, high):
    s = str(value or "").strip()
    if not s:
        return None
    if not re.match(r"^-?\d{1,12}$", s):
        raise ValueError(value)
    n = int(s)
    if n < low or n > high:
        raise ValueError(value)
    return n


def _flag(value):
    return str(value or "").strip() in ("1", "on", "true", "yes")


def parse_filters(args, bonus_points=(), my_classes=None):
    """(filters, errors) of a request's arguments. `errors` names each field
    whose value means nothing, with that field left out of the filter - the
    page marks it red and sends nothing for it (spec 1E). `bonus_points` is
    the whitelist of bonus lines; `my_classes` {pid: class} the person's own
    characters, for "tylko dla mojej postaci"."""
    get = (lambda k: args.get(k)) if hasattr(args, "get") else (lambda k: None)
    f, errors = {}, {}

    def field(name, fn):
        raw = get(name)
        try:
            value = fn(raw)
        except (TypeError, ValueError):
            errors[name] = "invalid"
            return None
        return value

    q = str(get("q") or "").strip()[:TEXT_MAX]
    if normalize(q):
        f["q"] = normalize(q)
    cat = str(get("cat") or "").strip()
    if cat in CATEGORY_BY_KEY:
        f["cat"] = CATEGORY_BY_KEY[cat][1]
        sub = str(get("sub") or "").strip()
        if (cat, sub) in SUB_BY_KEY:
            f["sub"] = SUB_BY_KEY[(cat, sub)]
    elif cat:
        errors["cat"] = "invalid"
    f["unit"] = _flag(get("unit"))
    for name in ("pmin", "pmax"):
        value = field(name, parse_price)
        if value is not None:
            f[name] = value
    for name, high in (("lmin", LEVEL_MAX), ("lmax", LEVEL_MAX), ("rmin", PLUS_MAX), ("rmax", PLUS_MAX),
                       ("nbmin", 7), ("nmaxmin", 4), ("avgmin", DAMAGE_MAX), ("avgmax", DAMAGE_MAX),
                       ("sklmin", DAMAGE_MAX), ("sklmax", DAMAGE_MAX), ("dmin", 100)):
        value = field(name, lambda v, h=high: _int(v, 0, h))
        if value is not None:
            f[name] = value
    for low, high in (("pmin", "pmax"), ("lmin", "lmax"), ("rmin", "rmax"), ("avgmin", "avgmax"),
                      ("sklmin", "sklmax")):
        if low in f and high in f and f[low] > f[high]:
            errors[high] = "range"
            del f[high]
    cls = str(get("cls") or "").strip()
    if cls in CLASS_KEYS:
        f["cls"] = CLASS_BITS[CLASS_KEYS.index(cls)]
    elif cls:
        errors["cls"] = "invalid"
    me = field("me", lambda v: _int(v, 1, 0xFFFFFFFF))
    if me is not None and my_classes is not None and me in my_classes:
        f["me"] = me
        if _flag(get("mine")):
            f["cls"] = CLASS_BITS[my_classes[me]]
    if _flag(get("maxonly")):
        f["nmaxmin"] = max(1, f.get("nmaxmin") or 1)
    bonuses = []
    allowed = set(int(p) for p in bonus_points)
    for i in range(1, MAX_BONUS_FILTERS + 1):
        point = field("b%d" % i, lambda v: _int(v, 1, 0xFFFF))
        if point is None:
            continue
        if point not in allowed:
            errors["b%d" % i] = "invalid"
            continue
        floor = field("b%dv" % i, lambda v: _int(v, -100000, 100000))
        bonuses.append((point, floor if floor is not None else 1))
    if bonuses:
        f["bonuses"] = bonuses
    ks = str(get("ks") or "").strip()
    if ks == "has":
        f["ks"] = "has"
    elif ks:
        stone = field("ks", lambda v: _int(v, SOUL_STONES[0], SOUL_STONES[1]))
        if stone is not None:
            f["ks"] = stone
    emp = field("emp", lambda v: _int(v, 1, 3))
    if emp is not None:
        f["emp"] = emp
    seller = str(get("seller") or "").strip()
    if seller in ("bot", "person"):
        f["seller"] = seller
    elif seller:
        errors["seller"] = "invalid"
    sname = normalize(str(get("sname") or "")[:TEXT_MAX])
    if sname:
        f["sname"] = sname
    for name in ("shop", "vnum"):
        value = field(name, lambda v: _int(v, 1, 0xFFFFFFFF))
        if value is not None:
            f[name] = value
    if "vnum" in f:
        variant = field("var", lambda v: _int(v, 0, 0xFFFFFFFF))
        if variant is not None:
            f["var"] = variant
    if _flag(get("deals")):
        f["deals"] = f.get("dmin", DEFAULT_DEAL_PCT)
    if _flag(get("rare")):
        f["rare"] = True
    f["expired"] = _flag(get("expired"))
    sort = str(get("sort") or DEFAULT_SORT).strip()
    if sort not in SORTS:
        errors["sort"] = "invalid"
        sort = DEFAULT_SORT
    f["sort"] = sort
    per = field("per", lambda v: _int(v, 1, 1000))
    f["per"] = per if per in PER_PAGE else DEFAULT_PER
    page = field("page", lambda v: _int(v, 1, MAX_PAGE))
    f["page"] = page or 1
    return f, errors


def build_where(f, kinds_table="kinds", shops_table="shops", ignore_category=False):
    """(SQL after WHERE, params) of a filter: fixed text, values as '?'."""
    sql, params = [], []
    if not f.get("expired"):
        sql.append("running = 1")
    if not ignore_category and "cat" in f:
        sql.append("cat = ?")
        params.append(f["cat"])
        if "sub" in f:
            sql.append("sub = ?")
            params.append(f["sub"])
    if "q" in f:
        sql.append("(vnum, var) IN (SELECT vnum, var FROM %s WHERE norm LIKE ? ESCAPE '\\')" % kinds_table)
        params.append(like_pattern(f["q"]))
    if "vnum" in f:
        sql.append("vnum = ?")
        params.append(f["vnum"])
        if "var" in f:
            sql.append("var = ?")
            params.append(f["var"])
    if "shop" in f:
        sql.append("owner = ?")
        params.append(f["shop"])
    column = "unit" if f.get("unit") else "price"
    if "pmin" in f:
        sql.append(column + " >= ?")
        params.append(f["pmin"])
    if "pmax" in f:
        sql.append(column + " <= ?")
        params.append(f["pmax"])
    if "rmax" in f and "rmin" not in f:
        sql.append("plus >= 0")                      # an item with no plus is no "+0 to +N"
    for key, col, op in (("lmin", "lvl", ">="), ("lmax", "lvl", "<="), ("rmin", "plus", ">="),
                         ("rmax", "plus", "<="), ("nbmin", "nb", ">="), ("nmaxmin", "nmax", ">="),
                         ("avgmin", "avg", ">="), ("avgmax", "avg", "<="), ("sklmin", "skl", ">="),
                         ("sklmax", "skl", "<="), ("emp", "emp", "=")):
        if key in f:
            sql.append("%s %s ?" % (col, op))
            params.append(f[key])
    if "cls" in f:
        sql.append("(cls & ?) <> 0")
        params.append(f["cls"])
    for point, floor in f.get("bonuses", ()):
        sql.append("(" + " OR ".join("(a%d = ? AND v%d >= ?)" % (i, i) for i in range(7)) + ")")
        for _ in range(7):
            params.extend((point, floor))
    if f.get("ks") == "has":
        sql.append("ks > 0")
    elif "ks" in f:
        sql.append("(s0 = ? OR s1 = ? OR s2 = ?)")
        params.extend((f["ks"],) * 3)
    if f.get("seller") == "bot":
        sql.append("bot = 1")
    elif f.get("seller") == "person":
        sql.append("bot = 0")
    if "sname" in f:
        sql.append("owner IN (SELECT owner FROM %s WHERE norm LIKE ? ESCAPE '\\')" % shops_table)
        params.append(like_pattern(f["sname"]))
    if "deals" in f:
        sql.append("bkey >= ?")
        params.append(max(DEAL_BADGE_PCT, int(f["deals"])))
    if f.get("rare"):
        sql.append("rare = 1")
    return (" AND ".join(sql) if sql else "1 = 1"), params


def order_by(f):
    if f.get("unit") and f.get("sort") in UNIT_SORTS:
        return UNIT_SORTS[f["sort"]]
    return SORTS.get(f.get("sort"), SORTS[DEFAULT_SORT])


def count_key(f):
    """What the category counts depend on: every filter but the category,
    the sort and the page - so a click on a category reuses them."""
    skip = ("cat", "sub", "sort", "page", "per", "me")
    return repr(sorted((k, v) for k, v in f.items() if k not in skip))


# -----------------------------------------------------------------------------
#  The reference price and the bargain (spec 1H).
# -----------------------------------------------------------------------------
# playerbot_price_rules.h YANG_RATE_POINTS: the world's yang rate's
# multiplier on his sheet (table of 29 September), +25 every 25 past 225.
YANG_RATE_POINTS = ((100, 100), (125, 130), (150, 160), (175, 190), (200, 220), (225, 243))


def yang_rate_price_pct(rate):
    rate = int(rate or 0)
    if rate <= 0:
        return 0
    first, last = YANG_RATE_POINTS[0], YANG_RATE_POINTS[-1]
    if rate <= first[0]:
        return first[1] * rate // first[0]
    if rate >= last[0]:
        return last[1] + (rate - last[0]) * 25 // 25
    for i in range(1, len(YANG_RATE_POINTS)):
        hi = YANG_RATE_POINTS[i]
        if rate > hi[0]:
            continue
        lo = YANG_RATE_POINTS[i - 1]
        return lo[1] + (hi[1] - lo[1]) * (rate - lo[0]) // (hi[0] - lo[0])
    return last[1]


def sheet_price(itype, vnum, socket0=0, plus=-1):
    """Iwakura's sheet price of one unit at x1.0, 0 where his sheet has none
    (or marks the piece the merchant's)."""
    itype, vnum = int(itype or 0), int(vnum or 0)
    if itype in (ITEM_WEAPON, ITEM_ARMOR):
        row = sheet.GEAR.get(vnum - vnum % 10)
        refine = vnum % 10
        if not row or (row[0] >> refine) & 1:
            return 0
        return row[1][refine]
    if itype == ITEM_SKILLBOOK:
        return sheet.BOOKS.get(book_skill(vnum, socket0), 0)
    if itype == ITEM_SKILLFORGET:
        return sheet.FORGET_SCROLLS.get(int(socket0 or 0), 0)
    if itype == ITEM_METIN and SOUL_STONES[0] <= vnum <= SOUL_STONES[1]:
        grade = (vnum // 100) % 10
        named = sheet.SOUL_STONES.get((vnum % 100, grade))
        if named:
            return named
        return sheet.SOUL_STONE_GRADES[grade] if 0 <= grade < len(sheet.SOUL_STONE_GRADES) else 0
    if itype == ITEM_POLYMORPH:
        return sheet.MARBLES.get(int(socket0 or 0), (sheet.MARBLE_BAND[0] + sheet.MARBLE_BAND[1]) // 2)
    return sheet.MATERIALS.get(vnum, 0)


def price_slot(itype, subtype):
    itype = int(itype or 0)
    if itype == ITEM_WEAPON:
        return WEAPON_PRICE_SLOT
    if itype == ITEM_ARMOR:
        return ARMOR_PRICE_SLOT.get(int(subtype or 0), 0)
    return 0


POINT_SKILL_DAMAGE = 121          # mt2009 POINT_SKILL_DAMAGE_BONUS (UM)
POINT_AVERAGE_DAMAGE = 122        # mt2009 POINT_NORMAL_HIT_DAMAGE_BONUS (SR)
POINT_MAX_HP = 6                  # mt2009 POINT_MAX_HP (Maks. PZ)

# Iwakura's Patch 13.5, point 3: one test of a line at its maximum for every
# rule (playerbot_max_line_rules.h) - its top on the server's table, and Max
# HP from 1500, "tak samo jak 2000". The preview marks such a line in the gold
# of a maximal line and prices it at his sheet's "max" column.
MAX_HP_AT_TOP_FROM = 1500

# Community Patch 5, point 11 (playerbot_price_rules.h MAX_LINES_PERCENT): two
# lines at their top x1.7, three x2.5, four and more x4.0.
MAX_LINES_PERCENT = (100, 100, 170, 250, 400)


def line_at_top(point, value, top):
    """The one test: `value` at the line's `top` (0: unknown), or Max HP from
    MAX_HP_AT_TOP_FROM whatever its top."""
    value = int(value or 0)
    if value <= 0:
        return False
    if int(point or 0) == POINT_MAX_HP and value >= MAX_HP_AT_TOP_FROM:
        return True
    return bool(top) and value >= int(top)


def max_lines_percent(count):
    return MAX_LINES_PERCENT[max(0, min(int(count), len(MAX_LINES_PERCENT) - 1))]


# The reference's multipliers of before - his bonus multipliers in floating
# point, Patch 13.5's +6 row as a factor over the plus's own and Patch 13's x3
# as its fallback - are gone with Iwakura's Patch 15, point 18C1-18C2: a piece
# of gear his sheet prices asks price.compose, the bots' own one price, line
# for line, and no x3 is anywhere.


def gear_plus(itype, vnum, plus):
    """A weapon's or armour's plus: its name's, else the vnum's last digit
    (the families are ten vnums); -1 for anything else without one."""
    if int(plus) >= 0:
        return int(plus)
    if int(itype or 0) in (ITEM_WEAPON, ITEM_ARMOR):
        return int(vnum) % 10
    return -1


# Iwakura's Patch 13, point 5A: an item is rare while all the running counters
# of every kingdom hold fewer than RARE_BELOW pieces of it (a piece of gear by
# its vnum, which is its plus too; a book by its skill and a marble by its
# monster, the snapshot's kind). 5D: "Rzadkie" in place of "Okazja".
RARE_BELOW = 10


def is_rare(pieces):
    return int(pieces) < RARE_BELOW


def is_max_line(point, value, tops):
    """A line at its maximum on the server's table - Max HP from 1500 (Patch
    13.5, point 3: line_at_top)."""
    return line_at_top(point, value, tops.get(int(point or 0), 0))


def line_tier(point, job=-1):
    """The higher of a line's PvE and PvP rating (18D's LineTier), with the
    job's +1 when the reader's class is known; 0 for a line he does not rate."""
    row = sheet.BONUS_TIERS.get(int(point or 0))
    if not row:
        return 0
    pve, pvp, pve_jobs, pvp_jobs, _label = row

    def with_job(tier, jobs):
        if tier > 0 and 0 <= job < 4 and jobs & (1 << job):
            tier += 1
        return min(6, tier)
    return max(with_job(pve, pve_jobs), with_job(pvp, pvp_jobs))


def tier_pair(point):
    row = sheet.BONUS_TIERS.get(int(point or 0))
    return (row[0], row[1]) if row else (0, 0)


# Iwakura's Patch 13.5, point 5 (playerbot_moonlight_rules.h's
# YoungChestPercent): a bot's Moonlight chest asks half its normal price in a
# world's first twelve hours and three quarters in the next twelve, and the
# preview's reference is that share too ("zeby nie oznaczal wszystkich jako
# Okazja"). A world's age is the cores' - the oldest account - and an unknown
# one (under nought) is an old world's.
MOONLIGHT_CHEST_VNUM = 50011
YOUNG_CHEST_HALF_SECONDS = 12 * 3600
YOUNG_CHEST_FULL_SECONDS = 24 * 3600
YOUNG_CHEST_FIRST_PERCENT = 50
YOUNG_CHEST_SECOND_PERCENT = 75
YOUNG_CHEST_NORMAL_PERCENT = 100


def young_chest_percent(world_age):
    age = -1 if world_age is None else int(world_age)
    if age < 0 or age >= YOUNG_CHEST_FULL_SECONDS:
        return YOUNG_CHEST_NORMAL_PERCENT
    return YOUNG_CHEST_FIRST_PERCENT if age < YOUNG_CHEST_HALF_SECONDS else YOUNG_CHEST_SECOND_PERCENT


def young_world_factor(vnum, world_age):
    """The share of the normal reference a kind's reference is at this age:
    the chest's young share, 1 for everything else."""
    if int(vnum or 0) != MOONLIGHT_CHEST_VNUM:
        return 1.0
    return young_chest_percent(world_age) / 100.0


# Iwakura's Patch 14, point 3 (playerbot_gear_value_rules.h's Level30Cut): a
# level-30 weapon at +0..+3 of the six families asks his sheet x0.75 in a
# world older than 48 hours, and a copy under 29% average another 35..65% off,
# drawn every eight hours for each family and kingdom, while that kingdom's
# market holds over a hundred of the family at +0..+3. A piece of two lines or
# more stands on its +6 row (point 4 of 13.5) and takes neither. The
# preview's reference follows, so the bots' cut lines are not all "Okazja".
LEVEL30_CUT_FAMILIES = (290, 1170, 2150, 3210, 5110, 7160)
LEVEL30_CUT_MAX_PLUS = 3
LEVEL30_CUT_OLD_WORLD_SECONDS = 48 * 3600
LEVEL30_CUT_OLD_WORLD_PERCENT = 75
LEVEL30_CUT_OVERSUPPLY_OVER = 100
LEVEL30_CUT_AVERAGE_UNDER = 29
LEVEL30_CUT_DRAW_MIN = 35
LEVEL30_CUT_DRAW_MAX = 65
LEVEL30_CUT_DRAW_SECONDS = 8 * 3600
# A piece of two lines or more stands on its +6 row (Patch 13.5, point 4) and
# takes no cut (playerbot_gear_value_rules.h LOW_PLUS_LINES_MIN).
LOW_PLUS_MIN_LINES = 2
# The kingdom of a stand's map (playerbot_empire_rules::GetMapOwnerEmpire).
MAP_OWNER_EMPIRE = {1: 1, 3: 1, 4: 1, 5: 1, 21: 2, 23: 2, 24: 2, 25: 2, 41: 3, 43: 3, 44: 3, 45: 3}


def level30_cut_family(vnum):
    """0..5 for a level-30 weapon at +0..+3 of the six families, else -1."""
    vnum = int(vnum or 0)
    for i, first in enumerate(LEVEL30_CUT_FAMILIES):
        if first <= vnum <= first + LEVEL30_CUT_MAX_PLUS:
            return i
    return -1


def level30_cut_slot(now):
    now = int(now or 0)
    return now // LEVEL30_CUT_DRAW_SECONDS if now > 0 else 0


def level30_oversupply_cut(slot, empire, family):
    """B's cut 35..65: the core's hash, in 32 bits."""
    m = 0xFFFFFFFF
    slot = int(slot)
    h = ((slot & m) * 2654435761) & m
    h ^= (((slot >> 32) & m) * 0x27D4EB2F) & m
    h ^= ((int(empire) + 1) * 0x85EBCA6B) & m
    h ^= ((int(family) + 1) * 0xC2B2AE35) & m
    h ^= 0x4C33300E
    h ^= h >> 16
    h = (h * 0x7FEB352D) & m
    h ^= h >> 15
    h = (h * 0x846CA68B) & m
    h ^= h >> 16
    return LEVEL30_CUT_DRAW_MIN + h % (LEVEL30_CUT_DRAW_MAX - LEVEL30_CUT_DRAW_MIN + 1)


def level30_cut_permille(vnum, plus, lines, average, world_age, units, drawn):
    """The share of his sheet a piece keeps, in thousandths (1000: no cut).
    `lines` its ordinary lines, `units` the family's +0..+3 on the kingdom's
    market (under 0 not counted), `drawn` the period's cut."""
    family = level30_cut_family(vnum)
    plus = int(plus)
    if family < 0 or not 0 <= plus <= LEVEL30_CUT_MAX_PLUS or (int(lines) >= LOW_PLUS_MIN_LINES):
        return 1000
    old = LEVEL30_CUT_OLD_WORLD_PERCENT if world_age is not None and int(world_age) >= LEVEL30_CUT_OLD_WORLD_SECONDS else 100
    cut = 0
    if units is not None and int(units) > LEVEL30_CUT_OVERSUPPLY_OVER and int(average or 0) < LEVEL30_CUT_AVERAGE_UNDER:
        cut = max(LEVEL30_CUT_DRAW_MIN, min(LEVEL30_CUT_DRAW_MAX, int(drawn)))
    return 1000 * old // 100 * (100 - cut) // 100


def level30_market_key(map_index, seller_empire):
    """The kingdom a stand's line counts in: its map's, else its seller's."""
    return MAP_OWNER_EMPIRE.get(int(map_index or 0), int(seller_empire or 0))


def level30_cut_keep(vnum, plus, lines, average, world_age, counts, empire, now=None):
    """The thousandths of his sheet a line keeps (1000 for anything else):
    `counts` {(empire, family): units} of the snapshot's running lines - what
    price.compose takes as the cut on the piece's own row."""
    family = level30_cut_family(vnum)
    if family < 0:
        return 1000
    units = counts.get((int(empire or 0), family), 0) if counts is not None and empire else -1
    drawn = level30_oversupply_cut(level30_cut_slot(now if now is not None else time.time()), empire, family) \
        if empire else 0
    return level30_cut_permille(vnum, plus, lines, average, world_age, units, drawn)


def level30_cut_factor(vnum, plus, lines, average, world_age, counts, empire, now=None):
    """The same share as a factor (1.0 for anything else)."""
    return level30_cut_keep(vnum, plus, lines, average, world_age, counts, empire, now) / 1000.0


def bargain_pct(unit, reference):
    """1 - price / reference in whole percent; None without a reference."""
    if not reference or reference <= 0 or unit is None:
        return None
    return int(math.floor((1.0 - float(unit) / float(reference)) * 100.0 + 0.5))


def bargain_key(pct):
    return NO_REFERENCE_KEY if pct is None else int(pct)


def median(values):
    values = sorted(values)
    n = len(values)
    if not n:
        return None
    mid = n // 2
    return float(values[mid]) if n % 2 else (values[mid - 1] + values[mid]) / 2.0


HISTORY_MIN_OFFERS = 5
HISTORY_DAYS = 7

# Iwakura's Patch 15, point 18C5: "gdy na rynku jest min. 5 ofert tego samego
# przedmiotu z tym samym plusem i ta sama liczba bonusow - zwykla cena =
# mediana tych ofert, gdy mniej - zwykla cena = wspolna funkcja ceny". The
# running offers of one vnum (which is the plus), one variant (a book's
# skill, a marble's monster) and one count of ordinary bonus lines; the week's
# median of Patch 12's 1H and Patch 14's 6B band round his sheet are gone with
# it.
MARKET_MIN_OFFERS = 5

# Where an offer's usual price came from (the offers table's `rsrc`, the "?"
# box names it): nothing, the one price (a piece of gear: price.compose; else
# his sheet's day price), a refine material's day price with its supply, the
# market's median. 3 was the week's median of before Patch 15 and is never
# reused.
REF_NONE, REF_SHEET, REF_MATERIAL, REF_MARKET = 0, 1, 2, 4


def is_unusual(pct):
    """18C6: over UNUSUAL_PCT under the usual price."""
    return pct is not None and int(pct) > UNUSUAL_PCT


def formula_text(composed):
    """The one price's steps in a few words, for the diagnostics: the row and
    why, WRB, Cena SR, the lines' premium, the price."""
    if not composed:
        return ""
    why = {0: "own", 1: "bonus_base", 2: "low_plus_lines"}.get(composed.get("why"), "?")
    return "row=+%d(%s) sheet=%d wrb=%d sr=%d premium=%d%% price=%d" % (
        composed["row"], why, composed["sheet"], composed["gear_base"], composed["after_average"],
        composed["premium_pct"], composed["price"])


UNUSUAL_COLUMNS = ("time", "item_id", "vnum", "plus", "var", "owner", "bot", "lines", "avg", "skl", "unit",
                   "reference", "pct", "source", "market_offers", "formula", "how")
REF_WORDS = {REF_NONE: "none", REF_SHEET: "formula", REF_MATERIAL: "material", REF_MARKET: "market_median"}


def unusual_header():
    return "#" + "\t".join(UNUSUAL_COLUMNS)


def unusual_row(when, e):
    lines = ",".join("%d:%d" % (int(p), int(v)) for p, v in e.get("lines", ()))
    return "\t".join(str(x) for x in (
        int(when), e["id"], e["vnum"], e["plus"], e["var"], e["owner"], e["bot"], lines or "-", e["avg"], e["skl"],
        int(round(e["unit"])), int(round(e["ref"])), e["pct"], REF_WORDS.get(e["rsrc"], "?"), e["rn"],
        int(round(e["fref"])), e.get("how") or "-"))


# The "ludzka pomylka" mark of a line that slipped is gone with the slip
# itself (Iwakura's Patch 15, point 16D: the bots never ask ten times a price
# any more); an offer far under its usual price is "Cena nietypowa" (18C6)
# and one far over it says how much dearer it is.


# -----------------------------------------------------------------------------
#  The TP's answers (playerbot_market_tp_rules.h StatusWord) and the page's
#  message keys for them. 'offline' is the panel's own: nobody answered in
#  fifteen seconds, or the character left between the claim and the move.
# -----------------------------------------------------------------------------
TP_STATUS_KEYS = {
    "done": "tp_done", "not_allowed": "tp_not_allowed", "no_shop": "tp_no_shop",
    "shop_closed": "tp_shop_closed", "other_channel": "tp_other_channel", "dead": "tp_dead",
    "dungeon": "tp_dungeon", "guild_war": "tp_guild_war", "combat": "tp_combat", "busy": "tp_busy",
    "cooldown": "tp_cooldown", "no_gold": "tp_no_gold", "bad_args": "tp_bad_args", "failed": "tp_failed",
    "offline": "tp_offline", "cancelled": "tp_offline",
}
TP_FINAL = frozenset(TP_STATUS_KEYS)
TP_WAIT_SECONDS = 15
TP_COOLDOWN_SECONDS = 30
TP_POLL_SECONDS = 1
# The fare the operator may set (playerbot_market_tp_rules.h COST_MAX).
TP_COST_MAX = 2000000000


# -----------------------------------------------------------------------------
#  Ten requests a second from one browser (spec 1L): a token bucket a key.
# -----------------------------------------------------------------------------
class RateLimiter(object):
    def __init__(self, rate=10.0, burst=10.0, clock=time.monotonic, max_keys=4096):
        self.rate, self.burst, self.clock, self.max_keys = float(rate), float(burst), clock, max_keys
        self.buckets = {}

    def allow(self, key):
        now = self.clock()
        tokens, stamp = self.buckets.get(key, (self.burst, now))
        tokens = min(self.burst, tokens + (now - stamp) * self.rate)
        if len(self.buckets) >= self.max_keys and key not in self.buckets:
            # Forget the quietest keys rather than grow without bound.
            for old in sorted(self.buckets, key=lambda k: self.buckets[k][1])[: self.max_keys // 4]:
                del self.buckets[old]
        if tokens < 1.0:
            self.buckets[key] = (tokens, now)
            return False
        self.buckets[key] = (tokens - 1.0, now)
        return True
