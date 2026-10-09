# =============================================================================
#  /editsql -- strony narzedziowe.
#
#   * dashboard  -- kafelki TYLKO dla systemow, ktore w tej bazie istnieja
#                   (schema.detect), stan polaczenia, ostatnie zmiany i uczciwa
#                   lista tego, czego edytor NIE ruszy (systemy plikowe).
#   * structure  -- baza -> tabela -> kolumna: typy, NULL, default, klucze,
#                   indeksy, silnik, liczba wierszy.
#   * history    -- historia zmian z cofaniem.
#   * apply      -- co wymaga restartu rdzeni, a co dziala od razu.
#   * labels     -- nazwy typow przedmiotow, rang i typow potworow.
# =============================================================================

from . import db, editor, fields, i18n, labels, render, safety, schema
from .i18n import P, T, tr

# Co wymaga czego, zeby zmiana dotarla do gry. Zebrane z analizy binarek:
# PROTO_FROM_DB=1 (bin/db czyta protosy przy starcie), exp_table czyta bin/game
# przy starcie, flagi w player.quest dzialaja od razu.
RESTART_TABLES = {
    "world": ("item_proto", "mob_proto", "refine_proto", "item_attr", "item_attr_rare",
              "skill_proto", "shop", "shop_item", "shop_special", "shop_special_proto",
              "object_proto", "crafting_proto", "quest_reward_proto", "banword",
              "land", "offlineshop_limit", "name_reservation"),
    "common": ("exp_table", "locale", "itemshop_items", "gmlist"),
}
LIVE_TABLES = {
    "player": ("quest", "web_admin_rates", "web_admin_queue"),
    "common": ("priv_settings",),
}
IGNORED_TABLES = {
    "world": ("etc_drop_item", "locale_point"),
    "common": ("m2_switches", "m2_itemshop_price_base", "itemshop_time_auctions"),
    "itemshop": (),
}


def _effect(db_name, table_name):
    if table_name in RESTART_TABLES.get(db_name, ()):
        return ("restart", T("zmiana zadziała po restarcie rdzeni (dane czyta bin/db przy "
                             "starcie) - po zapisaniu wszystkich zmian wejdź w „Zastosuj”.",
                             "the change takes effect after a restart of the cores (bin/db reads "
                             "the data when it starts) - once every change is saved, go to "
                             "“Apply”."))
    if table_name in LIVE_TABLES.get(db_name, ()):
        return ("live", T("zmiana działa od razu.", "the change takes effect at once."))
    if table_name in IGNORED_TABLES.get(db_name, ()):
        return ("ignored", T("żaden rdzeń nie czyta tej tabeli - zapis nie zmieni gry.",
                             "no core reads this table - a save will not change the game."))
    return ("unknown", T("efekt w grze nie jest potwierdzony dla tej tabeli.",
                         "the effect in the game is not confirmed for this table."))


def effect_html(db_name, table_name):
    kind, text = _effect(db_name, table_name)
    klass = {"restart": "esq-note-info", "live": "esq-note-ok",
             "ignored": "esq-note-warn"}.get(kind, "esq-note-info")
    link = ((' <a href="/editsql/apply">%s</a>' % render._esc(T("Przejdź do „Zastosuj”",
                                                               "Go to “Apply”")))
            if kind == "restart" else "")
    html = ('<div class="esq-note %s"><b>%s</b> %s%s</div>'
            % (klass, render._esc(T("Efekt w grze:", "Effect in the game:")), render._esc(text), link))
    if table_name in CLIENT_TABLES.get(db_name, ()):
        html += client_note_html()
    return html


# The game client reads these two from its own pack/gamedata, never from the
# server (launcher report 7b1bc872 and Kordyl13, 7 October): the panel's
# /client-data builds the client's copy from them (client_protos.py). Only the
# mt2009 line has a world database, so only there do these pages exist.
CLIENT_TABLES = {"world": ("item_proto", "mob_proto")}


def client_note_html():
    return ('<div class="esq-note esq-note-warn"><b>%s</b> %s <a href="/client-data">%s</a></div>'
            % (render._esc(T("Klient gry:", "The game client:")),
               render._esc(T("klient ma własną kopię tej tabeli (pack\\gamedata) i pokaże zmianę - opis "
                             "przedmiotu, cenę u NPC, poziom potwora - dopiero po synchronizacji: w launcherze "
                             "OTWÓRZ PANEL WWW → „Synchronizuj dane przedmiotów z klientem”, a dla znajomego "
                             "albo klienta na VPS paczka do pobrania.",
                             "the client keeps its own copy of this table (pack\\gamedata) and shows the "
                             "change - the item's tooltip, its NPC price, a monster's level - only after a "
                             "sync: in the launcher OPEN WEB PANEL → “Synchronize item data to the client”, "
                             "and for a friend or a client on a VPS a package to download.")),
               render._esc(T("Dane dla klienta", "Client data"))))


# -----------------------------------------------------------------------------
#  Dashboard
# -----------------------------------------------------------------------------
def dashboard(messages_list=()):
    alive, version = db.server_alive()
    found = {}
    load_error = None
    if alive:
        try:
            found = schema.detect()
        except Exception as exc:                   # noqa: BLE001
            load_error = str(exc)
    if isinstance(version, (bytes, bytearray)):
        version = db.decode(version)

    counts = {}
    for key, (db_name, table_name) in (("items", ("world", "item_proto")),
                                       ("mobs", ("world", "mob_proto")),
                                       ("refine", ("world", "refine_proto")),
                                       ("bonuses", ("world", "item_attr")),
                                       ("shops", ("world", "shop")),
                                       ("exp", ("common", "exp_table")),
                                       ("spawns", ("world", "land")),
                                       ("skills", ("world", "skill_proto")),
                                       ("crafting", ("world", "crafting_proto")),
                                       ("quests", ("world", "quest_reward_proto")),
                                       ("itemshop", ("common", "itemshop_items")),
                                       ("gm", ("common", "gmlist"))):
        table = schema.table(db_name, table_name) if alive else None
        if table is not None:
            try:
                counts[key] = schema.count_rows(db_name, table_name) \
                    if table["rows_estimate"] < 200000 else table["rows_estimate"]
            except Exception:                      # noqa: BLE001
                counts[key] = table["rows_estimate"]

    groups = []
    for group_title, ids in render.NAV_GROUPS:
        tiles = []
        for key, icon, title, hint in render.MODULES:
            if key not in ids or key not in found:
                continue
            count = counts.get(key)
            tiles.append('<a class="esq-tile" href="/editsql/%s"><span class="esq-tile-icon">%s</span>'
                         '<span class="esq-tile-title">%s%s</span>'
                         '<span class="esq-tile-hint">%s</span></a>'
                         % (render._esc(key), icon, render._esc(title),
                            ('<span class="esq-tile-count">%s</span>' % render.num(count))
                            if count is not None else "", render._esc(hint)))
        if tiles:
            groups.append('<h3 class="esq-group-title">%s</h3><div class="esq-tiles">%s</div>'
                          % (render._esc(group_title), "".join(tiles)))

    body = []
    if not alive:
        body.append('<div class="esq-note esq-note-warn">%s</div>'
                    % (T("Baza nie odpowiada: %s", "The database does not answer: %s")
                       % render._esc(version)))
    elif load_error:
        body.append('<div class="esq-note esq-note-warn">%s</div>'
                    % (T("Nie udało się odczytać struktury bazy: %s",
                         "Could not read the database's structure: %s") % render._esc(load_error)))
    else:
        body.append('<p class="esq-lead">%s</p>'
                    % (T('Połączono z <b>%s</b>. Wybierz, co chcesz zmienić - każdy zapis pokazuje '
                         'najpierw podgląd zmian i trafia do historii, z której można go cofnąć.',
                         'Connected to <b>%s</b>. Pick what you want to change - every save shows '
                         'a preview of the changes first and goes into the history, where it can '
                         'be undone.') % render._esc(version)))
    body.extend(groups)
    body.append(_recent_changes())
    body.append('<div class="esq-note esq-note-info">%s</div>' % T(
        '<b>Skrzynki i drop:</b> zawartość skrzynek '
        '(special_item_group.txt) i grup dropu (mob_drop_item.txt) zmienisz w osobnym edytorze '
        '<a href="/drops">„Skrzynki i drop”</a> panelu. <b>Czego ten edytor nie zmieni:</b> '
        'spawnów potworów (regen.txt, npc.txt), receptur Cube (cube.txt) i nazw map - te dane '
        'są w plikach serwera, do których panel nie ma dostępu.',
        '<b>Chests and drops:</b> what the chests hold (special_item_group.txt) and the drop '
        'groups (mob_drop_item.txt) are changed in the panel\'s separate '
        '<a href="/drops">“Chests and drops”</a> editor. <b>What this editor does not '
        'change:</b> monster spawns (regen.txt, npc.txt), Cube recipes (cube.txt) and map names - '
        'that data is in the server\'s files, which the panel cannot reach.'))
    return render.page(T("Edytor bazy danych", "Database editor"), "".join(body), active=None,
                       found=found, messages_list=messages_list,
                       side=render.side_help(T("Jak to działa", "How it works"), (
                           T("Zmiany idą do tej samej bazy, z której gra czyta dane.",
                             "Changes go to the same database the game reads its data from."),
                           T("Przedmioty, potwory, ulepszenia, bonusy i sklepy rdzeń czyta przy "
                             "starcie - po zapisaniu zmian wejdź w „Zastosuj” i zrestartuj rdzenie.",
                             "The cores read items, monsters, refining, bonuses and shops when "
                             "they start - once your changes are saved, go to “Apply” "
                             "and restart the cores."),
                           T("Każda zmiana trafia do historii (z kopią tabeli z danego dnia), więc "
                             "można ją cofnąć.",
                             "Every change goes into the history (with a copy of the table from "
                             "that day), so it can be undone."))))


def _recent_changes(limit=6):
    try:
        rows = db.history_rows(limit=limit)
    except Exception:                              # noqa: BLE001
        return ""
    if not rows:
        return ""
    body = []
    for row in rows:
        row = _decoded(row)
        body.append(("", [render._esc(_ts(row.get("ts"))), render._esc(row.get("admin")),
                          render._esc("%s.%s" % (row.get("db_name"), row.get("table_name"))),
                          render._esc(_pk_text(row.get("pk_json"))),
                          render._esc(fields.label(row.get("db_name"), row.get("table_name"),
                                                   row.get("column_name")))]))
    return render.box(T("Ostatnie zmiany", "Latest changes"),
                      render.table([T("Kiedy", "When"), T("Kto", "Who"), T("Tabela", "Table"),
                                    T("Wiersz", "Row"), T("Pole", "Field")], body)
                      + '<p class="esq-more"><a href="/editsql/history">%s &rarr;</a></p>'
                      % render._esc(T("Cała historia", "The whole history")))


# -----------------------------------------------------------------------------
#  Struktura bazy
# -----------------------------------------------------------------------------
def _size_text(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return ("%.1f %s" % (value, unit)) if unit != "B" else ("%d B" % value)
        value /= 1024.0
    return "-"


def structure_page(db_name=None, table_name=None):
    body = []
    structure = T("Struktura bazy", "Database structure")
    crumbs = [(structure, "/editsql/structure")]
    title = structure
    yes, no = T("tak", "yes"), T("nie", "no")
    if db_name and table_name:
        table = schema.table(db_name, table_name)
        if table is None:
            return render.page(structure,
                               '<div class="esq-note esq-note-warn">%s</div>'
                               % (T("Nie ma tabeli %s.%s.", "There is no table %s.%s.")
                                  % (render._esc(db_name), render._esc(table_name))),
                               active="structure")
        title = "%s.%s" % (db_name, table_name)
        crumbs += [(db_name, "/editsql/structure/%s" % db_name), (table_name, None)]
        module_id = _module_for(db_name, table_name)
        body.append('<div class="esq-facts">%s %s %s %s%s</div>' % (
            render.badge(T("widok", "view") if table["type"] == "VIEW" else T("tabela", "table")),
            render.badge(table["engine"] or "-"), render.badge(table["collation"] or "-"),
            render.badge(T("klucz: ", "key: ") + (", ".join(table["pk"]) if table["pk"]
                                                  else T("brak", "none")),
                         "ok" if table["pk"] else "bad"),
            (' <a class="esq-btn esq-btn-small esq-btn-go" href="/editsql/%s">%s</a>'
             % (render._esc(module_id), render._esc(T("Edytuj dane", "Edit the data"))))
            if module_id else ""))
        body.append(render.notes_html(db_name, table_name))
        body.append(effect_html(db_name, table_name))
        columns = []
        for col in table["columns"]:
            marks = []
            if col["name"] in table["pk"]:
                marks.append(render.badge("PK", "ok"))
            for unique in table["unique"]:
                if col["name"] in unique["columns"]:
                    marks.append(render.badge("UQ"))
            if any(i["column"] == col["name"] and i["name"] != "PRIMARY" and not i["unique"]
                   for i in table["indexes"]):
                marks.append(render.badge("IX"))
            label = fields.label(db_name, table_name, col["name"])
            columns.append(("", [
                ("esq-c-num", render._esc(col["pos"])),
                '<b>%s</b>%s' % (render._esc(col["name"]),
                                 ('<br /><span class="esq-dim">%s</span>' % render._esc(label))
                                 if label != col["name"] else ""),
                '<code>%s</code>' % render._esc(col["type"]),
                yes if col["nullable"] else no,
                render._esc("" if col["default"] is None else col["default"]),
                " ".join(marks),
                render._esc(col["charset"] or ""),
                render._esc(col["comment"] or "")]))
        body.append(render.box(T("Kolumny (%d)", "Columns (%d)") % len(table["columns"]),
                               render.table(["#", T("Kolumna", "Column"), T("Typ", "Type"), "NULL",
                                             T("Domyślnie", "Default"), T("Klucze", "Keys"),
                                             T("Kodowanie", "Encoding"), T("Komentarz", "Comment")],
                                            columns)))
        indexes = [i for i in table["indexes"] if i["name"] != "PRIMARY"]
        if indexes:
            rows = [("", [render._esc(i["name"]), render._esc(i["column"]),
                          ("esq-c-num", render._esc(i["seq"])), yes if i["unique"] else no,
                          render._esc(i["type"])]) for i in indexes[:80]]
            body.append(render.box(T("Indeksy", "Indexes"), render.table(
                [T("Nazwa", "Name"), T("Kolumna", "Column"), T("Pozycja", "Position"),
                 T("Unikalny", "Unique"), T("Typ", "Type")], rows)))
        relations = schema.relations_for(db_name, table_name)
        if relations:
            rows = []
            for column_name, rel in sorted(relations.items()):
                target = "%s.%s.%s" % (rel["to_db"], rel["to_table"], rel["to_column"])
                rows.append(("", [render._esc(column_name),
                                  '<a href="/editsql/structure/%s/%s">%s</a>'
                                  % (render._esc(rel["to_db"]), render._esc(rel["to_table"]),
                                     render._esc(target)),
                                  render._esc(rel["label"]),
                                  render.status_badge(schema.relation_ok(rel), T("jest", "present"),
                                                      T("brak", "missing"))]))
            body.append(render.box(T("Powiązania", "Relations"), render.table(
                [T("Kolumna", "Column"), T("Wskazuje na", "Points at"), T("Znaczenie", "Meaning"),
                 T("Tabela docelowa", "Target table")], rows),
                T("Baza nie ma kluczy obcych - te powiązania zna edytor.",
                  "The database has no foreign keys - the editor knows these relations itself.")))
        if table["rows_estimate"] < 200000:
            try:
                count = schema.count_rows(db_name, table_name)
                body.append('<p class="esq-hint">%s</p>'
                            % (T("Liczba wierszy: <b>%s</b>.", "Rows: <b>%s</b>.") % render.num(count)))
            except Exception:                      # noqa: BLE001
                pass
    else:
        selected_dbs = [db_name] if db_name else sorted(schema.dbs())
        if db_name:
            title = T("Baza %s", "Database %s") % db_name
            crumbs.append((db_name, None))
        for name in selected_dbs:
            tables = sorted((t for (database, _n), t in schema.tables().items() if database == name),
                            key=lambda t: t["name"])
            if not tables:
                continue
            if db_name:
                rows = [("", ['<a href="/editsql/structure/%s/%s">%s</a>'
                              % (render._esc(name), render._esc(t["name"]), render._esc(t["name"])),
                              ("esq-c-num", render.num(t["rows_estimate"])),
                              ("esq-c-num", render._esc(len(t["columns"]))),
                              render._esc(_size_text(t["data_length"])),
                              render._esc(t["engine"] or (T("widok", "view") if t["type"] == "VIEW"
                                                          else "-")),
                              render.status_badge(bool(t["pk"]), yes, T("brak", "none")),
                              ('<a href="/editsql/%s">%s</a>'
                               % (_module_for(name, t["name"]), render._esc(T("edytuj", "edit"))))
                              if _module_for(name, t["name"]) else ""])
                        for t in tables]
                body.append(render.box(T("Tabele (%d)", "Tables (%d)") % len(tables), render.table(
                    [T("Tabela", "Table"), T("Wierszy (ok.)", "Rows (approx.)"), T("Kolumn", "Columns"),
                     T("Dane", "Data"), T("Silnik", "Engine"), T("Klucz", "Key"), ""], rows)))
        if not db_name:
            rows = []
            for name in selected_dbs:
                tables = [t for (database, _n), t in schema.tables().items() if database == name]
                if not tables:
                    continue
                rows.append(("", ['<a href="/editsql/structure/%s">%s</a>'
                                  % (render._esc(name), render._esc(name)),
                                  ("esq-c-num", render._esc(len(tables))),
                                  render._esc(_size_text(sum(t["data_length"] for t in tables))),
                                  render._esc(", ".join(sorted({t["engine"] or T("widok", "view")
                                                                for t in tables}))),
                                  ("esq-c-num", render._esc(sum(1 for t in tables if not t["pk"])))]))
            body.append('<p class="esq-lead">%s</p>'
                        % render._esc(T("Struktura jest czytana na żywo z information_schema "
                                        "- nic nie jest wpisane na sztywno.",
                                        "The structure is read live from information_schema "
                                        "- nothing is written in by hand.")))
            body.append(render.box(T("Bazy", "Databases"), render.table(
                [T("Baza", "Database"), T("Tabel", "Tables"), T("Dane", "Data"),
                 T("Silniki", "Engines"), T("Bez klucza głównego", "Without a primary key")], rows)))
    return render.page(title, "".join(body), active="structure", crumbs=crumbs,
                       found=schema.detect() if _model_ok() else {})


def _model_ok():
    try:
        schema.load()
        return True
    except Exception:                              # noqa: BLE001
        return False


def _module_for(db_name, table_name):
    for key in ("items", "mobs", "refine", "bonuses", "shops", "spawns", "skills", "exp",
                "crafting", "quests", "itemshop", "gm"):
        spec = editor.MODULES.get(key)
        if spec and spec["db"] == db_name and spec["table"] == table_name:
            return key
    return None


# -----------------------------------------------------------------------------
#  Historia zmian
# -----------------------------------------------------------------------------
# The operation's word in the history. admin_panel.py adds the chest and drop
# editor's own (drop_*), as pairs too.
_OPS = {"update": P("zmiana", "change"), "insert": P("dodanie", "addition"),
        "delete": P("usunięcie", "removal"), "undo": P("cofnięcie", "undo")}


def _decoded(row):
    """Wiersz historii: bajty -> tekst (tabela historii jest w utf8mb4)."""
    return {key: (db.decode(value, "utf8mb4") if isinstance(value, (bytes, bytearray)) else value)
            for key, value in row.items()}


def _ts(value):
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        return str(value or "")


def _pk_text(pk_json):
    import json
    try:
        data = json.loads(pk_json or "{}")
    except ValueError:
        return pk_json or ""
    return ", ".join("%s %s" % (k, v) for k, v in data.items())


def _row_link(row):
    import json
    try:
        data = json.loads(row.get("pk_json") or "{}")
    except ValueError:
        return None
    module_id = _module_for(row.get("db_name"), row.get("table_name"))
    if not module_id or row.get("operation") in ("insert", "delete"):
        if row.get("table_name") == "shop_item" and "shop_vnum" in data:
            return "/editsql/shops/world/%s" % data["shop_vnum"]
        # Dodany przepis ma swoja strone, dopoki dodanie nie zostalo cofniete.
        if (module_id == "crafting" and row.get("operation") == "insert"
                and not row.get("undone") and "vnum" in data):
            return "/editsql/crafting/%s/%s" % (row.get("db_name"), data["vnum"])
        # So does an added ItemShop offer.
        if (module_id == "itemshop" and row.get("operation") == "insert"
                and not row.get("undone") and "index" in data):
            return "/editsql/itemshop/%s/%s" % (row.get("db_name"), data["index"])
        return None
    spec = editor.module_spec(module_id)
    if not spec or not spec.get("available"):
        return None
    keys = spec.get("key") or ()
    if not keys or any(k not in data for k in keys):
        return None
    return "/editsql/%s/%s/%s" % (module_id, spec["db"], "/".join(str(data[k]) for k in keys))


def history_page(page_no=1, per_page=50, messages_list=(), table_filter=""):
    try:
        db_name, table_name = (table_filter.split(".", 1) + [None])[:2] if table_filter else (None, None)
        total = db.history_count(db_name, table_name)
        pages = max(1, (total + per_page - 1) // per_page)
        page_no = min(page_no, pages)
        rows = [_decoded(r) for r in db.history_rows(limit=per_page, offset=(page_no - 1) * per_page,
                                                     db_name=db_name, table=table_name)]
    except Exception as exc:                       # noqa: BLE001
        return render.page(T("Historia zmian", "Change history"),
                           '<div class="esq-note esq-note-warn">%s</div>'
                           % (T("Nie mogę czytać historii: %s", "Cannot read the history: %s")
                              % render._esc(exc)), active="history",
                           messages_list=messages_list)
    body = []
    if not rows:
        body.append('<p class="esq-empty">%s</p>'
                    % render._esc(T("Historia jest pusta - pojawi się tu każda zmiana zapisana "
                                    "w edytorze.",
                                    "The history is empty - every change saved in the editor "
                                    "will show here.")))
    else:
        table_rows = []
        # Dodanie albo usuniecie przepisow jest jedna operacja: jedno "Cofnij"
        # cofa wszystkie wiersze z tej samej transakcji (writes._undo_whole_rows);
        # ItemShop offers too.
        whole = ("crafting_proto", "itemshop_items")
        try:
            groups = db.history_open_groups(
                [r.get("txid") for r in rows if r.get("table_name") in whole
                 and r.get("operation") in ("insert", "delete") and not r.get("undone")])
        except Exception:                          # noqa: BLE001
            groups = {}
        for row in rows:
            undo_form = ""
            op = row.get("operation")
            undoable = op in ("update",) or (op in ("insert", "delete")
                                             and row.get("table_name") in ("shop_item",) + whole)
            if not row.get("undone") and undoable:
                together = (groups.get(row.get("txid"), 1)
                            if row.get("table_name") in whole else 1)
                label, question = T("Cofnij", "Undo"), T("Cofnąć tę zmianę?", "Undo this change?")
                if together > 1:
                    label = T("Cofnij razem (%d)", "Undo together (%d)") % together
                    question = (T("Cofnąć całą operację? Cofnięcie obejmie razem wszystkie "
                                  "wiersze z tej samej operacji (%d).",
                                  "Undo the whole operation? The undo takes every row of "
                                  "that operation together (%d).") % together)
                undo_form = ('<form method="post" action="/editsql/history" class="esq-inline-form">%s'
                             '<input type="hidden" name="action" value="undo" />'
                             '<input type="hidden" name="id" value="%s" />'
                             '<button class="esq-btn esq-btn-small" type="submit" '
                             'data-confirm="%s">%s</button></form>'
                             % (render.csrf_input(), render._esc(row["id"]), render._esc(question),
                                render._esc(label)))
            elif row.get("undone"):
                undo_form = render.badge(T("cofnięte", "undone"))
            link = _row_link(row)
            where = render._esc(_pk_text(row.get("pk_json")))
            if link:
                where = '<a href="%s">%s</a>' % (render._esc(link), where)
            label = fields.label(row.get("db_name"), row.get("table_name"), row.get("column_name"))
            table_rows.append(("", [
                ("esq-c-nowrap", render._esc(_ts(row.get("ts")))),
                render._esc(row.get("admin") or ""),
                render._esc("%s.%s" % (row.get("db_name"), row.get("table_name"))),
                where,
                '%s<br /><code class="esq-col">%s</code>' % (render._esc(label),
                                                             render._esc(row.get("column_name"))),
                '<code class="esq-old">%s</code>' % render._esc(_value_text(row, "old_value")),
                '<code class="esq-new">%s</code>' % render._esc(_value_text(row, "new_value")),
                render.badge(_OPS.get(op, op or "?")),
                ("esq-c-act", undo_form)]))
        body.append(render.table([T("Kiedy", "When"), T("Kto", "Who"), T("Tabela", "Table"),
                                  T("Wiersz", "Row"), T("Pole", "Field"), T("Było", "Was"),
                                  T("Jest", "Now"), T("Operacja", "Operation"), ""],
                                 table_rows, klass="esq-table esq-history"))
        body.append(render.pager("/editsql/history", page_no, per_page, total,
                                 extra=("t=%s&" % render._esc(table_filter)) if table_filter else ""))
    return render.page(T("Historia zmian", "Change history"), "".join(body), active="history",
                       messages_list=messages_list,
                       side=render.side_help(T("Cofanie", "Undo"), (
                           T("Cofnięcie działa tylko wtedy, gdy nikt nie zmienił tej wartości "
                             "później - inaczej nadpisałoby cudzą pracę.",
                             "An undo works only while nobody has changed the value since - "
                             "otherwise it would overwrite someone else's work."),
                           T("Każde cofnięcie też trafia do historii.",
                             "Every undo goes into the history too."),
                           T("Przed pierwszą zmianą tabeli danego dnia edytor robi jej kopię "
                             "(<tabela>_editsql_<data>).",
                             "Before a table's first change of the day the editor makes a copy "
                             "of it (<table>_editsql_<date>)."))))


def _value_text(row, key):
    """Wartosc we wpisie historii; caly wiersz (JSON) jako "kolumna wartosc · ..."."""
    value = row.get(key)
    if value is None:
        return ""
    if row.get("column_name") == safety.ROW_COLUMN:
        import json
        try:
            data = json.loads(value)
            return " · ".join("%s %s" % (k, "NULL" if v is None else v) for k, v in data.items())
        except (ValueError, AttributeError):
            return value
    return value


def history_undo(entry_id):
    return safety.undo(entry_id, _admin_name())


# -----------------------------------------------------------------------------
#  Zastosuj
# -----------------------------------------------------------------------------
def apply_page(messages_list=(), result=None):
    body = []
    queue = schema.table("player", "web_admin_queue")
    pending, recent = 0, []
    try:
        if queue is None:
            raise RuntimeError(T("brak tabeli player.web_admin_queue",
                                 "there is no player.web_admin_queue table"))
        pending = int(db.scalar(
            "SELECT COUNT(*) AS n FROM %s WHERE %s='pending'"
            % (db.qt(queue["db"], queue["name"]), db.qi("status")), None, 0) or 0)
        columns = [name for name in ("id", "player_name", "cmd", "status", "created")
                   if name in queue["by_name"]]
        recent = [safety.decode_row(queue, r) for r in db.query(
            "SELECT %s FROM %s ORDER BY %s DESC LIMIT 10"
            % (", ".join(db.qi(name) for name in columns),
               db.qt(queue["db"], queue["name"]), db.qi("id")))]
    except Exception as exc:                       # noqa: BLE001
        body.append('<div class="esq-note esq-note-warn">%s</div>'
                    % (T("Nie mogę czytać kolejki poleceń: %s", "Cannot read the command queue: %s")
                       % render._esc(exc)))
    body.append('<p class="esq-lead">%s</p>'
                % render._esc(T("Zapis w edytorze trafia do bazy od razu. To, kiedy zobaczy "
                                "go gra, zależy od tabeli:",
                                "A save in the editor reaches the database at once. When the game "
                                "sees it depends on the table:")))
    rows = []
    for db_name, names in sorted(RESTART_TABLES.items()):
        rows.append(("", [render.badge(T("po restarcie rdzeni", "after a restart of the cores")),
                          render._esc(db_name), render._esc(", ".join(names))]))
    for db_name, names in sorted(LIVE_TABLES.items()):
        rows.append(("", [render.badge(T("od razu", "at once"), "ok"), render._esc(db_name),
                          render._esc(", ".join(names))]))
    for db_name, names in sorted(IGNORED_TABLES.items()):
        if names:
            rows.append(("", [render.badge(T("nie wpływa na grę", "does not affect the game"), "bad"),
                              render._esc(db_name), render._esc(", ".join(names))]))
    body.append(render.table([T("Kiedy działa", "When it takes effect"), T("Baza", "Database"),
                              T("Tabele", "Tables")], rows))
    if result:
        body.append('<div class="esq-note esq-note-info">%s</div>' % render._esc(" · ".join(result)))
    body.append('<div id="register"><form method="post" action="/editsql/apply" '
                'data-confirm="%s">%s'
                '<div class="esq-note esq-note-warn">%s</div>%s</form></div>'
                % (render._esc(T("Zrestartować rdzenie gry? Gracze w grze zostaną na chwilę rozłączeni.",
                                 "Restart the game's cores? Players in the game will be disconnected "
                                 "for a moment.")),
                   render.csrf_input(),
                   render._esc(T("Restart rdzeni przerywa grę na chwilę. Użyj go po zakończeniu zmian "
                                 "w przedmiotach, potworach, ulepszeniach, bonusach, sklepach "
                                 "i tabeli doświadczenia.",
                                 "A restart of the cores interrupts the game for a moment. Use it once "
                                 "you have finished changing items, monsters, refining, bonuses, "
                                 "shops and the experience table.")),
                   render.actions(((T("Zastosuj: przeładuj i zrestartuj rdzenie",
                                      "Apply: reload and restart the cores"), "primary",
                                    'name="action" value="reload"'),))))
    body.append('<p class="esq-hint">%s</p>'
                % (T("Oczekujących poleceń w kolejce: <b>%s</b>.",
                     "Commands waiting in the queue: <b>%s</b>.") % render._esc(pending)))
    if recent:
        rows = [("", [("esq-c-num", render._esc(r.get("id"))), render._esc(r.get("player_name")),
                      '<code>%s</code>' % render._esc(r.get("cmd")),
                      render.badge(str(r.get("status") or "")),
                      ("esq-c-nowrap", render._esc(_ts(r.get("created")))) ]) for r in recent]
        body.append(render.box(T("Ostatnie polecenia w kolejce", "Latest commands in the queue"),
                               render.table(["ID", T("Postać", "Character"), T("Polecenie", "Command"),
                                             "Status", T("Kiedy", "When")], rows)))
    return render.page(T("Zastosuj zmiany", "Apply changes"), "".join(body), active="apply",
                       messages_list=messages_list,
                       side=render.side_help(T("Dlaczego restart", "Why a restart"), (
                           T("bin/db czyta przedmioty, potwory, ulepszenia i sklepy z bazy przy starcie.",
                             "bin/db reads items, monsters, refining and shops from the database "
                             "when it starts."),
                           T("bin/game czyta tabelę doświadczenia też przy starcie.",
                             "bin/game reads the experience table when it starts too."),
                           T("Mnożniki z panelu (player.quest) działają od razu.",
                             "The panel's rates (player.quest) take effect at once."))))


def apply_now():
    _queued, messages = safety.request_reload(_admin_name())
    return messages


# -----------------------------------------------------------------------------
#  Etykiety typow i rang
# -----------------------------------------------------------------------------
def _labels_table(kind, hints, form_prefix, extra_head=(), extra_cols=None):
    rows = []
    for value in sorted(hints):
        info = hints[value]
        default = labels.default_label(kind, value)
        cells = [("esq-c-num", render._esc(value)),
                 '<input form="labelsForm" type="text" class="esq-input" name="label_%s_%s" '
                 'value="%s" placeholder="%s" maxlength="96" />'
                 % (form_prefix, render._esc(value), render._esc(labels.label(kind, value)),
                    render._esc(default or T("nazwa", "name"))),
                 render._esc(default or "—"),
                 ("esq-c-num", render.num(info.get("count")))]
        if extra_cols:
            cells.extend(extra_cols(info))
        cells.append(render._esc(", ".join(labels.shown_examples(info, 3))))
        rows.append(("", cells))
    return render.table([T("Numer", "Number"), T("Twoja nazwa", "Your name"),
                         T("Domyślnie", "Default"), T("Ile", "How many")] + list(extra_head)
                        + [T("Przykłady", "Examples")],
                        rows, klass="esq-table esq-labels")


def labels_page(messages_list=()):
    body = ['<p class="esq-lead">%s</p>' % render._esc(T(
        "Typy przedmiotów, rangi i typy potworów są w bazie liczbami. "
        "Edytor zna ich standardowe nazwy z silnika Metin2 (kolumna „Domyślnie”), a tutaj "
        "możesz nadać własne - pojawią się wszędzie w edytorze. Puste pole = nazwa domyślna.",
        "Item types, monster ranks and monster types are numbers in the database. The editor "
        "knows their standard names from the Metin2 engine (the “Default” column), and "
        "here you can give your own - they show everywhere in the editor. An empty field = the "
        "default name."))]
    item_types = labels.item_type_hints()
    if item_types:
        body.append(render.box(T("Typy przedmiotów", "Item types"),
                               _labels_table(labels.KIND_ITEM_TYPE, item_types, labels.KIND_ITEM_TYPE)))
    ranks = labels.mob_rank_hints()
    if ranks:
        body.append(render.box(T("Rangi potworów", "Monster ranks"),
                               _labels_table(labels.KIND_MOB_RANK, ranks, labels.KIND_MOB_RANK,
                                             (T("Śr. PŻ", "Avg. HP"),),
                                             lambda info: [("esq-c-num", render.num(info.get("avg_hp") or 0))])))
    mob_types = labels.mob_type_hints()
    if mob_types:
        body.append(render.box(T("Typy potworów", "Monster types"),
                               _labels_table(labels.KIND_MOB_TYPE, mob_types, labels.KIND_MOB_TYPE)))
    if item_types or ranks or mob_types:
        body.append('<div id="register"><form id="labelsForm" method="post" action="/editsql/labels">%s'
                    '<input type="hidden" name="action" value="save_all" />%s</form></div>'
                    % (render.csrf_input(), render.actions(((T("Zapisz nazwy", "Save the names"),
                                                             "primary", ""),), sticky=True)))
    return render.page(T("Etykiety", "Labels"), "".join(body), active="labels",
                       messages_list=messages_list)


def labels_save_all(form):
    """Zapisuje nadane nazwy (pola label_<kind>_<numer>) - tylko te, ktore sie zmienily."""
    saved = 0
    kinds = (labels.KIND_ITEM_TYPE, labels.KIND_MOB_RANK, labels.KIND_MOB_TYPE)
    for field_name, value in (form or {}).items():
        if not field_name.startswith("label_"):
            continue
        rest = field_name[len("label_"):]
        for kind in kinds:
            prefix = kind + "_"
            if rest.startswith(prefix):
                key = rest[len(prefix):]
                if not key.lstrip("-").isdigit():
                    break
                new = (value or "").strip()
                if new != labels.label(kind, key):
                    labels.save(kind, key, new, labels.note(kind, key))
                    saved += 1
                break
    labels.invalidate()
    return saved


# -----------------------------------------------------------------------------
#  Wspolne
# -----------------------------------------------------------------------------
def _admin_name():
    panel = db.ns()
    try:
        session = panel.session
        name = session.get("player") or ("lokalny" if panel.local_open() else "admin")
    except Exception:                              # noqa: BLE001
        name = "admin"
    return str(name)
