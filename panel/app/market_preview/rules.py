# =============================================================================
#  /market -- the market preview's pure rules (Iwakura's Patch 12, point 1).
#
#  No Flask, no database: what a request's parameters mean, the one list of
#  categories, the SQL a filter becomes (fixed text, every value a parameter),
#  the sort orders, a price as a player writes it, a name as a search reads
#  it, the reference price and the bargain, the "human slip" mark, the bonus
#  lines' ratings and the TP's answers. tests/market_preview_test.py tests all
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
DEAL_BADGE_PCT = 10                  # "Plakietka tylko, gdy X >= 10%"
DEAL_SUSPECT_PCT = 80                # "Gdy X >= 80% - dodatkowo maly znak ?"
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
    "shop": "", "vnum": "", "deals": "0", "dmin": str(DEFAULT_DEAL_PCT), "hideslip": "1", "expired": "0",
    "var": "", "sort": DEFAULT_SORT, "page": "1", "per": str(DEFAULT_PER),
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
    f["hideslip"] = str(get("hideslip") if get("hideslip") is not None else "1").strip() != "0"
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
    if f.get("hideslip", True):
        sql.append("slip = 0")
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


def _tier_pct(tiers, value):
    pct = 100
    for start, p in tiers:
        if value >= start:
            pct = p
    return pct


POINT_SKILL_DAMAGE = 121          # mt2009 POINT_SKILL_DAMAGE_BONUS (UM)
POINT_AVERAGE_DAMAGE = 122        # mt2009 POINT_NORMAL_HIT_DAMAGE_BONUS (SR)


def bonus_multiplier(slot, level, lines, tops):
    """His sheet's bonus multiplier of a piece (GetPlayerBotBonusPricePercent's
    rows): each line on the slot and level band its own row names, the
    maximum roll's or any other value's; a weapon's average and skill damage
    by their tiers. `lines` [(point, value)], `tops` {point: top roll}. 1.0
    for anything the sheet does not price."""
    if not slot:
        return 1.0
    pct = 1.0
    for point, value in lines:
        if not point or not value:
            continue
        if slot == WEAPON_PRICE_SLOT and point == POINT_AVERAGE_DAMAGE:
            pct *= _tier_pct(sheet.AVERAGE_TIERS, value) / 100.0
            continue
        if slot == WEAPON_PRICE_SLOT and point == POINT_SKILL_DAMAGE:
            if value >= sheet.SKILL_TIERS[0][0]:
                pct *= _tier_pct(sheet.SKILL_TIERS, value) / 100.0
            continue
        for slots, row_point, max_pct, other_pct, lv_from, lv_to, own_top in sheet.BONUS_ROWS:
            if row_point != point or not slots & slot or not lv_from <= int(level or 0) <= lv_to:
                continue
            top = own_top or tops.get(point, 0)
            pct *= (max_pct if top and value >= top else other_pct) / 100.0
            break
    return pct


def is_max_line(point, value, tops):
    top = tops.get(int(point or 0), 0)
    return bool(top) and int(value or 0) >= top


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


HISTORY_MIN_OFFERS = 5            # "jesli mniej niz 5 ofert w historii - cena z CENY"
HISTORY_DAYS = 7


# -----------------------------------------------------------------------------
#  "Ludzka pomylka" (Community Patch 5, point 6; market.md "A slip is marked by
#  its item id"): a one-unit line of a skill book or an upgrade material whose
#  item id the bots' draw marks, asking twice its fair price or more - or any
#  such line at five times. The draw is the core's own hash.
# -----------------------------------------------------------------------------
def nav_hash(value):
    """PlayerBotNavHash (playerbot_navigation.h), 32-bit."""
    value &= 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value


def slip_drawn(item_id):
    return bool(item_id) and nav_hash(int(item_id) ^ 0x534C4950) % 1000 == 0


def is_slip(item_id, count, is_book, is_refine, unit, fair_unit):
    if int(count or 0) != 1 or not (is_book or is_refine) or not fair_unit or fair_unit <= 0:
        return False
    if unit >= fair_unit * 5:
        return True
    return slip_drawn(item_id) and unit >= fair_unit * 2


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
