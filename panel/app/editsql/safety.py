# =============================================================================
#  /editsql -- bezpieczny zapis.
#
#  Caly przepis z raportu w jednym miejscu:
#
#      ODCZYT -> EDYCJA -> PODGLAD -> POTWIERDZENIE -> SQL
#
#  i twarde zasady, ktore ten modul egzekwuje:
#
#   * ZADNYCH nazw z zadania HTTP. Tabela i kolumny pochodza z metamodelu,
#     a kazde uzycie przechodzi przez whitelist() i db.qi(). Zadanie podaje
#     tylko WARTOSCI - i to one leca jako parametry (%s), nigdy sklejane.
#   * ZADNEGO DROP/TRUNCATE/DELETE calych tabel. DELETE istnieje wylacznie jako
#     usuniecie JEDNEGO wiersza po kluczu glownym, z wpisem w historii.
#   * ZAPIS W TRANSAKCJI. Polowa operacji nie moze zostac wykonana: albo COMMIT
#     wszystkich kolumn, albo ROLLBACK wszystkiego.
#   * PODGLAD TRZYMANY NA SERWERZE, nie w formularzu. Gdyby stare wartosci
#     przyszly z przegladarki, "podglad zmian" bylby do podmienienia jednym
#     polem ukrytym - a wtedy nie jest podgladem, tylko dekoracja.
#   * BLOKADA OPTYMISTYCZNA. Przed zapisem sprawdzamy, czy wiersz w bazie ma
#     nadal te wartosci, ktore widzial operator. Jesli nie (ktos inny albo sama
#     gra go zmienila), zapis jest odrzucany - nie nadpisujemy cudzej zmiany.
#   * HISTORIA I COFANIE. Kazda zmieniona kolumna to wiersz w
#     player.editsql_history; cofniecie robi odwrotny UPDATE i tez sie zapisuje.
# =============================================================================

import hashlib
import json
import threading
import time
import uuid

from . import db, schema
from .i18n import T

# Ile czeka niepotwierdzony podglad zmiany i ile ich trzymamy.
PENDING_TTL = 1800.0
PENDING_MAX = 200

_lock = threading.RLock()
_pending = {}


# -----------------------------------------------------------------------------
#  Biala lista
# -----------------------------------------------------------------------------
class Denied(Exception):
    """Operacja poza biala lista - zawsze po stronie serwera, nigdy z UI."""


def key_columns(table, keys=None):
    """Kolumny tozsamosci wiersza: klucz glowny albo klucz logiczny.

    Klucz logiczny istnieje po to, zeby dala sie edytowac tabela, ktora w tej
    bazie NIE MA klucza glownego, ale ma kolumne jednoznacznie identyfikujaca
    wiersz (world.item_attr.apply: 44 wiersze, 44 rozne wartosci - zmierzone na
    dumpie). Nie jest to zalozenie: przed kazdym zapisem edytor sprawdza
    COUNT(*) po tym kluczu i odmawia, gdy wierszy jest wiecej niz jeden, bo
    wtedy UPDATE moglby trafic kilka naraz, a cofniecie nie mialoby po czym
    trafić.
    """
    if keys:
        return tuple(keys)
    return tuple(table["pk"])


def uniqueness_guard(table, columns, values):
    """Podnosi Denied, gdy klucz logiczny nie wskazuje DOKLADNIE jednego wiersza."""
    if not columns:
        raise Denied(T("brak klucza: nie wiem, ktory wiersz zmienic",
                       "no key: there is no telling which row to change"))
    where = " AND ".join("%s=%%s" % db.qi(name) for name in columns)
    found = int(db.scalar("SELECT COUNT(*) AS n FROM %s WHERE %s"
                          % (db.qt(table["db"], table["name"]), where),
                          tuple(values), 0) or 0)
    if found != 1:
        raise Denied(T("klucz %s wskazuje %d wierszy (musi dokładnie 1) - nie zapisuję",
                       "key %s matches %d rows (it must be exactly 1) - not saving")
                     % (", ".join(columns), found))
    return True


def whitelist(db_name, table_name, logical_key=None, for_insert=False):
    """Tabela gotowa do zapisu albo Denied z powodem."""
    ok, reason = schema.writable(db_name, table_name, logical_key, for_insert)
    if not ok:
        raise Denied(reason)
    found = schema.table(db_name, table_name)
    if found is None:
        raise Denied(T("nie ma takiej tabeli", "there is no such table"))
    return found


def column(table, name):
    """Kolumna z metamodelu albo Denied. Nazwa z zadania nigdy nie idzie dalej."""
    col = table["by_name"].get(str(name))
    if col is None:
        raise Denied(T("nie ma takiej kolumny: %r", "there is no such column: %r") % (name,))
    return col


def locked_columns(db_name, table_name):
    """Kolumny, ktorych edytor nie pozwala ruszyc bez decyzji czlowieka."""
    blocked = {"password", "hwid", "securitycode", "social_id"}
    if table_name == "account":
        return blocked
    if db_name == "player" and table_name == "player":
        return {"account_id", "name", "id"}
    if table_name in ("item_proto", "mob_proto"):
        # `name` to wewnetrzna nazwa z klienta: bajty EUC-KR w kolumnie cp1250.
        # Przepisanie jej przez formularz zamieniloby koreanskie znaki na "?"
        # i rozjechalo sie z plikami klienta - wiec tylko do odczytu.
        return {"name"}
    if table_name in ("land", "object_proto", "gmlist", "refine_proto"):
        return set()
    return {"id"}


# -----------------------------------------------------------------------------
#  Walidacja wartosci
# -----------------------------------------------------------------------------
class Invalid(Exception):
    pass


def validate(col, raw):
    """(ok, wartosc, blad). Wartosc jest JUZ w typie kolumny (int/float/str/bytes/None)."""
    name = col["name"]
    if raw is None:
        raw = ""
    text = raw if isinstance(raw, str) else str(raw)
    text = text.strip()

    if col["auto"]:
        raise Invalid(T("%s: kolumna AUTO_INCREMENT - nie edytuje sie recznie",
                        "%s: an AUTO_INCREMENT column - not edited by hand") % name)
    if col.get("extra", "").startswith("on update"):
        raise Invalid(T("%s: kolumna aktualizowana automatycznie przez baze",
                        "%s: a column the database updates itself") % name)

    # --- typy tekstowe / binarne -------------------------------------------
    if col["choices"] is not None:
        if col['data_type'] == 'enum' and text not in col['choices']:
            raise Invalid('%s: invalid ENUM value' % name)
        parts = [p for p in (x.strip() for x in text.split(",")) if p]
        unknown = [p for p in parts if p not in col["choices"]]
        if unknown:
            raise Invalid(T("%s: nie ma takiej wartości: %s", "%s: no such value: %s")
                          % (name, ", ".join(unknown)))
        if col['set']:
            parts = [choice for choice in col['choices'] if choice in parts]
        value = ",".join(parts)
        return True, _prepare(col, value), None

    if col["data_type"] in ("char", "varchar", "text", "tinytext", "mediumtext", "longtext"):
        if text == "" and col["nullable"]:
            return True, None, None
        if col["length"] and len(text) > col["length"]:
            raise Invalid(T("%s: maksymalnie %d znaków (jest %d)",
                            "%s: at most %d characters (there are %d)")
                          % (name, col["length"], len(text)))
        if col["charset"] and not db.encodable(text, col["charset"]):
            bad = "".join(sorted({ch for ch in text if not db.encodable(ch, col["charset"])}))
            raise Invalid(T("%s: kodowanie kolumny (%s) nie ma znaków: %s",
                            "%s: the column's encoding (%s) has no such characters: %s")
                          % (name, col["charset"], bad))
        return True, _prepare(col, text), None

    if col["data_type"] in ("binary", "varbinary", "blob", "tinyblob", "mediumblob", "longblob"):
        if text == "" and col["nullable"]:
            return True, None, None
        return True, _prepare(col, text), None

    if col["data_type"] in ("date", "datetime", "timestamp", "time", "year"):
        if text == "" and col["nullable"]:
            return True, None, None
        if not _looks_like_datetime(text, col["data_type"]):
            raise Invalid(T("%s: oczekuje formatu %s", "%s: expects the format %s")
                          % (name, T(*_DATETIME_HINT[col["data_type"]])))
        return True, text, None

    # --- liczby -------------------------------------------------------------
    if col["data_type"] in ("float", "double", "decimal"):
        if text == "":
            if col["nullable"]:
                return True, None, None
            raise Invalid(T("%s: wymagana liczba", "%s: a number is required") % name)
        try:
            from decimal import Decimal
            value = Decimal(text.replace(',', '.'))
            if not value.is_finite():
                raise ValueError('non-finite number')
        except (ValueError, __import__("decimal").InvalidOperation):
            raise Invalid(T("%s: to nie jest liczba: %r", "%s: not a number: %r") % (name, text))
        return True, value, None

    if col["data_type"] in ("tinyint", "smallint", "mediumint", "int", "bigint", "bit"):
        if text == "":
            if col["nullable"]:
                return True, None, None
            raise Invalid(T("%s: wymagana liczba", "%s: a number is required") % name)
        try:
            value = int(text)
        except ValueError:
            raise Invalid(T("%s: to nie jest liczba całkowita: %r", "%s: not a whole number: %r")
                          % (name, text))
        low, high = col["range"] or (None, None)
        if low is not None and (value < low or value > high):
            raise Invalid(T("%s: poza zakresem %d…%d (jest %d)", "%s: out of the range %d…%d (it is %d)")
                          % (name, low, high, value))
        return True, value, None

    # --- nieznany typ: przepuszczamy jako tekst, ale kodujemy jak kolumna ----
    return True, _prepare(col, text), None


# (Polish, English) - the format a date column expects, as the reader writes it.
_DATETIME_HINT = {"date": ("RRRR-MM-DD", "YYYY-MM-DD"),
                  "datetime": ("RRRR-MM-DD GG:MM:SS", "YYYY-MM-DD HH:MM:SS"),
                  "timestamp": ("RRRR-MM-DD GG:MM:SS", "YYYY-MM-DD HH:MM:SS"),
                  "time": ("GG:MM:SS", "HH:MM:SS"), "year": ("RRRR", "YYYY")}


def _looks_like_datetime(text, kind):
    import re
    if kind == "date":
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", text))
    if kind == "time":
        return bool(re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", text))
    if kind == "year":
        return bool(re.match(r"^\d{4}$", text))
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$", text))


def _prepare(col, text):
    """Zamienia tekst na to, co pojedzie do bazy: bajty w kodowaniu kolumny
    (albo surowe bajty dla VARBINARY) i liczba znakow sprawdzona wyzej."""
    if col["data_type"] in ("binary", "varbinary", "blob", "tinyblob", "mediumblob",
                            "longblob"):
        return db.encode(text, col["charset"] or "latin1")
    if col["charset"]:
        return db.encode(text, col["charset"])
    return text


# -----------------------------------------------------------------------------
#  Przepisy wytwarzania (world.crafting_proto) - zasady ponad typ kolumny
#
#  Rdzen db czyta kolumne recipe przy starcie (InitializeCraftingTable):
#  std::getline po przecinku i std::stoul/std::stoi bez try. Pusty albo
#  nieliczbowy kawalek ("50901,,5", "50901,5,abc") rzuca wyjatek, ktorego nikt
#  nie lapie - rdzen nie wstaje. Dlatego skladniki ida do bazy wylacznie jako
#  "vnum,ilosc,..." z samych cyfr ASCII, najwyzej CRAFTING_MATERIAL_MAX_NUM par
#  (reszte silnik po cichu pomija). req_level laduje do BYTE (300 bylby po
#  cichu 44), a szansa to number(1,100) <= chance w quest/libs/crafting.
#  recipe_vnum NIE jest przedmiotem: to klucz postepu nauki (flaga
#  crafting.progress_<numer>), wiec nie sprawdzamy go w item_proto.
# -----------------------------------------------------------------------------
CRAFTING = ("world", "crafting_proto")
CRAFTING_MATERIALS_MAX = 10
ROW_COLUMN = "*"                          # wpis historii o calym wierszu
_CRAFTING_RANGES = {"vnum": (1, None), "item_vnum": (1, None), "count": (1, None),
                    "price": (0, None), "chance": (1, 100), "req_progress": (0, None),
                    "req_level": (0, 255), "recipe_vnum": (0, None)}
_DIGITS = __import__("re").compile(r"^[0-9]{1,10}\Z")      # \Z: "$" przepuszcza "12\n"


def parse_recipe(text):
    """'50901,5,50721,10' -> [(50901, 5), (50721, 10)] albo Invalid."""
    text = (text or "").strip()
    if not text:
        raise Invalid(T("recipe: przepis potrzebuje co najmniej jednego składnika (vnum,ilość)",
                        "recipe: a recipe needs at least one ingredient (vnum,count)"))
    parts = [part.strip() for part in text.split(",")]
    if "" in parts:
        raise Invalid(T("recipe: puste miejsce między przecinkami (np. „50901,,5”) - rdzeń db "
                        "nie wczyta takiego przepisu i nie wstanie",
                        "recipe: an empty place between commas (e.g. \"50901,,5\") - the db "
                        "core cannot read such a recipe and will not start"))
    bad = [part for part in parts if not _DIGITS.match(part)]
    if bad:
        raise Invalid(T("recipe: składniki to same liczby rozdzielone przecinkami (vnum,ilość,...), "
                        "a jest: %s",
                        "recipe: the ingredients are numbers only, separated by commas "
                        "(vnum,count,...), and there is: %s")
                      % ", ".join(repr(part) for part in bad[:3]))
    if len(parts) % 2:
        raise Invalid(T("recipe: ostatni składnik nie ma ilości (potrzebne pary vnum,ilość)",
                        "recipe: the last ingredient has no count (vnum,count pairs are needed)"))
    pairs = [(int(parts[i]), int(parts[i + 1])) for i in range(0, len(parts), 2)]
    if len(pairs) > CRAFTING_MATERIALS_MAX:
        raise Invalid(T("recipe: najwyżej %d składników (silnik pomija resztę), jest %d",
                        "recipe: %d ingredients at most (the engine skips the rest), there are %d")
                      % (CRAFTING_MATERIALS_MAX, len(pairs)))
    seen = set()
    for vnum, count in pairs:
        if not 1 <= vnum <= 4294967295:
            raise Invalid(T("recipe: vnum składnika musi być większy od zera (jest %d)",
                            "recipe: an ingredient's vnum must be above zero (it is %d)") % vnum)
        if not 1 <= count <= 2147483647:
            raise Invalid(T("recipe: ilość składnika %d musi być od 1 do 2147483647 (jest %d)",
                            "recipe: the count of ingredient %d must be 1 to 2147483647 (it is %d)")
                          % (vnum, count))
        if vnum in seen:
            raise Invalid(T("recipe: przedmiot %d jest w składnikach dwa razy - połącz ilości",
                            "recipe: item %d is in the ingredients twice - add the counts together")
                          % vnum)
        seen.add(vnum)
    return pairs


def recipe_text(pairs):
    return ",".join("%d,%d" % pair for pair in pairs)


def _bounds(name, value, low, high):
    if value < low or (high is not None and value > high):
        raise Invalid(T("%s: dozwolone %s (jest %s)", "%s: allowed %s (it is %s)")
                      % (name, ("%d…%d" % (low, high)) if high is not None
                         else (T("od %d", "from %d") % low), value))


def column_rule(table, col, value):
    """Zasady gry dla kolumny ponad jej typ w bazie. Zwraca wartosc (skladniki
    ujednolicone do "vnum,ilosc,...") albo podnosi Invalid."""
    if (table["db"], table["name"]) == ITEMSHOP:
        return _itemshop_rule(col, value)
    if (table["db"], table["name"]) != CRAFTING:
        return value
    name = col["name"]
    if name == "recipe":
        text = db.decode(value, col["charset"]) if isinstance(value, (bytes, bytearray)) else value
        return _prepare(col, recipe_text(parse_recipe(text)))
    bounds = _CRAFTING_RANGES.get(name)
    if bounds and value is not None:
        _bounds(name, value, *bounds)
    return value


# -----------------------------------------------------------------------------
#  ItemShop offers (common.itemshop_items, mt2009) - the game's rules over the
#  column types (Drip, 7 October)
#
#  The db core sends every row to the game cores as it is, and the game core
#  of 2.2.75 and before read the item table of a row's vnum without a check:
#  Drip "deleted" the wedding page by setting each row's vnum, count, price
#  and level to 0 (the editor had no delete for this table), and every open
#  of the ItemShop killed the core that hosted the player. So a form never
#  sets vnum or count to 0 - it says where the delete is instead - and an
#  offer must be one the game can sell: an item of item_proto, a count from 1
#  to that item's stack (BuyItem gives at most a stack a piece; a stack of 0
#  divided by zero), a price from 0 to what ten purchases at once still fit in
#  the engine's 32-bit sum (BuyItem multiplies by 1 to 10), a level the
#  server's characters can have (MAX_LEVEL; the engine keeps it in a BYTE),
#  an index from 1 (the client stops reading the catalogue at index 0). The
#  currency is the column's ENUM, which validate() already holds to.
# -----------------------------------------------------------------------------
ITEMSHOP = ("common", "itemshop_items")
ITEMSHOP_PRICE_MAX = 214748364


def max_level():
    """The server's MAX_LEVEL as the panel knows it (admin_panel.MAX_LEVEL)."""
    try:
        level = int(db.ns().get("MAX_LEVEL", 120))
    except Exception:                              # noqa: BLE001 - no panel, the game's own ceiling
        level = 120
    return min(max(level, 1), 255)


def _itemshop_ranges():
    return {"index": (1, None), "vnum": (1, None), "count": (1, None),
            "price": (0, ITEMSHOP_PRICE_MAX), "minLevel": (0, max_level())}


def _zero_offer(name):
    """The refusal of a 0 in vnum or count: it says where the delete is."""
    return Invalid(T("%s: 0 to nie jest pozycja sklepu - gra nie zna przedmiotu 0 ani pozycji bez "
                     "sztuk, a rdzeń, który wysłał taką pozycję, padał przy każdym otwarciu "
                     "ItemShopu. Pozycję zdejmuje się ze sklepu przyciskiem „Usuń tę pozycję” "
                     "(albo zaznacz ją na liście ItemShop i „Usuń zaznaczone”), a nie zerem.",
                     "%s: 0 is no offer - the game knows no item 0 and no offer of nothing, and a "
                     "core that sent such an offer went down at every open of the ItemShop. An "
                     "offer comes off the shop with “Delete this offer” (or select it on the "
                     "ItemShop list and “Delete the selected”), not with a 0.") % name)


def _itemshop_rule(col, value):
    name = col["name"]
    if value is None:
        return value
    if name in ("vnum", "count") and value == 0:
        raise _zero_offer(name)
    bounds = _itemshop_ranges().get(name)
    if bounds:
        _bounds(name, value, *bounds)
    return value


def item_stack(vnum):
    """(present, stack) of an item_proto row; stack is None where the table
    has no stack column (no limit to judge by)."""
    items = schema.table("world", "item_proto") or schema.table("player", "item_proto")
    if items is None:
        return False, None
    has_stack = "stack" in items["by_name"]
    rows = db.query("SELECT %s AS s FROM %s WHERE %s=%%s"
                    % (db.qi("stack") if has_stack else "NULL", db.qt(items["db"], items["name"]),
                       db.qi("vnum")), (int(vnum),))
    if not rows:
        return False, None
    return True, (int(rows[0]["s"]) if has_stack and rows[0]["s"] is not None else None)


def offer_problems(vnum, count, present, stack):
    """What keeps (vnum, count) from being an offer, given the item's row."""
    problems = []
    if vnum is not None and int(vnum) < 1:
        problems.append(str(_zero_offer("vnum")))
    elif vnum is not None and not present:
        problems.append(T("%s: nie ma przedmiotu o vnum %d w item_proto",
                          "%s: there is no item with vnum %d in item_proto") % ("vnum", int(vnum)))
    if count is not None and int(count) < 1:
        problems.append(str(_zero_offer("count")))
    elif count is not None and present and stack is not None:
        if stack < 1:
            problems.append(T("count: przedmiot %d ma w item_proto stos 0 - ItemShop go nie sprzeda",
                              "count: item %d has a stack of 0 in item_proto - the ItemShop cannot "
                              "sell it") % int(vnum))
        elif int(count) > stack:
            problems.append(T("count: najwyżej %d - tyle mieści jeden stos przedmiotu %d "
                              "(stack w item_proto), jest %d",
                              "count: %d at most - one stack of item %d holds that many "
                              "(stack in item_proto), it is %d") % (stack, int(vnum), int(count)))
    return problems


def itemshop_problems(table, values, new=True):
    """Bledy, ktore wymagaja bazy: zajety numer pozycji, brak przedmiotu, stos.

    Asked of a new row (`new`) and of an edited row as it would be after the
    edit, so a row left broken (Drip's vnum 0) is not saved again as it is;
    the save (writes.py) asks the same under its locks."""
    problems = []
    if (table["db"], table["name"]) != ITEMSHOP:
        return problems
    if new and values.get("index") is not None:
        taken = db.scalar("SELECT COUNT(*) AS n FROM %s WHERE %s=%%s"
                          % (db.qt(table["db"], table["name"]), db.qi("index")),
                          (values["index"],), 0)
        if taken:
            problems.append(T("index: pozycja %s już istnieje - wybierz wolny numer",
                              "index: position %s exists already - pick a free number")
                            % values["index"])
    vnum, count = values.get("vnum"), values.get("count")
    present, stack = item_stack(vnum) if vnum is not None and int(vnum) > 0 else (False, None)
    problems.extend(offer_problems(vnum, count, present, stack))
    return problems


def row_problems(table, values, new=True):
    """The checks a whole-row table needs of the database (schema.ROW_TABLES)."""
    if (table["db"], table["name"]) == ITEMSHOP:
        return itemshop_problems(table, values, new)
    return crafting_problems(table, values, new)


def build_row(table, form):
    """Nowy wiersz z formularza: (values, errors), wartosci juz w typach kolumn.

    Kazda kolumna przechodzi validate() i column_rule() - tak samo jak edycja,
    wiec nowy wiersz nie moze dostac czegos, czego formularz edycji by nie
    przepuscil. Kolumny AUTO_INCREMENT i "on update" zostaja bazie.
    """
    values, errors = {}, []
    getter = getattr(form, "getlist", None)
    for col in table["columns"]:
        name = col["name"]
        if col["auto"] or col.get("extra", "").startswith("on update"):
            continue
        if col["set"] and ("__set__" + name) in form:
            picked = getter(name) if getter else ([form.get(name)] if form.get(name) else [])
            raw = ",".join(v for v in picked if v)
        else:
            raw = form.get(name)
        try:
            _, value, _ = validate(col, raw)
            values[name] = column_rule(table, col, value)
        except Invalid as exc:
            errors.append(str(exc))
    return values, errors


def _item_vnums_present(vnums):
    """Te z podanych vnumow, ktore SA w item_proto (zapytanie bez blokad)."""
    items = schema.table("world", "item_proto") or schema.table("player", "item_proto")
    wanted = sorted({int(v) for v in vnums})
    if items is None or not wanted:
        return set()
    rows = db.query("SELECT %s AS v FROM %s WHERE %s IN (%s)"
                    % (db.qi("vnum"), db.qt(items["db"], items["name"]), db.qi("vnum"),
                       ",".join(["%s"] * len(wanted))), tuple(wanted))
    return {int(row["v"]) for row in rows}


def crafting_problems(table, values, new=True):
    """Bledy, ktore wymagaja bazy: zajety numer, brakujacy wynik albo skladnik.

    Podglad pyta o to bez blokad, zeby operator zobaczyl blad od razu; zapis
    (writes.py) sprawdza to samo jeszcze raz pod blokada w transakcji.
    """
    problems = []
    if (table["db"], table["name"]) != CRAFTING:
        return problems
    if new and values.get("vnum") is not None:
        taken = db.scalar("SELECT COUNT(*) AS n FROM %s WHERE %s=%%s"
                          % (db.qt(table["db"], table["name"]), db.qi("vnum")),
                          (values["vnum"],), 0)
        if taken:
            problems.append(T("vnum: przepis #%s już istnieje - wybierz wolny numer",
                              "vnum: recipe #%s already exists - pick a free number") % values["vnum"])
    wanted = {}
    if values.get("item_vnum"):
        wanted.setdefault(int(values["item_vnum"]), "item_vnum")
    if values.get("recipe") is not None:
        text = values["recipe"]
        if isinstance(text, (bytes, bytearray)):
            text = db.decode(text, table["by_name"]["recipe"]["charset"])
        try:
            for vnum, _count in parse_recipe(text):
                wanted.setdefault(vnum, "recipe")
        except Invalid as exc:
            problems.append(str(exc))
    if wanted:
        present = _item_vnums_present(wanted)
        for vnum, column_name in sorted(wanted.items()):
            if vnum not in present:
                problems.append(T("%s: nie ma przedmiotu o vnum %d w item_proto",
                                  "%s: there is no item with vnum %d in item_proto") % (column_name, vnum))
    return problems


def placeholder_for(col):
    """Fragment SET: dla tekstu CONVERT(_binary %s USING <charset kolumny>).

    Dzieki temu zapis jest poprawny dla cp1250, latin1, latin2 i utf8mb3 naraz,
    niezaleznie od kodowania polaczenia. Dla VARBINARY bajty ida wprost.
    """
    if col["choices"] is not None or col["data_type"] in (
            "char", "varchar", "text", "tinytext", "mediumtext", "longtext"):
        if col["charset"] and db.qi(col["charset"]):
            # PyMySQL sam dokleja do bajtow prefiks _binary, wiec tu go juz nie
            # ma ("_binary _binary X'..'" to blad skladni i psulo kazdy zapis tekstu).
            return "CONVERT(%%s USING %s)" % col["charset"]
        return "%s"
    return "%s"


# -----------------------------------------------------------------------------
#  Zestaw zmian i podglad
# -----------------------------------------------------------------------------
def pk_of(table, row, keys=None):
    """Wartosci klucza wiersza (kolejnosc z metamodelu albo z klucza logicznego)."""
    out = []
    for name in key_columns(table, keys):
        value = row.get(name)
        if isinstance(value, (bytes, bytearray)):
            value = db.decode(value, table["by_name"][name]["charset"])
        out.append(value)
    return out


def pk_json(table, row, keys=None):
    return json.dumps(dict(zip(key_columns(table, keys), pk_of(table, row, keys))),
                      ensure_ascii=False)


def fetch_row(table, pk_values, keys=None):
    """Wiersz po kluczu, z tekstami jako str (dekodowane per kolumna)."""
    columns = key_columns(table, keys)
    where = " AND ".join("%s=%%s" % db.qi(name) for name in columns)
    rows = db.query("SELECT * FROM %s WHERE %s LIMIT 1"
                    % (db.qt(table["db"], table["name"]), where), tuple(pk_values))
    if not rows:
        return None
    return decode_row(table, rows[0])


def decode_row(table, row):
    """Kazda kolumna tekstowa: bajty -> str w kodowaniu TEJ kolumny."""
    out = {}
    for name, value in row.items():
        col = table["by_name"].get(name)
        if col is not None and isinstance(value, (bytes, bytearray)):
            out[name] = db.decode(value, col["charset"])
        else:
            out[name] = value
    return out


def editable_columns(db_name, table_name, logical_key=None):
    """Kolumny, ktore edytor pokaze w formularzu (reszta jest tylko do odczytu)."""
    table = whitelist(db_name, table_name, logical_key)
    blocked = locked_columns(db_name, table_name)
    out = []
    for col in table["columns"]:
        if col["name"] in blocked or col["auto"]:
            continue
        if col.get("extra", "").startswith("on update"):
            continue
        out.append(col)
    return table, out


def build_changes(table, row, form, only=None, keys=()):
    """Porownuje formularz z wierszem. Zwraca (changes, errors).

    changes = [{'column','old','new','sql_value','label'}] - zawiera WYLACZNIE
    kolumny, ktore naprawde sie roznia, wiec UPDATE dotyka tylko ich.
    """
    changes, errors = [], []
    blocked = set(locked_columns(table["db"], table["name"])) | set(keys or ())
    blocked |= set(table["pk"])
    for col in table["columns"]:
        name = col["name"]
        if name in blocked or col["auto"]:
            continue
        if col.get("extra", "").startswith("on update"):
            continue
        if only is not None and name not in only:
            continue
        if col["set"] and ("__set__" + name) in form:
            # SET jako zestaw pol wyboru: odznaczone pole w ogole nie przychodzi,
            # wiec znacznik mowi, ze kolumna byla w formularzu (pusty zbior tez).
            getter = getattr(form, "getlist", None)
            picked = getter(name) if getter else ([form.get(name)] if form.get(name) else [])
            raw = ",".join(v for v in picked if v)
        elif name not in form:
            continue
        else:
            raw = form.get(name)
        old = row.get(name)
        try:
            _, new, _ = validate(col, raw)
            # Zasady gry sadza tylko to, co operator zmienia: wartosc zastana
            # w bazie, odeslana bez zmian, nie blokuje edycji innych pol.
            if not _same(old, new):
                new = column_rule(table, col, new)
        except Invalid as exc:
            errors.append(str(exc))
            continue
        if _same(old, new):
            continue
        changes.append({"column": name, "old": old, "new": new,
                        "display_old": _display(old), "display_new": _display(new),
                        "label": col["comment"] or name})
    return changes, errors


def _same(old, new):
    from decimal import Decimal, InvalidOperation
    if isinstance(old, (bytes, bytearray)):
        old = db.decode(old)
    if isinstance(new, (bytes, bytearray)):
        new = db.decode(new)
    if old is None or new is None:
        return old is new
    if isinstance(old, (int, float, Decimal)) or isinstance(new, (int, float, Decimal)):
        try:
            return Decimal(str(old)) == Decimal(str(new))
        except InvalidOperation:
            return False
    return str(old) == str(new)


def _display(value):
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return db.decode(value)
    return str(value)


# -----------------------------------------------------------------------------
#  Podglad trzymany na serwerze
# -----------------------------------------------------------------------------
def stash(payload):
    """Zapisuje podglad i zwraca token. Token jedzie do formularza, dane nie."""
    token = uuid.uuid4().hex
    now = time.time()
    with _lock:
        for key in [k for k, v in _pending.items() if now - v["ts"] > PENDING_TTL]:
            _pending.pop(key, None)
        while len(_pending) >= PENDING_MAX:
            oldest = min(_pending, key=lambda k: _pending[k]["ts"])
            _pending.pop(oldest, None)
        session = db.ns().session
        payload['owner'] = session.setdefault('_editsql_owner', uuid.uuid4().hex)
        payload["ts"] = now
        _pending[token] = payload
    return token


def take(token, keep=False):
    with _lock:
        payload = _pending.get(token)
        if payload is None:
            return None
        if time.time() - payload['ts'] > PENDING_TTL:
            _pending.pop(token, None)
            return None
        if payload.get('owner') != db.ns().session.get('_editsql_owner'):
            return None
        if not keep:
            _pending.pop(token, None)
        return payload


def stash_count():
    with _lock:
        return len(_pending)


# -----------------------------------------------------------------------------
#  Zapis
# -----------------------------------------------------------------------------
class Conflict(Exception):
    pass


# The write implementation owns all row/history locks in one transaction.
def apply_changes(*args, **kwargs):
    from .writes import apply_changes as write
    return write(*args, **kwargs)

def insert_row(*args, **kwargs):
    from .writes import insert_row as write
    return write(*args, **kwargs)

def delete_row(*args, **kwargs):
    from .writes import delete_row as write
    return write(*args, **kwargs)

def delete_rows(*args, **kwargs):
    from .writes import delete_rows as write
    return write(*args, **kwargs)

def undo(*args, **kwargs):
    from .writes import undo as write
    return write(*args, **kwargs)

# -----------------------------------------------------------------------------
#  Kanaly do gry (proto sa czytane przy starcie rdzeni)
# -----------------------------------------------------------------------------
def request_reload(admin):
    """Prosi gre o przeladowanie protosow / restart, tak jak strona /rates.

    Proto (item_proto, mob_proto, refine_proto, skill_proto, shop*) czyta bin/db
    PRZY STARCIE, a exp_table bin/game. Bez tego kroku administrator zapisalby
    dane, ktorych gra nie widzi, i uznalby edytor za zepsuty.
    """
    panel = db.ns()
    messages = []
    queued = None
    queue_and_wait = panel.get("queue_and_wait")
    if queue_and_wait is not None:
        try:
            status, qid = queue_and_wait("", "RATES", "", "", wait=0)
            queued = (status, qid)
            messages.append(T("kolejka: %s", "queue: %s") % status)
        except Exception as exc:                   # noqa: BLE001
            messages.append(T("kolejki nie udało się użyć: %s", "the queue could not be used: %s") % exc)
    script = panel.get("RATES_SCRIPT")
    import os
    import subprocess
    if script and os.path.exists(script):
        try:
            subprocess.Popen(["/bin/sh", script], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True, start_new_session=True)
            messages.append(T("restart rdzeni zlecony", "a restart of the cores was requested"))
        except Exception as exc:                   # noqa: BLE001
            messages.append(T("restartu nie udało się zlecić: %s", "the restart could not be requested: %s")
                            % exc)
    else:
        messages.append(T("brak skryptu restartu w tym środowisku - zrestartuj rdzenie ręcznie",
                          "no restart script in this environment - restart the cores by hand"))
    return queued, messages


def fingerprint(table, row):
    """Krotki odcisk wiersza - do pokazania, ze podglad dotyczy tej samej wersji."""
    blob = json.dumps({k: _display(v) for k, v in sorted(row.items())},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()[:10]
