# =============================================================================
#  /editsql -- metamodel bazy (ETAP 6).
#
#  Czyta information_schema RAZ na cala baze (6 zapytan, nie SHOW CREATE TABLE
#  per tabela - na tym serwerze byloby to 173 rund) i buduje model, na ktorym
#  stoi caly edytor:
#
#      baza -> tabela -> kolumna (+ typ, NULL, default, auto_increment)
#                     -> klucz glowny / UNIQUE / indeksy
#                     -> szacowana liczba wierszy, silnik, kolacja, komentarz
#
#  Trzy fakty o TYM serwerze, ktore ten kod respektuje (wszystkie potwierdzone
#  na dumpie information_schema):
#
#   * NIE MA ANI JEDNEGO klucza obcego (REFERENTIAL_CONSTRAINTS = 0 wierszy,
#     a 247 wierszy KEY_COLUMN_USAGE nie ma REFERENCED_TABLE_NAME). Relacji nie
#     da sie wiec odkryc - mapa relacji musi byc czescia edytora i jest nizej,
#     w RELATIONS, z podanym pokryciem zmierzonym na danych.
#   * Klucze budujemy z TABLE_CONSTRAINTS + KEY_COLUMN_USAGE, bo COLUMNS.COLUMN_KEY
#     nie mowi nic o KOLEJNOSCI kolumn w kluczu zlozonym (player.quest ma
#     (dwPID, szName, szState) - kolejnosc ma znaczenie przy WHERE i przy REPLACE).
#   * Kodowanie jest per KOLUMNA (world.locale_point ma w jednej tabeli trzy),
#     wiec model trzyma charset i collation kazdej kolumny osobno.
#
#  Model jest cache'owany (SCHEMA_TTL) i budowany pod zamkiem: jedno zadanie
#  buduje, reszta czeka, zeby rownolegle zadania nie zrobily 6 zapytan kazde.
# =============================================================================

import re
import threading
import time

from . import db
from .i18n import P, T, bilingual

MODEL ={"ts": 0.0, "dbs": {}, "tables": {}, "loaded": False}
_lock = threading.RLock()

SYSTEM_DBS = ("information_schema", "performance_schema", "mysql", "sys", "hotbackup")

# Bazy, ktore edytor pokazuje jako "gry". hotbackup bywa pusty i nie jest
# czescia swiata, wiec idzie do listy tylko wtedy, gdy ma tabele.
GAME_DBS = ("world", "player", "common", "account", "log", "itemshop")


# -----------------------------------------------------------------------------
#  Pomocnicze: parsowanie COLUMN_TYPE
# -----------------------------------------------------------------------------
_ENUM_RE = re.compile(r"^(enum|set)\((.*)\)$", re.I | re.S)
_QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")


def parse_choices(column_type):
    """['POINT_MAX_HP', ...] dla ENUM/SET, inaczej None.

    Wartosci moga zawierac przecinki i apostrofy (MySQL je escapuje), wiec nie
    dzielimy po przecinku - wyciagamy kolejne literaly w apostrofach.
    """
    m = _ENUM_RE.match((column_type or "").strip())
    if not m:
        return None
    return [v.replace("\\'", "'").replace("\\\\", "\\") for v in _QUOTED.findall(m.group(2))]


def parse_numeric_range(column_type):
    """(min, max) dla typow calkowitych, inaczej None. Z COLUMN_TYPE + UNSIGNED."""
    t = (column_type or "").lower()
    unsigned = "unsigned" in t
    m = re.match(r"^(tinyint|smallint|mediumint|int|bigint|decimal|float|double)", t)
    if not m:
        return None
    kind = m.group(1)
    bits = {"tinyint": 8, "smallint": 16, "mediumint": 24, "int": 32, "bigint": 64}.get(kind)
    if bits is None:                               # float/double/decimal: bez zakresu
        return None
    if unsigned:
        return 0, (1 << bits) - 1
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def parse_length(column_type):
    m = re.match(r"^(?:var)?char\((\d+)\)", (column_type or "").lower())
    if m:
        return int(m.group(1))
    if (column_type or "").lower().startswith("text"):
        return None
    return None


def normalise_default(value, data_type):
    """information_schema zwraca defaulty tekstowe W APOSTROFACH ('Noname')."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if data_type in ("char", "varchar", "text", "tinytext", "mediumtext", "longtext",
                     "enum", "set", "binary", "varbinary", "blob"):
        if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            return value[1:-1].replace("''", "'")
    return value


# -----------------------------------------------------------------------------
#  Budowa modelu
# -----------------------------------------------------------------------------
def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def load(force=False):
    """Model bazy. Cache SCHEMA_TTL; force=True wymusza odswiezenie."""
    with _lock:
        if not force and MODEL["loaded"] and time.time() - MODEL["ts"] < db.SCHEMA_TTL:
            return MODEL
        try:
            _build()
            MODEL["loaded"] = True
        except Exception as exc:                   # noqa: BLE001
            MODEL["error"] = str(exc)
            if not MODEL["loaded"]:
                raise
        return MODEL


def reload_model():
    return load(force=True)


def _build():
    dbs = {}
    for row in db.query(
            "SELECT SCHEMA_NAME AS name, DEFAULT_CHARACTER_SET_NAME AS cs, "
            "DEFAULT_COLLATION_NAME AS coll "
            "FROM information_schema.SCHEMATA"):
        name = db.decode(row["name"])
        if name in SYSTEM_DBS:
            continue
        dbs[name] = {"name": name, "charset": db.decode(row["cs"]),
                     "collation": db.decode(row["coll"])}

    names = sorted(dbs)
    if not names:
        raise RuntimeError(T("nie widze zadnej bazy gry", "no game database is visible"))
    marks = ",".join(["%s"] * len(names))

    tables = {}
    for row in db.query(
            "SELECT TABLE_SCHEMA AS db, TABLE_NAME AS t, TABLE_TYPE AS tt, ENGINE AS eng, "
            "ROW_FORMAT AS rf, TABLE_ROWS AS rows_est, AVG_ROW_LENGTH AS avglen, "
            "DATA_LENGTH AS dlen, INDEX_LENGTH AS ilen, AUTO_INCREMENT AS autoinc, "
            "TABLE_COLLATION AS coll, TABLE_COMMENT AS comment "
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA IN (" + marks + ") "
            "ORDER BY TABLE_SCHEMA, TABLE_NAME", tuple(names)):
        key = (db.decode(row["db"]), db.decode(row["t"]))
        tables[key] = {
            "db": key[0], "name": key[1],
            "type": db.decode(row["tt"]) or "BASE TABLE",
            "engine": db.decode(row["eng"]) or "",
            "row_format": db.decode(row["rf"]) or "",
            "rows_estimate": _int(row["rows_est"]),
            "avg_row_length": _int(row["avglen"]),
            "data_length": _int(row["dlen"]),
            "index_length": _int(row["ilen"]),
            "auto_increment": _int(row["autoinc"]),
            "collation": db.decode(row["coll"]) or "",
            "comment": db.decode(row["comment"]) or "",
            "columns": [], "by_name": {}, "pk": (), "unique": [], "indexes": [],
        }

    if tables:
        for row in db.query(
                "SELECT TABLE_SCHEMA AS db, TABLE_NAME AS t, ORDINAL_POSITION AS pos, "
                "COLUMN_NAME AS c, COLUMN_TYPE AS ctype, DATA_TYPE AS dtype, "
                "IS_NULLABLE AS nullable, COLUMN_DEFAULT AS cdefault, COLUMN_KEY AS ckey, "
                "EXTRA AS extra, CHARACTER_SET_NAME AS cs, COLLATION_NAME AS coll, "
                "CHARACTER_MAXIMUM_LENGTH AS maxlen, NUMERIC_PRECISION AS prec, "
                "NUMERIC_SCALE AS scale, COLUMN_COMMENT AS comment "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA IN (" + marks + ") "
                "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION", tuple(names)):
            key = (db.decode(row["db"]), db.decode(row["t"]))
            table = tables.get(key)
            if table is None:
                continue
            ctype = db.decode(row["ctype"]) or ""
            dtype = db.decode(row["dtype"]) or ""
            col = {
                "name": db.decode(row["c"]),
                "pos": _int(row["pos"]),
                "type": ctype,
                "data_type": dtype,
                "nullable": (db.decode(row["nullable"]) == "YES"),
                "default": normalise_default(db.decode(row["cdefault"]), dtype),
                "key": db.decode(row["ckey"]) or "",
                "extra": db.decode(row["extra"]) or "",
                "charset": db.decode(row["cs"]),
                "collation": db.decode(row["coll"]),
                "maxlen": row["maxlen"],
                "precision": row["prec"],
                "scale": row["scale"],
                "comment": db.decode(row["comment"]) or "",
                "choices": parse_choices(ctype),
                "range": parse_numeric_range(ctype),
                "length": parse_length(ctype),
            }
            col["auto"] = "auto_increment" in col["extra"]
            col["set"] = bool(col["choices"]) and ctype.lower().startswith("set")
            col["enum"] = bool(col["choices"]) and ctype.lower().startswith("enum")
            col["is_text"] = db.is_text_column(col)
            table["columns"].append(col)
            table["by_name"][col["name"]] = col

        for row in db.query(
                "SELECT TABLE_SCHEMA AS db, TABLE_NAME AS t, INDEX_NAME AS idx, "
                "NON_UNIQUE AS nonuniq, SEQ_IN_INDEX AS seq, COLUMN_NAME AS c, "
                "SUB_PART AS subpart, INDEX_TYPE AS itype, CARDINALITY AS card "
                "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA IN (" + marks + ") "
                "ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX", tuple(names)):
            key = (db.decode(row["db"]), db.decode(row["t"]))
            table = tables.get(key)
            if table is None:
                continue
            table["indexes"].append({
                "name": db.decode(row["idx"]),
                "unique": not _int(row["nonuniq"]),
                "seq": _int(row["seq"]),
                "column": db.decode(row["c"]),
                "sub_part": row["subpart"],
                "type": db.decode(row["itype"]) or "BTREE",
                "cardinality": row["card"],
            })

        for row in db.query(
                "SELECT tc.TABLE_SCHEMA AS db, tc.TABLE_NAME AS t, tc.CONSTRAINT_NAME AS cname, "
                "tc.CONSTRAINT_TYPE AS ctype, kcu.COLUMN_NAME AS c, kcu.ORDINAL_POSITION AS pos "
                "FROM information_schema.TABLE_CONSTRAINTS tc "
                "JOIN information_schema.KEY_COLUMN_USAGE kcu "
                "  ON kcu.CONSTRAINT_SCHEMA=tc.CONSTRAINT_SCHEMA "
                " AND kcu.CONSTRAINT_NAME=tc.CONSTRAINT_NAME "
                " AND kcu.TABLE_SCHEMA=tc.TABLE_SCHEMA AND kcu.TABLE_NAME=tc.TABLE_NAME "
                "WHERE tc.TABLE_SCHEMA IN (" + marks + ") "
                " AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY','UNIQUE') "
                "ORDER BY tc.TABLE_SCHEMA, tc.TABLE_NAME, tc.CONSTRAINT_NAME, kcu.ORDINAL_POSITION",
                tuple(names)):
            key = (db.decode(row["db"]), db.decode(row["t"]))
            table = tables.get(key)
            if table is None:
                continue
            ctype = db.decode(row["ctype"]) or ""
            column = db.decode(row["c"])
            if ctype == "PRIMARY KEY":
                table["pk"] = tuple(list(table["pk"]) + [column])
            else:
                for entry in table["unique"]:
                    if entry["name"] == db.decode(row["cname"]):
                        entry["columns"].append(column)
                        break
                else:
                    table["unique"].append({"name": db.decode(row["cname"]),
                                            "columns": [column]})

    MODEL.update({"ts": time.time(), "dbs": dbs, "tables": tables, "loaded": True})
    MODEL.pop("error", None)
    return MODEL


# -----------------------------------------------------------------------------
#  Dostep do modelu
# -----------------------------------------------------------------------------
def dbs():
    return load()["dbs"]


def tables():
    return load()["tables"]


def table(db_name, table_name):
    """Obiekt tabeli albo None. Nigdy nie rzuca - brak tabeli to normalny stan."""
    try:
        return load()["tables"].get((db_name, table_name))
    except Exception:                              # noqa: BLE001
        return None


def find_table(table_name, prefer=GAME_DBS):
    """Pierwsza tabela o tej nazwie, w kolejnosci preferencji baz."""
    model = load()["tables"]
    for database in prefer:
        found = model.get((database, table_name))
        if found is not None:
            return found
    for (database, name), found in sorted(model.items()):
        if name == table_name:
            return found
    return None


def columns(db_name, table_name):
    found = table(db_name, table_name)
    return list(found["columns"]) if found else []


def primary_key(db_name, table_name):
    found = table(db_name, table_name)
    return tuple(found["pk"]) if found else ()


def count_rows(db_name, table_name):
    """Dokladny COUNT(*) - tylko na zadanie (TABLE_ROWS to estymata InnoDB)."""
    return int(db.scalar("SELECT COUNT(*) AS n FROM " + db.qt(db_name, table_name), None, 0) or 0)


# -----------------------------------------------------------------------------
#  Relacje (baza ich nie ma - mapa jest czescia edytora)
#
#  'cover' to pokrycie zmierzone na dumpie tej bazy: ile wartosci niepustych
#  wskazuje na istniejący wiersz. Edytor pokazuje to operatorowi, bo relacja
#  bez pokrycia to najczęściej literówka w danych, a nie blad mapy.
# -----------------------------------------------------------------------------
RELATIONS = [
    {"db": "world", "table": "item_proto", "column": "refined_vnum",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("wynik ulepszenia", "refining result"), "cover": "2716/2716"},
    {"db": "world", "table": "item_proto", "column": "refine_set",
     "to_db": "world", "to_table": "refine_proto", "to_column": "id",
     "kind": "id", "label": P("przepis ulepszenia", "refining recipe"), "cover": "2660/2663"},
    {"db": "world", "table": "mob_proto", "column": "drop_item",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("drop specjalny", "special drop"), "cover": "110/122"},
    {"db": "world", "table": "mob_proto", "column": "resurrection_vnum",
     "to_db": "world", "to_table": "mob_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("potwor po odrodzeniu", "monster it comes back as"), "cover": ""},
    {"db": "world", "table": "mob_proto", "column": "polymorph_item",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("przedmiot polimorfii", "polymorph item"), "cover": ""},
    {"db": "world", "table": "shop", "column": "npc_vnum",
     "to_db": "world", "to_table": "mob_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("NPC sklepu", "shop NPC"), "cover": "12/14"},
    {"db": "world", "table": "shop_item", "column": "shop_vnum",
     "to_db": "world", "to_table": "shop", "to_column": "vnum",
     "kind": "id", "label": P("sklep", "shop"), "cover": "575/575"},
    {"db": "world", "table": "shop_item", "column": "item_vnum",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("przedmiot", "item"), "cover": "575/575"},
    {"db": "world", "table": "shop_special", "column": "item_vnum",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("przedmiot", "item"), "cover": ""},
    {"db": "world", "table": "shop_special_proto", "column": "item_vnum",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("przedmiot", "item"), "cover": ""},
    {"db": "world", "table": "crafting_proto", "column": "item_vnum",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("wynik wytwarzania", "crafting result"), "cover": ""},
    {"db": "world", "table": "object_proto", "column": "npc",
     "to_db": "world", "to_table": "mob_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("NPC budynku", "building NPC"), "cover": ""},
    {"db": "world", "table": "object_proto", "column": "upgrade_vnum",
     "to_db": "world", "to_table": "object_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("ulepszenie budynku", "building upgrade"), "cover": ""},
    {"db": "world", "table": "item_attr", "column": "apply",
     "to_db": "world", "to_table": "locale_point", "to_column": "point_name",
     "kind": "name", "label": P("nazwa bonusu", "bonus name"), "cover": ""},
    {"db": "world", "table": "item_attr_rare", "column": "apply",
     "to_db": "world", "to_table": "locale_point", "to_column": "point_name",
     "kind": "name", "label": P("nazwa bonusu", "bonus name"), "cover": ""},
    {"db": "player", "table": "item", "column": "vnum",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("przedmiot", "item"), "cover": ""},
    {"db": "player", "table": "item", "column": "owner_id",
     "to_db": "player", "to_table": "player", "to_column": "id",
     "kind": "id", "label": P("wlasciciel", "owner"), "cover": ""},
    {"db": "player", "table": "player", "column": "account_id",
     "to_db": "account", "to_table": "account", "to_column": "id",
     "kind": "id", "label": P("konto", "account"), "cover": ""},
    {"db": "player", "table": "guild_member", "column": "guild_id",
     "to_db": "player", "to_table": "guild", "to_column": "id",
     "kind": "id", "label": P("gildia", "guild"), "cover": ""},
    {"db": "player", "table": "guild_member", "column": "pid",
     "to_db": "player", "to_table": "player", "to_column": "id",
     "kind": "id", "label": P("postac", "character"), "cover": ""},
    {"db": "player", "table": "object", "column": "vnum",
     "to_db": "world", "to_table": "object_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("budynek", "building"), "cover": ""},
    {"db": "player", "table": "object", "column": "land_id",
     "to_db": "world", "to_table": "land", "to_column": "id",
     "kind": "id", "label": P("dzialka", "plot"), "cover": ""},
    {"db": "common", "table": "itemshop_items", "column": "vnum",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("przedmiot", "item"), "cover": "164/164"},
    {"db": "itemshop", "table": "ishop_items", "column": "vnum",
     "to_db": "world", "to_table": "item_proto", "to_column": "vnum",
     "kind": "vnum", "label": P("przedmiot", "item"), "cover": "17/18"},
]

_REL_INDEX = {}
for _r in RELATIONS:
    _REL_INDEX.setdefault((_r["db"], _r["table"]), {})[_r["column"]] = _r


def relation_for(db_name, table_name, column):
    return _REL_INDEX.get((db_name, table_name), {}).get(column)


def relations_for(db_name, table_name):
    return dict(_REL_INDEX.get((db_name, table_name), {}))


def relation_ok(rel):
    """Czy obie strony relacji istnieja w tej bazie (zaden FK tego nie pilnuje)."""
    if not rel:
        return False
    left = table(rel["db"], rel["table"])
    right = table(rel["to_db"], rel["to_table"])
    if not left or not right:
        return False
    return (rel["column"] in left["by_name"] and rel["to_column"] in right["by_name"])


# -----------------------------------------------------------------------------
#  Wykrywanie systemow -- kafelek modulu istnieje tylko wtedy, gdy system jest
# -----------------------------------------------------------------------------
def _has(db_name, table_name, column=None):
    found = table(db_name, table_name)
    if found is None:
        return False
    return column is None or column in found["by_name"]


def detect():
    """Slownik modul -> informacja, ktore tabele go uzasadniaja.

    Nic nie jest 'na wszelki wypadek': jezeli tabeli nie ma, modulu nie ma.
    """
    found = {}

    def add(module, *reasons):
        found[module] = {"reasons": reasons}

    item_tbl = table("world", "item_proto") or table("player", "item_proto")
    mob_tbl = table("world", "mob_proto") or table("player", "mob_proto")

    if item_tbl:
        add("items", item_tbl["db"] + "." + item_tbl["name"])
    if mob_tbl:
        add("mobs", mob_tbl["db"] + "." + mob_tbl["name"])
    if _has("world", "refine_proto") and item_tbl and "refine_set" in item_tbl["by_name"]:
        add("refine", "world.refine_proto", "%s.refine_set" % item_tbl["name"])
    if _has("world", "item_attr"):
        add("bonuses", "world.item_attr",
            *(["world.item_attr_rare"] if _has("world", "item_attr_rare") else []))
    if (mob_tbl and "drop_item" in mob_tbl["by_name"]) or _has("world", "etc_drop_item"):
        add("drops", *([("%s.drop_item" % mob_tbl["name"])] if mob_tbl and
                       "drop_item" in mob_tbl["by_name"] else []),
            *(["world.etc_drop_item"] if _has("world", "etc_drop_item") else []))
    if _has("world", "shop") and _has("world", "shop_item"):
        add("shops", "world.shop", "world.shop_item",
            *(["world.shop_special_proto"] if _has("world", "shop_special_proto") else []))
    if _has("world", "object_proto") or _has("world", "land") or _has("player", "object"):
        add("spawns", *[n for n, ok in (("world.object_proto", _has("world", "object_proto")),
                                       ("world.land", _has("world", "land")),
                                       ("player.object", _has("player", "object"))) if ok])
    if _has("world", "skill_proto"):
        add("skills", "world.skill_proto")
    if _has("common", "exp_table"):
        add("exp", "common.exp_table")
    if _has("world", "crafting_proto"):
        add("crafting", "world.crafting_proto")
    if _has("world", "quest_reward_proto"):
        add("quests", "world.quest_reward_proto")
    if _has("common", "itemshop_items"):
        add("itemshop", "common.itemshop_items")
    if _has("common", "gmlist"):
        add("gm", "common.gmlist")
    if item_tbl and "type" in item_tbl["by_name"]:
        add("chests", item_tbl["db"] + "." + item_tbl["name"] + " (typ 20/23)")

    add("structure", "information_schema")
    add("history", "player.editsql_history")
    add("labels", "player.editsql_labels")
    add("apply", "player.web_admin_queue")
    return found


def table_notes(db_name, table_name):
    """Ostrzezenia, ktore edytor MUSI pokazac przy tabeli (z ustalen analizy)."""
    notes = []
    if db_name == "world" and table_name == "etc_drop_item":
        notes.append(("warn", T("Silnik NIE czyta tej tabeli: drop mapowy jest ładowany z pliku "
                                "etc_drop_item.txt. Zapis tutaj nie zmieni gry.",
                                "The engine does NOT read this table: the map drop is loaded from "
                                "etc_drop_item.txt. A save here will not change the game.")))
    if db_name == "world" and table_name == "locale_point":
        notes.append(("warn", T("Silnik nie czyta tej tabeli - edytor bierze z niej tylko polskie "
                                "nazwy bonusów.",
                                "The engine does not read this table - the editor takes only the "
                                "bonuses' Polish names from it.")))
    if db_name == "common" and table_name == "m2_switches":
        notes.append(("warn", T("To nie jest konfiguracja gry: ani bin/db, ani bin/game nie "
                                "czytają tej tabeli.",
                                "This is not the game's configuration: neither bin/db nor bin/game "
                                "reads this table.")))
    if db_name == "common" and table_name == "exp_table":
        notes.append(("warn", T("Nie usuwaj poziomów: bez tej tabeli serwer nie wstaje. Wartości "
                                "nie muszą rosnąć z poziomem (118 = 119), więc edytor tego nie wymusza.",
                                "Do not delete levels: the server does not start without this table. "
                                "The values need not grow with the level (118 = 119), so the editor "
                                "does not enforce it.")))
    if db_name == "common" and table_name == "gmlist":
        notes.append(("warn", T("Pusta lista GM nie odbiera praw: przy następnym starcie najstarsza "
                                "postać konta admina dostanie IMPLEMENTOR.",
                                "An empty GM list takes no rights away: at the next start the admin "
                                "account's oldest character gets IMPLEMENTOR.")))
    if db_name == "account" and table_name == "account":
        notes.append(("warn", T("Hasła są hashami; kolumny hwid i securitycode biorą udział "
                                "w logowaniu.",
                                "Passwords are hashes; the hwid and securitycode columns take part "
                                "in the login.")))
    if db_name == "log":
        notes.append(("info", T("Baza logów: tylko do odczytu.", "The log database: read only.")))
    found = table(db_name, table_name)
    if found is not None and found["engine"].upper() == "MYISAM":
        notes.append(("warn", T("Tabela MyISAM: bez transakcji, więc edytor jej nie zapisuje.",
                                "A MyISAM table: no transactions, so the editor does not write it.")))
    if found is not None and found["type"] == "VIEW":
        notes.append(("info", T("To WIDOK nad inną tabelą - zapisuj w tabeli źródłowej.",
                                "This is a VIEW over another table - write in the source table.")))
    return notes


# Tabele bez klucza glownego, ktore maja jednak kolumne jednoznacznie wskazujaca
# wiersz. Zmierzone na dumpie tego projektu:
#   world.item_attr      - 44 wiersze, 44 rozne apply  (brak duplikatow)
#   world.item_attr_rare - 20 wierszy, 20 roznych apply (brak duplikatow)
# Edytor NIE zaklada, ze tak zostanie: safety.uniqueness_guard() sprawdza przed
# kazdym zapisem, ze klucz wskazuje dokladnie jeden wiersz i odmawia, gdy nie.
LOGICAL_KEYS = {
    ("world", "item_attr"): ("apply",),
    ("world", "item_attr_rare"): ("apply",),
    ("world", "shop_item"): ("shop_vnum", "item_vnum", "count"),
}

# Only the reviewed world-data modules can write. The structure browser is
# read-only, including live characters, accounts, queue tables and backups.
WRITE_TABLES = {
    'world': {'item_proto', 'mob_proto', 'refine_proto', 'item_attr', 'item_attr_rare',
              'shop', 'shop_item', 'land', 'object_proto', 'skill_proto',
              'crafting_proto', 'quest_reward_proto'},
    'common': {'exp_table', 'itemshop_items', 'gmlist'},
}


# Tabele, w ktorych edytor dodaje i usuwa CALE wiersze. Kazda ma w writes.py
# wlasna, przejrzana sciezke (schemat, referencje, historia, cofanie) - nie ma
# tu ogolnego INSERT/DELETE dla dowolnej tabeli z WRITE_TABLES.
ROW_TABLES = {('world', 'shop_item'), ('world', 'crafting_proto'), ('common', 'itemshop_items')}


def logical_key(db_name, table_name):
    return LOGICAL_KEYS.get((db_name, table_name))


def writable(db_name, table_name, logical_key=None, for_insert=False):
    """(True, '') albo (False, powod). Biala lista zapisu.

    `logical_key` to kolumny, ktore jednoznacznie wskazuja wiersz w tabeli BEZ
    klucza glownego. Edytor nie wierzy na slowo: safety.uniqueness_guard()
    sprawdza przed kazdym zapisem, ze taki klucz wskazuje dokladnie jeden wiersz.

    `for_insert=True` to dodanie NOWEGO wiersza: klucz nie jest do tego potrzebny
    (baza go nada albo wskaze go UNIQUE), wiec tabela bez klucza glownego moze
    przyjac nowy wiersz. Usuwanie i edycja nadal wymagaja klucza.
    """
    if table_name not in WRITE_TABLES.get(db_name, set()):
        return False, bilingual("tabela poza listą edycji / table is read-only", "the table is read only")
    if for_insert and (db_name, table_name) not in ROW_TABLES:
        return False, bilingual("dodawanie tylko pozycji sklepów, przepisów wytwarzania i ItemShopu / "
                                "inserts are limited to shop, crafting and ItemShop rows",
                                "inserts are limited to shop, crafting and ItemShop rows")
    if db_name in ("information_schema", "performance_schema", "mysql", "sys"):
        return False, T("baza systemowa", "a system database")
    if db_name == "log":
        return False, T("baza logów jest tylko do odczytu", "the log database is read only")
    if db_name == "account" and table_name == "account":
        # Hasla (hash), hwid i securitycode wchodza w logowanie; edycja konta
        # nalezy do swiadomej decyzji, nie do formularza z bazy.
        return False, T("kont nie edytuje się z tego formularza", "accounts are not edited in this form")
    found = table(db_name, table_name)
    if found is None:
        return False, T("nie ma takiej tabeli", "there is no such table")
    if found["type"] == "VIEW":
        return False, T("to widok - zapisuj w tabeli źródłowej", "it is a view - write in the source table")
    if found['engine'].upper() != 'INNODB':
        return False, bilingual("wymagany silnik InnoDB / InnoDB is required", "InnoDB is required")
    if for_insert:
        return True, ""
    if not found["pk"] and not (logical_key or LOGICAL_KEYS.get((db_name, table_name))):
        # Bez klucza UPDATE moglby trafic wiele wierszy naraz, a cofniecie
        # zmiany nie mialoby po czym trafic. Takie tabele sa w edytorze tylko
        # do odczytu - chyba ze mamy klucz logiczny.
        return False, T("tabela bez klucza głównego - tylko do odczytu",
                        "a table without a primary key - read only")
    return True, ""


def load_error():
    return MODEL.get("error")
