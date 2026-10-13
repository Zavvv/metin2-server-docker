# =============================================================================
#  /market -- what a piece of gear his sheet prices asks: steps 1 to 3 of
#  Iwakura's order, the one definition of the price (his Patch 15, point 18C1:
#  "Jedna wspolna funkcja ceny - ta sama dla wystawiania przez bota, barteru,
#  Bonowacza i ceny odniesienia w Podgladzie rynku. Panel nie moze miec
#  wlasnego wzoru").
#
#  This is playerbot_gear_price_rules.h line for line and integer for integer
#  (the overlay's linux-port/overlays/playerbot/src/game/src): the bots ask
#  the C++ for every piece they list, sell in a barter, bonus as the Bonowacz
#  or judge as buyers, and the preview's reference asks this. The panel's
#  container carries no overlay and Python is no C++, so the code cannot be
#  one; the data is (sheet.py is rendered from the same tables) and so is the
#  arithmetic: tests/data/gear_price_cases.tsv and gear_price_lines.tsv hold
#  the cases both are tested on (tests/playerbot_gear_price_rules_test.cpp and
#  tests/market_preview_price_test.py), Buty Feniksa of 18D among them. A
#  change to one without the other fails both tests.
#
#  Integer arithmetic throughout, divisions truncated toward zero as C++'s
#  are (tdiv): a reference a yang off the bots' own price is a reference that
#  is wrong.
# =============================================================================

try:
    from . import sheet
except ImportError:                                  # loaded as a plain module by a test
    import sheet                                     # noqa: F401

MAX_LINES = 5
PRICE_CEILING = 0xFFFFFFFF
LINES_PRODUCT_CAP_PCT = 10000
INFLATION_ONE = 10000
PRICE_INDEX_ONE_MILLI = 1000

# playerbot_price_rules.h / playerbot_max_line_rules.h
MAX_LINES_PERCENT = (100, 100, 170, 250, 400)
AVERAGE_DAMAGE_MAX_FROM = 40
MAX_HP_AT_TOP_FROM = 1500

try:
    from . import overrides
except ImportError:
    import overrides
PRICING_OPTIONS = overrides.options({})

# playerbot_gear_value_rules.h
SHEET_ROWS = 10
LOW_PLUS_LINES_MAX_PLUS = 7
LOW_PLUS_LINES_MIN = 1
LOW_PLUS_SHEET_ROW = 7
AVERAGE_FLOOR_ROW5_FROM, AVERAGE_FLOOR_ROW6_FROM = 30, 40
AVERAGE_FLOOR_ROW5, AVERAGE_FLOOR_ROW6 = 5, 6
AVERAGE_PCT_NONE = 100
BASE_SLOT_NONE, BASE_SLOT_JEWEL, BASE_SLOT_ARMOUR = 0, 1, 2
BASE_JEWEL_ROW_CAP, BASE_ARMOUR_ROW_CAP = 8, 7
BASE_TOP_PERCENT, BASE_MIDDLE_PERCENT = 75, 40
BASE_MIN_TIER, BASE_MAX_TIER = 4, 6
MAX_HP_BASE_TIER, MAX_HP_BASE_TOP = 6, 2000
LEVEL30_CUT_PERMILLE_ONE = 1000
INT_SLOT_OTHER, INT_SLOT_SHAMAN_WEAPON, INT_SLOT_SHIELD = 0, 1, 2
INT_ROWS = {INT_SLOT_SHAMAN_WEAPON: (300, 250), INT_SLOT_SHIELD: (260, 200)}
HELMET_SHEET_PERCENT = 50

ROW_OWN, ROW_BONUS_BASE, ROW_LOW_PLUS_LINES = 0, 1, 2

# The mt2009 POINT numbers a line of player.item carries (sheet.py's keys).
POINT_MAX_HP = 6
POINT_IQ = 15
POINT_SKILL_DAMAGE = 121
POINT_NORMAL_HIT_DAMAGE = 122

# item_proto's types, subtypes and the price slots of playerbot_bonus.h.
ITEM_WEAPON, ITEM_ARMOR = 1, 2
WEAPON_BELL, WEAPON_FAN, WEAPON_ARROW, WEAPON_QUIVER = 4, 5, 6, 9
ARMOR_BODY, ARMOR_HEAD, ARMOR_SHIELD, ARMOR_WRIST, ARMOR_FOOTS, ARMOR_NECK, ARMOR_EAR = 0, 1, 2, 3, 4, 5, 6
PRICE_SLOT_HEAD, PRICE_SLOT_BODY, PRICE_SLOT_SHIELD, PRICE_SLOT_FOOTS = 1, 2, 4, 8
PRICE_SLOT_WRIST, PRICE_SLOT_NECK, PRICE_SLOT_EAR, PRICE_SLOT_WEAPON = 16, 32, 64, 128
ARMOR_PRICE_SLOT = {ARMOR_BODY: PRICE_SLOT_BODY, ARMOR_HEAD: PRICE_SLOT_HEAD, ARMOR_SHIELD: PRICE_SLOT_SHIELD,
                    ARMOR_WRIST: PRICE_SLOT_WRIST, ARMOR_FOOTS: PRICE_SLOT_FOOTS, ARMOR_NECK: PRICE_SLOT_NECK,
                    ARMOR_EAR: PRICE_SLOT_EAR}
# CItem::GetAttributeSetIndex: the column of world.item_attr a piece rolls by
# (weapon, body, wrist, foots, neck, head, shield, ear).
ARMOR_ATTRIBUTE_SET = {ARMOR_BODY: 1, ARMOR_WRIST: 2, ARMOR_FOOTS: 3, ARMOR_NECK: 4, ARMOR_HEAD: 5,
                       ARMOR_SHIELD: 6, ARMOR_EAR: 7}
ATTRIBUTE_MAX_LEVEL = 5
ITEM_ANTIFLAG_CLASSES = (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5)


def tdiv(a, b):
    """C++'s integer division: truncated toward zero."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def saturate(value):
    return PRICE_CEILING if value > PRICE_CEILING else value


# ---------------------------------------------------------------- a line
def damage_tier_pct(tiers, value):
    """DamageTierPct: `tiers` ((from, pct), ...)."""
    if not tiers:
        return 100
    v2 = 2 * int(value)
    prev_x = 2 * (int(tiers[0][0]) - 1)
    prev_pct = 100
    if v2 <= prev_x:
        return 100
    for i, (frm, pct) in enumerate(tiers):
        end = int(tiers[i + 1][0]) - 1 if i + 1 < len(tiers) else int(frm)
        mid_x = int(frm) + end
        if v2 <= mid_x:
            return prev_pct + tdiv((int(pct) - prev_pct) * (v2 - prev_x), max(1, mid_x - prev_x))
        prev_x = mid_x
        prev_pct = int(pct)
    return prev_pct


def find_line_rows(rows, point, slot, level):
    """FindLineRows: `rows` ((slots, point, max, other, from, to, top), ...);
    the slot's row (top 0) and a point-13 row (a top of its own), the first
    of each. Each answer (max, other, top) or None."""
    slot_rule = top_rule = None
    for slots, row_point, mx, other, lv_from, lv_to, top in rows:
        if int(row_point) != int(point) or not (int(slots) & int(slot)) or \
                not int(lv_from) <= int(level) <= int(lv_to):
            continue
        if int(top) == 0 and slot_rule is None:
            slot_rule = (mx, other, 0)
        elif int(top) != 0 and top_rule is None:
            top_rule = (mx, other, int(top))
    return [slot_rule, top_rule]


_ROWS_BY_POINT = {}


def rows_of_point(point):
    """sheet.BONUS_ROWS of one line, in the table's order (what
    find_line_rows walks; the rest it would skip)."""
    if not _ROWS_BY_POINT:
        for row in sheet.BONUS_ROWS:
            _ROWS_BY_POINT.setdefault(int(row[1]), []).append(row)
    return _ROWS_BY_POINT.get(int(point), ())


def apply_int_row(found, int_slot):
    row = INT_ROWS.get(int_slot)
    if row:
        key = 'intq:%s:' % ('shield' if int_slot == INT_SLOT_SHIELD else 'shaman_weapon')
        row = (overrides.resulting_percent(key+'max', row[0], PRICING_OPTIONS),
               overrides.resulting_percent(key+'other', row[1], PRICING_OPTIONS))
        found[0] = (row[0], row[1], 0)
    return found


def is_line_at_top(max_hp, value, table_top, written_top=0):
    if value <= 0:
        return False
    if max_hp and value >= MAX_HP_AT_TOP_FROM:
        return True
    return (table_top > 0 and value >= table_top) or (written_top > 0 and value >= written_top)


def line_percent(value, table_max, slot_rule, top_rule, max_hp):
    if value <= 0:
        return 100
    if top_rule and top_rule[2] > 0 and value >= top_rule[2]:
        return top_rule[0]
    if slot_rule:
        return slot_rule[0] if is_line_at_top(max_hp, value, table_max, 0) else slot_rule[1]
    if top_rule:
        return top_rule[1]
    return 100


def line_pct(found, point, value, table_max, max_hp):
    """LinePct: (pct, at_top)."""
    if not point or value <= 0:
        return 100, False
    slot_rule, top_rule = found
    at_top = is_line_at_top(max_hp, value, table_max, top_rule[2] if top_rule else 0)
    return line_percent(value, table_max, slot_rule, top_rule, max_hp), at_top


# ---------------------------------------------------------------- the lines
class Line(object):
    __slots__ = ("pct", "at_top", "average", "ordinary", "tier", "value", "top", "base_pct", "point")

    def __init__(self, pct=100, at_top=False, average=False, ordinary=False, tier=0, value=0, top=0,
                 base_pct=100, point=0):
        self.pct, self.at_top, self.average, self.ordinary = pct, bool(at_top), bool(average), bool(ordinary)
        self.tier, self.value, self.top, self.base_pct, self.point = int(tier), int(value), int(top), \
            int(base_pct), int(point)


def base_line_for(max_hp, tier, value, slot_top, pct):
    """BaseLineFor: (tier, value, top, pct)."""
    tier = max(tier, MAX_HP_BASE_TIER) if max_hp else tier
    return tier, int(value), MAX_HP_BASE_TOP if max_hp else int(slot_top), int(pct)


def max_lines_percent(count):
    return MAX_LINES_PERCENT[max(0, min(int(count), len(MAX_LINES_PERCENT) - 1))]


def compound(product, pct, cap):
    product = tdiv(product * pct, 100)
    return cap if product > cap else product


def classic(lines, without_average, cap=LINES_PRODUCT_CAP_PCT, policy=None):
    """Classic: (product, at_top_lines, premium)."""
    product, at_top = 100, 0
    policy = PRICING_OPTIONS if policy is None else policy
    for line in lines:
        if line.at_top:
            at_top += 1
        if not without_average or not line.average:
            product = compound(product, line.pct, 1000000 if policy.get('cap_active') else cap)
    product = overrides.soft_cap(product, policy)
    return product, at_top, tdiv(product * max_lines_percent(at_top), 100) - 100


def ordinary_lines(lines):
    return sum(1 for line in lines if line.ordinary)


# ---------------------------------------------------------------- the rows
def low_plus_lines_apply(plus, lines):
    return 0 <= plus <= LOW_PLUS_LINES_MAX_PLUS and lines >= LOW_PLUS_LINES_MIN


def low_plus_lines_row(rows, plus, lines):
    if not low_plus_lines_apply(plus, lines):
        return plus
    for row in range(LOW_PLUS_SHEET_ROW, plus, -1):
        if rows[row] > 0 and rows[row] > rows[plus]:
            return row
    return plus


def is_low_plus_lines_piece(rows, plus, lines):
    return low_plus_lines_apply(plus, lines) and low_plus_lines_row(rows, plus, lines) != plus


def line_points(tier, value, top):
    if tier < BASE_MIN_TIER or value <= 0 or top <= 0:
        return 0
    grid = ((1, 0, 0), (2, 1, 0), (3, 2, 1))
    share = value * 100
    column = 0 if share >= top * BASE_TOP_PERCENT else (1 if share >= top * BASE_MIDDLE_PERCENT else 2)
    return grid[min(tier, BASE_MAX_TIER) - BASE_MIN_TIER][column]


def bonus_base_row(points, slot):
    if slot == BASE_SLOT_NONE or points <= 0:
        return 0
    row = 8 if points >= 6 else (7 if points >= 3 else (6 if points == 2 else 4))
    cap = BASE_JEWEL_ROW_CAP if slot == BASE_SLOT_JEWEL else BASE_ARMOUR_ROW_CAP
    return min(row, cap)


def evaluate_bonus_base_at(rows, plus, classic_row, slot, base_lines, classic_pct, cap):
    """EvaluateBonusBaseAt: a dict of points, row, applies, zero_point_pct,
    classic_core, base_core, wins."""
    out = {"points": 0, "row": 0, "applies": False, "zero_point_pct": 100, "classic_core": 0, "base_core": 0,
           "wins": False}
    if plus < 0 or plus >= SHEET_ROWS or slot == BASE_SLOT_NONE:
        return out
    if classic_row < plus or classic_row >= SHEET_ROWS:
        classic_row = plus
    for tier, value, top, pct in base_lines:
        points = line_points(tier, value, top)
        out["points"] += points
        if points == 0 and value > 0:
            out["zero_point_pct"] = tdiv(out["zero_point_pct"] * (pct if pct > 0 else 100), 100)
            if out["zero_point_pct"] > cap:
                out["zero_point_pct"] = cap
    out["row"] = bonus_base_row(out["points"], slot)
    out["classic_core"] = tdiv(rows[classic_row] * (100 + classic_pct), 100)
    out["applies"] = out["row"] > classic_row
    if not out["applies"]:
        return out
    out["base_core"] = tdiv(rows[out["row"]] * out["zero_point_pct"], 100)
    out["wins"] = out["base_core"] > out["classic_core"]
    return out


def average_floor_row(average):
    if average >= AVERAGE_FLOOR_ROW6_FROM:
        return AVERAGE_FLOOR_ROW6
    if average >= AVERAGE_FLOOR_ROW5_FROM:
        return AVERAGE_FLOOR_ROW5
    return 0


def average_floor_applies(plus, floor_row):
    return plus >= 0 and plus < floor_row < SHEET_ROWS


def level30_cut_price(price, keep):
    if price <= 0 or keep >= LEVEL30_CUT_PERMILLE_ONE:
        return price
    kept = tdiv(price * max(0, keep), LEVEL30_CUT_PERMILLE_ONE)
    return kept if kept > 0 else 1


# ---------------------------------------------------------------- the price
def scale_sheet(base, curve_pct, inflation):
    """ScalePlayerBotIwakuraPrice."""
    if base <= 0:
        return 0
    curved = tdiv(base * (curve_pct if curve_pct > 1 else 1), 100)
    if curved >= PRICE_CEILING:
        return PRICE_CEILING
    return saturate(tdiv(curved * inflation, INFLATION_ONE))


def apply_premium(price, premium):
    if premium <= 0:
        return price
    value = saturate(tdiv(price * (100 + premium), 100))
    return value if value > 1 else 1


def inflation_of(index_milli):
    """PriceIndexFactor: the index in thousandths as ten-thousandths."""
    index_milli = int(index_milli or 0)
    return INFLATION_ONE if index_milli <= 0 else index_milli * (INFLATION_ONE // PRICE_INDEX_ONE_MILLI)


class Facts(object):
    def __init__(self, rows, plus, weapon=False, base_slot=BASE_SLOT_NONE, lines=(), stones_pct=100,
                 curve_pct=100, inflation=INFLATION_ONE, average_pct=AVERAGE_PCT_NONE, average=0,
                 level30_keep=LEVEL30_CUT_PERMILLE_ONE, cap=LINES_PRODUCT_CAP_PCT):
        self.rows = tuple(int(r) for r in rows)
        self.plus, self.weapon, self.base_slot = int(plus), bool(weapon), int(base_slot)
        self.lines = list(lines)[:MAX_LINES]
        self.stones_pct, self.curve_pct, self.inflation = int(stones_pct), int(curve_pct), int(inflation)
        self.average_pct, self.average = int(average_pct), int(average)
        self.level30_keep, self.cap = int(level30_keep), int(cap)
        self.pricing_options = dict(PRICING_OPTIONS)


def _compose_precise(f, out):
    from decimal import Decimal
    D = lambda x: Decimal(str(x))
    def soft(product):
        policy = f.pricing_options
        full = D(policy.get('full', 10000))
        return product if not policy.get('cap_active') or product <= full else full + (product-full)*D(policy.get('excess', 0))/100
    lines = f.lines
    out['ordinary_lines'] = ordinary_lines(lines)
    out['low_row'] = low_plus_lines_row(f.rows, f.plus, out['ordinary_lines'])
    row = out['low_row']
    product, zero, points, max_count = D(100), D(100), 0, 0
    for line in lines:
        max_count += int(line.at_top)
        if not f.weapon or not line.average:
            product *= D(line.pct)/100
        earned = line_points(line.tier, line.value, line.top)
        points += earned
        if not earned and line.value > 0:
            zero *= D(line.pct)/100
    product = soft(product*max_lines_percent(max_count)/100)
    zero = soft(zero)
    base_row = bonus_base_row(points, f.base_slot)
    out['base'] = dict(points=points, row=base_row, applies=False, wins=False, zero_point_pct=float(zero))
    why = ROW_LOW_PLUS_LINES if row != f.plus else ROW_OWN
    if not f.weapon and f.base_slot != BASE_SLOT_NONE and base_row > row and f.rows[base_row]*zero > f.rows[row]*product:
        row, why, product = base_row, ROW_BONUS_BASE, zero
        out['base'].update(applies=True, wins=True)
    out.update(row=row, why=why, sheet_row=f.rows[row])
    if f.rows[row] <= 0:
        return out
    keep = f.level30_keep if row == f.plus else LEVEL30_CUT_PERMILLE_ONE
    stones = f.stones_pct if f.stones_pct > 0 else 100
    scale = D(max(1, f.curve_pct))/100*f.inflation/INFLATION_ONE
    sheet_value = D(f.rows[row])*keep/1000
    base = sheet_value*stones/100*scale
    after = base
    floor = D(0)
    if f.weapon:
        floor_row = average_floor_row(f.average)
        if row == f.plus and average_floor_applies(f.plus, floor_row) and f.rows[floor_row] > 0:
            floor = D(f.rows[floor_row])*keep/1000*stones/100*scale
            out['floor_row'] = floor_row
        after = max(base*f.average_pct/100, floor)
        out.update(average_applied=f.average_pct != AVERAGE_PCT_NONE or floor > 0,
                   average_price_sr=float(base*f.average_pct/100), average_floor_wins=floor > base*f.average_pct/100)
    precise = after*product/100
    out.update(priced=True, sheet=float(sheet_value), gear_base=float(base), after_average=float(after),
               floor=float(floor), product=float(product), at_top_lines=max_count, classic_pct=float(product-100),
               premium_pct=float(product-100), price=min(PRICE_CEILING, int(precise)), precise_price=str(precise),
               level30_applied=sheet_value != f.rows[row])
    return out


def listing_quote(composed, c9, policy, *, floor=0, count=1, extra=100, spread=100,
                  bonowacz=0, habit=0, rare=0, markdown=0, markup=0, now=None,
                  reference=False, counter_ceiling=1999000000):
    """The native unit-chain boundary, with explicit listing context inputs.

    Missing owner/supply/investment facts must not be silently invented by a
    caller. A sheet reference uses neutral modifiers and is labelled as such.
    """
    from decimal import Decimal, ROUND_FLOOR
    import time
    D = lambda value: Decimal(str(value))
    unit = D(composed.get('precise_price', composed.get('price', 0)))
    unit *= D(max(0, extra))/100*D(max(0, spread))/100*D(max(100, 100+bonowacz))/100
    if habit > 0:
        unit = D(habit)
    if rare:
        unit = min(unit*D(rare)/100, unit*D(400)/100)
    else:
        unit *= D(max(0, 100-markdown) if markdown > 0 else 100+max(0, markup))/100
    before_cap = max(unit, D(floor))
    capped, reasons = before_cap, []
    if not reference and policy.get('plus9', 0):
        if c9 > 0:
            capped = min(capped, D(c9)*D(policy['plus9'])/100)
        else:
            reasons.append('price_missing_c9')
    clock = int(time.time()) if now is None else int(now)
    started = int(policy.get('started', 0))
    age = clock-started if started else -1
    if not reference and policy.get('young_days', 0) and policy.get('young_pct', 0) and 0 <= age < 86400*policy['young_days']:
        if policy.get('median', 0) > 0:
            capped = min(capped, D(policy['median'])*D(policy['young_pct'])/100)
        else:
            reasons.append('price_missing_cohort')
    conflict = capped < D(floor)
    if conflict:
        reasons.insert(0, 'price_floor_cap_conflict')
        capped = before_cap
    unit_yang = max(1, int((capped+D('0.5')).to_integral_value(rounding=ROUND_FLOOR)))
    total=unit_yang*max(1, int(count))
    if counter_ceiling > 0:
        total=min(total, int(counter_ceiling))
    return dict(price=total, unit=unit_yang,
                precise_price=str(capped), before_cap=str(before_cap), conflict=conflict,
                reasons=reasons or ['priced'])


def verified_c9(proto, vnum, plus, protos, rows, curve_pct, inflation):
    """Only the actual ten-step native proto/refine family supplies C9."""
    from decimal import Decimal
    base = int(vnum)-int(plus)
    current, seen, found = protos.get(base), set(), False
    mask = ITEM_ANTIFLAG_CLASSES | 3  # native FEMALE/MALE flags
    for step in range(10):
        if (current is None or current.vnum in seen or current.type != proto.type or
                current.subtype != proto.subtype or current.antiflag & mask != proto.antiflag & mask or current.plus != step):
            return 0
        seen.add(current.vnum)
        found |= current.vnum == int(vnum) and step == int(plus)
        if step != 9:
            current = protos.get(current.refined_vnum)
    if not found or not rows[9]:
        return 0
    return Decimal(rows[9])*Decimal(max(1, curve_pct))/100*Decimal(inflation)/INFLATION_ONE


def compose(f):
    """Compose: a dict of every step (playerbot_gear_price_rules::TPrice)."""
    out = {"priced": False, "ordinary_lines": 0, "low_row": 0, "base": None, "row": 0, "why": ROW_OWN,
           "sheet_row": 0, "sheet": 0, "level30_applied": False, "gear_base": 0, "floor": 0, "floor_row": 0,
           "average_applied": False, "average_price_sr": 0, "average_floor_wins": False, "after_average": 0,
           "product": 100, "at_top_lines": 0, "classic_pct": 0, "premium_pct": 0, "price": 0}
    if f.plus < 0 or f.plus >= SHEET_ROWS:
        return out
    if f.pricing_options.get('precise'):
        return _compose_precise(f, out)
    lines = f.lines
    out["ordinary_lines"] = ordinary_lines(lines)
    out["low_row"] = low_plus_lines_row(f.rows, f.plus, out["ordinary_lines"])
    catalogue = out["low_row"]
    out["why"] = ROW_LOW_PLUS_LINES if out["low_row"] != f.plus else ROW_OWN
    base = None
    if not f.weapon and f.base_slot != BASE_SLOT_NONE:
        plain = classic(lines, False, f.cap, f.pricing_options)
        base_lines = [(line.tier, line.value, line.top, line.base_pct) for line in lines]
        base = evaluate_bonus_base_at(f.rows, f.plus, out["low_row"], f.base_slot, base_lines, plain[2], f.cap)
        if base["wins"]:
            catalogue = base["row"]
            out["why"] = ROW_BONUS_BASE
    out["base"] = base
    row = f.plus if catalogue < f.plus else min(catalogue, SHEET_ROWS - 1)
    out["row"] = row
    if row == f.plus:
        out["why"] = ROW_OWN
    out["sheet_row"] = f.rows[row]
    if out["sheet_row"] <= 0:
        return out
    out["priced"] = True
    keep = f.level30_keep if row == f.plus else LEVEL30_CUT_PERMILLE_ONE
    out["sheet"] = level30_cut_price(out["sheet_row"], keep)
    out["level30_applied"] = out["sheet"] != out["sheet_row"]
    stones = f.stones_pct if f.stones_pct > 0 else 100
    out["gear_base"] = scale_sheet(saturate(tdiv(out["sheet"] * stones, 100)), f.curve_pct, f.inflation)
    out["after_average"] = out["gear_base"]
    if f.weapon:
        if row == f.plus:
            floor_row = average_floor_row(f.average)
            if average_floor_applies(f.plus, floor_row) and f.rows[floor_row] > 0:
                out["floor_row"] = floor_row
                out["floor"] = scale_sheet(saturate(tdiv(level30_cut_price(f.rows[floor_row], keep) * stones, 100)),
                                           f.curve_pct, f.inflation)
        if f.average_pct != AVERAGE_PCT_NONE or out["floor"] != 0:
            out["average_applied"] = True
            price_sr = tdiv(out["gear_base"] * (f.average_pct if f.average_pct > 0 else AVERAGE_PCT_NONE), 100)
            floor = out["floor"] if out["floor"] > 0 else 0
            out["average_price_sr"] = price_sr
            out["average_floor_wins"] = floor > price_sr
            sr = saturate(floor if floor > price_sr else price_sr)
            out["after_average"] = sr if sr > 1 else 1
    out["product"], out["at_top_lines"], out["classic_pct"] = classic(lines, f.weapon, f.cap, f.pricing_options)
    out["premium_pct"] = out["classic_pct"]
    if base and base["wins"] and row == base["row"]:
        out["premium_pct"] = max(-2147483647, min(2147483647, overrides.soft_cap(base["zero_point_pct"], f.pricing_options) - 100))
    out["price"] = apply_premium(out["after_average"], out["premium_pct"])
    out["price"] = overrides.final_cap(out["price"], scale_sheet(f.rows[9], f.curve_pct, f.inflation), f.pricing_options)
    return out


# ---------------------------------------------------------------- an offer
def family_rows(vnum, plus, protos=None):
    """His sheet's ten rows of a piece's family (vnum less its plus), a
    helmet's made from the body armour of its level and classes where his
    sheet carries no row for it (playerbot_gear_sheet.h,
    GetPlayerBotHelmetPriceRow); None when neither."""
    base = int(vnum) - int(plus)
    row = sheet.GEAR.get(base)
    if row:
        return tuple(row[1])
    if not protos:
        return None
    helmet = protos.get(base)
    if helmet is None or int(helmet.type) != ITEM_ARMOR or int(helmet.subtype) != ARMOR_HEAD:
        return None
    level, classes = int(helmet.level or 0), int(helmet.antiflag or 0) & ITEM_ANTIFLAG_CLASSES
    best = None
    for family in sorted(sheet.GEAR):
        proto = protos.get(family)
        if proto is None or int(proto.type) != ITEM_ARMOR or int(proto.subtype) != ARMOR_BODY:
            continue
        if int(proto.antiflag or 0) & ITEM_ANTIFLAG_CLASSES != classes or int(proto.level or 0) > level:
            continue
        if best is None or int(proto.level or 0) > int(protos[best].level or 0):
            best = family
    if best is None:
        return None
    return tuple(tdiv(p * HELMET_SHEET_PERCENT, 100) if p > 0 else 0 for p in sheet.GEAR[best][1])


def price_slot(itype, subtype):
    if int(itype) == ITEM_WEAPON:
        return PRICE_SLOT_WEAPON
    if int(itype) == ITEM_ARMOR:
        return ARMOR_PRICE_SLOT.get(int(subtype), 0)
    return 0


def base_slot(itype, subtype):
    if int(itype) != ITEM_ARMOR:
        return BASE_SLOT_NONE
    subtype = int(subtype)
    if subtype in (ARMOR_NECK, ARMOR_WRIST, ARMOR_FOOTS, ARMOR_EAR):
        return BASE_SLOT_JEWEL
    if subtype in (ARMOR_BODY, ARMOR_SHIELD, ARMOR_HEAD):
        return BASE_SLOT_ARMOUR
    return BASE_SLOT_NONE


def attribute_set(itype, subtype):
    if int(itype) == ITEM_WEAPON:
        return -1 if int(subtype) in (WEAPON_ARROW, WEAPON_QUIVER) else 0
    if int(itype) == ITEM_ARMOR:
        return ARMOR_ATTRIBUTE_SET.get(int(subtype), -1)
    return -1


def table_max(attr_sets, point, aset):
    """GetPlayerBotBonusMaxRoll: the line's top on the piece's attribute set
    of world.item_attr - its level for the set, 5 where the set has none -
    0 where the table has no such line. `attr_sets` {point: ((lv1..lv5),
    (weapon, body, wrist, foots, neck, head, shield, ear))}."""
    row = attr_sets.get(int(point)) if attr_sets else None
    if not row:
        return 0
    values, levels = row
    level = int(levels[aset]) if 0 <= aset < len(levels) else 0
    if level <= 0 or level > ATTRIBUTE_MAX_LEVEL:
        level = ATTRIBUTE_MAX_LEVEL
    return int(values[level - 1])


def market_tier(point):
    """GetPlayerBotMarketBonusTier: the higher of his PvE and PvP mark, no
    class's +1."""
    row = sheet.BONUS_TIERS.get(int(point))
    if not row:
        return 0
    return max(min(int(row[0]), 6) if int(row[0]) > 0 else 0, min(int(row[1]), 6) if int(row[1]) > 0 else 0)


def stones_percent(sockets):
    """GetPlayerBotSocketStonePercent."""
    seated, percent = 0, 100
    for socket in sockets:
        socket = int(socket or 0)
        if socket <= 2 or socket == sheet.BROKEN_SOUL_STONE:
            continue
        seated += 1
        kind, grade = socket % 100, (socket // 100) % 10
        mult = sheet.SOCKET_STONE_PERCENT.get((kind, grade))
        if mult:
            percent = tdiv(percent * mult, 100)
    if seated <= 0:
        return 100
    return tdiv(percent * sheet.SOCKET_COUNT_PERCENT[min(seated, 3)], 100)


def attribute_count(attrs):
    """CItem::GetAttributeCount: the leading lines of the five with a type."""
    n = 0
    for point, _value in list(attrs)[:MAX_LINES]:
        if not int(point or 0):
            break
        n += 1
    return n


def offer_lines(proto, attrs, attr_sets):
    """The piece's five ordinary lines as the price reads them."""
    itype, subtype, level = int(proto.type), int(proto.subtype), int(proto.level or 0)
    slot, aset = price_slot(itype, subtype), attribute_set(itype, subtype)
    out = []
    attrs = list(attrs)
    for point, value in attrs[:attribute_count(attrs)]:
        point, value = int(point or 0), int(value or 0)
        top = table_max(attr_sets, point, aset)
        pct, at_top = 100, False
        if slot:
            if slot == PRICE_SLOT_WEAPON and point == POINT_NORMAL_HIT_DAMAGE:
                at_top = value >= AVERAGE_DAMAGE_MAX_FROM if value > 0 else False
                pct = damage_tier_pct(sheet.AVERAGE_TIERS, value) if value > 0 else 100
            elif slot == PRICE_SLOT_WEAPON and point == POINT_SKILL_DAMAGE:
                at_top = value >= sheet.SKILL_TIERS[-1][0] if value > 0 else False
                pct = damage_tier_pct(sheet.SKILL_TIERS, value) if value > 0 else 100
            else:
                found = find_line_rows(rows_of_point(point), point, slot, level)
                if point == POINT_IQ:
                    apply_int_row(found, INT_SLOT_SHIELD if slot == PRICE_SLOT_SHIELD else
                                  (INT_SLOT_SHAMAN_WEAPON if slot == PRICE_SLOT_WEAPON and
                                   subtype in (WEAPON_BELL, WEAPON_FAN) else INT_SLOT_OTHER))
                pct, at_top = line_pct(found, point, value, top, point == POINT_MAX_HP)
        tier, bvalue, btop, bpct = base_line_for(point == POINT_MAX_HP, market_tier(point), value, top, pct)
        out.append(Line(pct, at_top, slot == PRICE_SLOT_WEAPON and point == POINT_NORMAL_HIT_DAMAGE,
                        point != 0 and value > 0 and point not in (POINT_NORMAL_HIT_DAMAGE, POINT_SKILL_DAMAGE),
                        tier, bvalue, btop, bpct, point))
    return out


@overrides.synchronized
def offer_facts(proto, vnum, plus, attrs, sockets, attr_sets, yang_pct, index_milli, level30_keep=None,
                protos=None):
    """The Facts of an offer of a family his sheet prices, or None."""
    if proto is None or int(proto.type) not in (ITEM_WEAPON, ITEM_ARMOR) or plus is None or not 0 <= int(plus) <= 9:
        return None
    rows = family_rows(vnum, plus, protos)
    if rows is None:
        return None
    lines = offer_lines(proto, attrs, attr_sets)
    weapon = int(proto.type) == ITEM_WEAPON
    average_pct = AVERAGE_PCT_NONE
    for line in lines:
        if line.average:
            average_pct = line.pct
            break
    average = 0
    for point, value in attrs:
        if int(point or 0) == POINT_NORMAL_HIT_DAMAGE:
            average = int(value or 0)
            break
    return Facts(rows, int(plus), weapon, BASE_SLOT_NONE if weapon else base_slot(proto.type, proto.subtype),
                 lines, stones_percent(sockets), int(yang_pct), inflation_of(index_milli), average_pct, average,
                 LEVEL30_CUT_PERMILLE_ONE if level30_keep is None else int(level30_keep))
