# =============================================================================
#  /editsql -- etykiety (nazwy typow, rang, bonusow).
#
#  Zasada z raportu: zadnej wiedzy o grze wpisanej na sztywno. Dlatego:
#
#   * BONUSY czyta sie z bazy. world.locale_point to gotowa tablica
#     numer POINT -> nazwa (POINT_ST) -> polska etykieta ("Sila: +{}").
#     Nic tu nie trzeba zgadywac - to jest w bazie tego serwera.
#
#   * TYPY PRZEDMIOTOW i RANGI POTWOROW nie maja nigdzie nazw (kolumna to
#     tinyint, a enum zyje w naglowku silnika, ktorego w projekcie nie ma).
#     Wymyslanie ich bylo by dokladnie tym, czego nie wolno: "typ 28 = kostium"
#     wyglada jak fakt, a jest zgadywaniem. Zamiast tego edytor:
#       - pokazuje SUROWY numer zawsze,
#       - dokleja PRZYKLADY I STATYSTYKI WYLICZONE Z DANYCH tej bazy
#         ("2 · np. Zbroja Nahan+5, Zbroja Tanma+5 · 1514 szt."),
#       - a operator moze nadac wlasna nazwe w player.editsql_labels.
#     Nazwa nadana przez operatora wygrywa; pusta oznacza "nienazwane".
#
#  Wszystko jest cache'owane: locale_point ma 90 wierszy, a podpowiedzi
#  wymagaja dwoch zapytan grupujacych na tabele.
# =============================================================================

import threading
import time

from . import db, i18n, schema
from .i18n import P, T, tr

TTL = 600.0
_lock = threading.RLock()
_cache = {}

LABELS_DDL = """
CREATE TABLE IF NOT EXISTS `player`.`editsql_labels` (
  `kind`  VARCHAR(24) NOT NULL,
  `key`   VARCHAR(64) NOT NULL,
  `label` VARCHAR(96) NOT NULL DEFAULT '',
  `note`  VARCHAR(255) NOT NULL DEFAULT '',
  `updated` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`kind`,`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

KIND_ITEM_TYPE = "item_type"
KIND_MOB_RANK = "mob_rank"
KIND_MOB_TYPE = "mob_type"
KIND_EVENT = "event_kind"

_SEEDED = {"done": False}


# -----------------------------------------------------------------------------
#  Tabela etykiet
# -----------------------------------------------------------------------------
def ensure_table():
    if not _SEEDED["done"]:
        try:
            db.ddl(LABELS_DDL)
        except Exception:                          # noqa: BLE001 - brak praw = praca bez nadpisan
            pass
        _SEEDED["done"] = True


def _fetch(kind):
    with _lock:
        hit = _cache.get(kind)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    rows = {}
    try:
        ensure_table()
        for row in db.query(
                "SELECT `key` AS k, label, note FROM `player`.`editsql_labels` WHERE kind=%s",
                (kind,)):
            rows[db.decode(row["k"])] = {"label": db.decode(row["label"]) or "",
                                         "note": db.decode(row["note"]) or ""}
    except Exception:                              # noqa: BLE001
        rows = {}
    with _lock:
        _cache[kind] = (time.time(), rows)
    return rows


def save(kind, key, label, note=""):
    ensure_table()
    db.ddl("INSERT INTO `player`.`editsql_labels` (kind, `key`, label, note) "
           "VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE label=VALUES(label), "
           "note=VALUES(note)",
           (kind, str(key)[:64], (label or "")[:96], (note or "")[:255]))
    with _lock:
        _cache.pop(kind, None)


def invalidate():
    with _lock:
        _cache.clear()


def label(kind, key):
    """Nazwa nadana przez operatora albo '' (wtedy UI pokazuje sam numer)."""
    entry = _fetch(kind).get(str(key))
    return entry["label"] if entry else ""


def note(kind, key):
    entry = _fetch(kind).get(str(key))
    return entry["note"] if entry else ""


def describe(kind, key, extra=None):
    """(label, hint) gotowe do pokazania: nazwa operatora + podpowiedz z danych."""
    name = label(kind, key)
    hint = note(kind, key)
    if extra:
        hint = (hint + " · " + extra) if hint else extra
    return name, hint


# -----------------------------------------------------------------------------
#  Bonusy -- w calosci z bazy (world.locale_point)
# -----------------------------------------------------------------------------
def point_labels():
    """{numer POINT: {'name': 'POINT_ST', 'pl': 'Sila: +{}'}} oraz po nazwie."""
    with _lock:
        hit = _cache.get("points")
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    by_number, by_name = {}, {}
    try:
        table = schema.table("world", "locale_point")
        if table is None:
            raise RuntimeError("brak world.locale_point")
        columns = [name for name in ("point", "point_name", "point_locale")
                   if name in table["by_name"]]
        rows = db.query("SELECT %s FROM %s"
                        % (", ".join(db.qi(name) for name in columns),
                           db.qt(table["db"], table["name"])))
        for row in rows:
            entry = {"point": int(row.get("point") or 0),
                     "name": db.decode(row.get("point_name"), "latin1") or "",
                     "pl": db.decode(row.get("point_locale"), "utf8") or ""}
            by_number[entry["point"]] = entry
            if entry["name"]:
                by_name[entry["name"]] = entry
    except Exception:                              # noqa: BLE001
        pass
    result = {"by_number": by_number, "by_name": by_name}
    with _lock:
        _cache["points"] = (time.time(), result)
    return result


def point_by_number(number):
    return point_labels()["by_number"].get(int(number or 0))


def point_by_name(name):
    return point_labels()["by_name"].get(str(name or "").strip())


def bonus_label(value):
    """Etykieta bonusu dla NUMERU (item_proto.applytypeN) albo NAZWY (item_attr.apply).

    Najpierw probujemy po nazwie (item_attr uzywa nazw POINT_*), potem po numerze.
    Zwracamy (nazwa, polska etykieta, sposob) - sposob mowi, skad etykieta przyszla,
    zeby UI moglo byc uczciwe, gdy jej nie ma.
    """
    text = str(value or "").strip()
    if not text:
        return "", "", ""
    if text.isdigit():
        entry = point_by_number(int(text))
        if entry:
            return entry["name"], entry["pl"], "locale_point"
        return "", "", ""
    entry = point_by_name(text)
    if entry:
        return entry["name"], entry["pl"], "locale_point"
    return text, "", ""


# -----------------------------------------------------------------------------
#  Typy przedmiotow i rangi potworow -- podpowiedzi z DANYCH
# -----------------------------------------------------------------------------
def _item_table():
    return schema.table("world", "item_proto") or schema.table("player", "item_proto")


def _vnum_col(table):
    """`vnum` AS v, for the example's official English name, when the table has it."""
    return "`vnum` AS v, " if "vnum" in table["by_name"] else ""


def _put_examples(info, kind, rows, name_col, charset):
    """A hint's examples: the stored names (what seed_from_data writes into
    the labels' notes, Polish as the table holds them) and beside each the
    official English one, or None (i18n.english_name, from the stored bytes)."""
    info["examples"] = [db.decode(r["n"], charset) or "" for r in rows]
    info["examples_en"] = [i18n.english_name(kind, r.get("v"), name)
                           if name_col == "locale_name" and r.get("v") is not None else None
                           for r, name in zip(rows, info["examples"])]


def item_type_hints(limit=3, refresh=False):
    """{typ: {'count': n, 'examples': [nazwa, ...]}} - wyliczone z item_proto."""
    key = "item_types"
    with _lock:
        hit = _cache.get(key)
        if hit and not refresh and time.time() - hit[0] < TTL:
            return hit[1]
    table = _item_table()
    out = {}
    if table is not None:
        try:
            name_col = "locale_name" if "locale_name" in table["by_name"] else "name"
            for row in db.query(
                    "SELECT type, COUNT(*) AS n FROM %s GROUP BY type ORDER BY type"
                    % db.qt(table["db"], table["name"])):
                out[int(row["type"] or 0)] = {"count": int(row["n"] or 0), "examples": []}
            for type_value in out:
                rows = db.query(
                    "SELECT %s%s AS n FROM %s WHERE type=%%s "
                    "AND %s <> '' LIMIT %%s" % (_vnum_col(table), db.qi(name_col),
                                                db.qt(table["db"], table["name"]), db.qi(name_col)),
                    (type_value, limit))
                _put_examples(out[type_value], "item", rows, name_col, table["by_name"][name_col]["charset"])
        except Exception:                          # noqa: BLE001
            out = {}
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def mob_rank_hints(refresh=False):
    """{ranga: {'count': n, 'median_hp': x, 'examples': [...]}} z mob_proto."""
    key = "mob_ranks"
    with _lock:
        hit = _cache.get(key)
        if hit and not refresh and time.time() - hit[0] < TTL:
            return hit[1]
    table = schema.table("world", "mob_proto") or schema.table("player", "mob_proto")
    out = {}
    if table is not None:
        cols = table["by_name"]
        name_col = "locale_name" if "locale_name" in cols else "name"
        hp = "max_hp" if "max_hp" in cols else None
        try:
            sql = "SELECT `rank`, COUNT(*) AS n"
            if hp:
                sql += ", CAST(AVG(%s) AS UNSIGNED) AS hp" % db.qi(hp)
            sql += " FROM %s GROUP BY `rank` ORDER BY `rank`" % db.qt(table["db"], table["name"])
            for row in db.query(sql):
                out[int(row["rank"] or 0)] = {"count": int(row["n"] or 0),
                                              "avg_hp": int(row.get("hp") or 0),
                                              "examples": []}
            for rank in out:
                rows = db.query(
                    "SELECT %s%s AS n FROM %s WHERE `rank`=%%s LIMIT 3"
                    % (_vnum_col(table), db.qi(name_col), db.qt(table["db"], table["name"])), (rank,))
                _put_examples(out[rank], "mob", rows, name_col, cols[name_col]["charset"])
        except Exception:                          # noqa: BLE001
            out = {}
    with _lock:
        _cache[key] = (time.time(), out)
    return out


# -----------------------------------------------------------------------------
#  Nazwy domyslne -- wartosci enumow silnika Metin2 (item_length.h, length.h).
#  Kazda zostala sprawdzona na danych TEJ bazy (przyklady wierszy obok liczby):
#  typ 1 to same bronie, 20 to szkatulki, 28 kostiumy, ranga 4 to Wodz Orkow
#  i Krol Demonow, typ potwora 2 to Metiny. Operator moze kazda nadpisac na
#  stronie Etykiety; typy, ktorych silnik nie zna (35, 36), zostaja numerem.
# -----------------------------------------------------------------------------
DEFAULT_ITEM_TYPES = {
    0: P("Brak typu", "No type"), 1: P("Broń", "Weapon"), 2: P("Pancerz i biżuteria", "Armour and jewellery"),
    3: P("Użytkowy", "Usable"), 4: P("Auto-użycie", "Auto-use"),
    5: P("Materiał", "Material"), 6: P("Specjalny", "Special"), 7: P("Narzędzie", "Tool"),
    8: P("Loteria", "Lottery"), 9: "Yang",
    10: P("Kamień duszy", "Soul stone"), 11: P("Pojemnik", "Container"), 12: P("Ryba", "Fish"),
    13: P("Wędka", "Fishing rod"), 14: P("Surowiec", "Resource"),
    15: P("Ognisko", "Campfire"), 16: P("Unikalny", "Unique"),
    17: P("Księga umiejętności", "Skill book"), 18: P("Przedmiot misji", "Quest item"),
    19: P("Polimorfia", "Polymorph"), 20: P("Skrzynia skarbu", "Treasure chest"),
    21: P("Klucz do skrzyni", "Chest key"),
    22: P("Księga zapomnienia", "Forgetting book"), 23: P("Skrzynka-prezent", "Gift box"),
    24: P("Kilof", "Pickaxe"), 25: P("Fryzura", "Hairstyle"),
    26: P("Totem", "Totem"), 27: P("Mieszanka", "Blend"), 28: P("Kostium", "Costume"),
    29: P("Smoczy kamień", "Dragon stone"),
    30: P("Specjalny smoczy kamień", "Special dragon stone"), 31: P("Ekstraktor", "Extractor"),
    32: P("Druga waluta", "Second currency"),
    33: P("Pierścień", "Ring"), 34: P("Pas", "Belt"),
}
DEFAULT_ITEM_SUBTYPES = {
    1: {0: P("Miecz", "Sword"), 1: P("Sztylet", "Dagger"), 2: P("Łuk", "Bow"),
        3: P("Broń dwuręczna", "Two-handed weapon"), 4: P("Dzwon", "Bell"),
        5: P("Wachlarz", "Fan"), 6: P("Strzała", "Arrow"), 7: P("Lanca", "Lance")},
    2: {0: P("Zbroja", "Armour"), 1: P("Hełm", "Helmet"), 2: P("Tarcza", "Shield"),
        3: P("Bransoleta", "Bracelet"), 4: P("Buty", "Shoes"),
        5: P("Naszyjnik", "Necklace"), 6: P("Kolczyki", "Earrings")},
    28: {0: P("Strój", "Outfit"), 1: P("Fryzura", "Hairstyle")},
}
DEFAULT_MOB_RANKS = {0: P("Zwykły", "Ordinary"), 1: P("Silny", "Strong"), 2: P("Elitarny", "Elite"),
                     3: P("Silny elitarny", "Strong elite"),
                     4: "Boss", 5: P("Król", "King")}
DEFAULT_MOB_TYPES = {0: P("Potwór", "Monster"), 1: "NPC", 2: P("Kamień Metin", "Metin stone"),
                     3: "Portal", 4: P("Brama", "Gate"),
                     5: P("Budynek", "Building"), 6: P("Postać gracza", "Player character"),
                     7: P("Polimorfia", "Polymorph"), 8: P("Koń", "Horse"),
                     9: P("Punkt teleportu", "Teleport point")}
EMPIRES = {0: P("Wszystkie / brak", "All / none"), 1: P("Shinsoo (czerwone)", "Shinsoo (red)"),
           2: P("Chunjo (żółte)", "Chunjo (yellow)"),
           3: P("Jinno (niebieskie)", "Jinno (blue)")}

SKILL_GROUPS = {0: P("Wspólne / pasywne", "Shared / passive"), 1: P("Wojownik", "Warrior"),
                2: "Ninja", 3: "Sura", 4: P("Szaman", "Shaman"),
                5: P("Jazda konna", "Riding")}

KIND_DEFAULTS = {KIND_ITEM_TYPE: DEFAULT_ITEM_TYPES, KIND_MOB_RANK: DEFAULT_MOB_RANKS,
                 KIND_MOB_TYPE: DEFAULT_MOB_TYPES}


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def default_label(kind, key):
    number = _int_or_none(key)
    return tr(KIND_DEFAULTS.get(kind, {}).get(number, "")) if number is not None else ""


def name_of(kind, key):
    """Nazwa do pokazania: nadana przez operatora, inaczej domyslna, inaczej ''."""
    return label(kind, key) or default_label(kind, key)


def _with_number(kind, value):
    name = name_of(kind, value)
    return name if name else (T("typ %s", "type %s") % value if kind != KIND_MOB_RANK
                              else T("ranga %s", "rank %s") % value)


def shown_examples(hints, count):
    """A hint's example names as this reader reads them: the official English
    name where the example has one (hints["examples_en"], worked out when the
    examples were read), for every reader but a Polish one."""
    names = list(hints.get("examples") or [])[:count]
    if i18n.lang() != "pl":
        english = list(hints.get("examples_en") or [])
        names = [(english[i] if i < len(english) and english[i] else name) for i, name in enumerate(names)]
    return [x for x in names if x]


def _examples(hints):
    return T("np. ", "e.g. ") + ", ".join(shown_examples(hints, 2))


def item_type_text(type_value):
    """(tekst, podpowiedz) dla typu przedmiotu: "Broń" + "1 · 1397 szt. · np. ...". """
    hints = item_type_hints().get(_int_or_none(type_value) or 0) or {}
    bits = [T("typ %s", "type %s") % type_value]
    if hints.get("count"):
        bits.append(T("%d szt.", "%d pcs") % hints["count"])
    if hints.get("examples"):
        bits.append(_examples(hints))
    return _with_number(KIND_ITEM_TYPE, type_value), " · ".join(bits)


def item_subtype_text(type_value, subtype_value):
    names = DEFAULT_ITEM_SUBTYPES.get(_int_or_none(type_value), {})
    name = tr(names.get(_int_or_none(subtype_value)))
    return name or str(subtype_value if subtype_value is not None else "")


def mob_rank_text(rank_value):
    hints = mob_rank_hints().get(_int_or_none(rank_value) or 0) or {}
    bits = [T("ranga %s", "rank %s") % rank_value]
    if hints.get("count"):
        bits.append(i18n.T("%d potworów", "%d monsters") % hints["count"])
    if hints.get("avg_hp"):
        bits.append(T("śr. PŻ %d", "avg. HP %d") % hints["avg_hp"])
    if hints.get("examples"):
        bits.append(_examples(hints))
    return _with_number(KIND_MOB_RANK, rank_value), " · ".join(bits)


def mob_type_text(type_value):
    return _with_number(KIND_MOB_TYPE, type_value), T("typ %s", "type %s") % type_value


def empire_text(value):
    number = _int_or_none(value)
    return tr(EMPIRES.get(number, str(value))), T("królestwo %s", "kingdom %s") % value


def bonus_text(value):
    """Czytelna nazwa bonusu: "Maks. PŻ" zamiast "Maks. PŻ: +{}" albo POINT_MAX_HP.

    world.locale_point has the bonus names in Polish only, so an English reader
    gets the technical name of the same row, made readable ("Max hp"), rather
    than the Polish label; the code stays beside it as before.
    """
    name, pl, _src = bonus_label(value)
    if pl and i18n.lang() != "pl" and name:
        pl = ""
    if pl:
        import re
        text = re.sub(r"[:\s]*[+\-]?\s*\{\}\s*%?\s*$", "", pl)   # "...: +{}%" na koncu
        text = text.replace("{}", "X")                               # "{}% obrazen..." w srodku
        text = re.sub(r"\s+", " ", text).strip(" :+-")
        return text.strip() or name, name
    if name:
        pretty = name[6:] if name.startswith("POINT_") else name
        return pretty.replace("_", " ").capitalize(), name
    return str(value or ""), ""


def mob_type_hints(refresh=False):
    """{typ: {'count': n, 'examples': [...]}} z mob_proto."""
    key = "mob_types"
    with _lock:
        hit = _cache.get(key)
        if hit and not refresh and time.time() - hit[0] < TTL:
            return hit[1]
    table = schema.table("world", "mob_proto") or schema.table("player", "mob_proto")
    out = {}
    if table is not None and "type" in table["by_name"]:
        cols = table["by_name"]
        name_col = "locale_name" if "locale_name" in cols else "name"
        try:
            for row in db.query("SELECT `type` AS t, COUNT(*) AS n FROM %s GROUP BY `type` "
                                "ORDER BY `type`" % db.qt(table["db"], table["name"])):
                out[int(row["t"] or 0)] = {"count": int(row["n"] or 0), "examples": []}
            for type_value in out:
                rows = db.query("SELECT %s%s AS n FROM %s WHERE `type`=%%s LIMIT 3"
                                % (_vnum_col(table), db.qi(name_col), db.qt(table["db"], table["name"])),
                                (type_value,))
                _put_examples(out[type_value], "mob", rows, name_col, cols[name_col]["charset"])
        except Exception:                          # noqa: BLE001
            out = {}
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def seed_from_data():
    """Wypelnia UWAGI (nie nazwy) przykladami z tej bazy - raz.

    Nazw nie wymyslamy: zostaja puste, dopoki operator ich nie nada. Ale zeby
    mial od czego zaczac, przy kazdym typie/randze zapisujemy, co to realnie
    jest w TEJ bazie (przyklady i liczebnosc).
    """
    ensure_table()
    marker = _fetch("seeded").get("v1")
    if marker:
        return False
    for type_value, hint in item_type_hints().items():
        bits = []
        if hint.get("count"):
            bits.append("%d przedmiotow" % hint["count"])
        if hint.get("examples"):
            bits.append("np. " + ", ".join(x for x in hint["examples"][:3] if x))
        if bits:
            save(KIND_ITEM_TYPE, type_value, label(KIND_ITEM_TYPE, type_value),
                 " · ".join(bits))
    for rank, hint in mob_rank_hints().items():
        bits = []
        if hint.get("count"):
            bits.append("%d mobow" % hint["count"])
        if hint.get("avg_hp"):
            bits.append("sr. HP %d" % hint["avg_hp"])
        if hint.get("examples"):
            bits.append("np. " + ", ".join(x for x in hint["examples"][:3] if x))
        if bits:
            save(KIND_MOB_RANK, rank, label(KIND_MOB_RANK, rank), " · ".join(bits))
    save("seeded", "v1", "1", "podpowiedzi wyliczone z danych tej bazy")
    return True
