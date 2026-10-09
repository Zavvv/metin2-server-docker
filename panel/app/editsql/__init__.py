# =============================================================================
#  /editsql -- rejestracja tras.
#
#  Modul jest dolaczany tak samo jak strona glowna: admin_panel.py na samym
#  koncu wola editsql.init(globals()). Nie ma tu importu Flaska - obiekty
#  (app, request, redirect, login_required, csrf_token, lang) bierzemy z
#  namespace'u panelu. Dzieki temu:
#
#   * pakiet da sie zaimportowac i przetestowac bez Flaska (patrz tests/),
#   * autoryzacja i CSRF sa DOKLADNIE te same co w reszcie panelu - globalny
#     before_request panelu sprawdza kazdy POST, a login_required pilnuje
#     kazdej trasy, takze gdy ktos wpisze /editsql recznie.
#
#  Przeplyw zapisu (zgodnie z raportem):
#      GET  /editsql/<modul>/<db>/<klucz>          -- odczyt i formularz
#      POST /editsql/<modul>/<db>/<klucz>  preview -- walidacja + zapis podgladu
#      GET  /editsql/<modul>/<db>/<klucz>?preview= -- ekran potwierdzenia
#      POST /editsql/<modul>/<db>/<klucz>  save    -- transakcja + audyt
# =============================================================================

from . import db, editor, i18n, labels, modules, pages, render, safety, schema  # noqa: F401
from .i18n import P, T, tr

# Rejestr endpointow - potrzebny, zeby init() mozna bylo wywolac dwa razy
# (np. w testach) bez dublowania tras.
_registered = {"done": False}


# -----------------------------------------------------------------------------
#  Komunikaty (sesja panelu, bez zaleznosci od flask.flash)
# -----------------------------------------------------------------------------
def _put_message(kind, text):
    session = db.ns().session
    queue = session.get("editsql_msgs") or []
    queue.append([kind, text])
    session["editsql_msgs"] = queue[-12:]


def _take_messages():
    session = db.ns().session
    queue = session.get("editsql_msgs") or []
    session["editsql_msgs"] = []
    return [(kind, text) for kind, text in queue]


def _redirect(path):
    return db.ns().redirect(path)


# -----------------------------------------------------------------------------
#  Trasy
# -----------------------------------------------------------------------------
def _home():
    try:
        schema.load()
    except Exception as exc:                       # noqa: BLE001
        return render.page(T("Edytor bazy danych", "Database editor"),
                           '<div class="esq-note esq-note-warn">%s</div>'
                           % (T("Nie mogę zbudować modelu bazy: %s",
                                "Cannot build the database's model: %s") % render._esc(exc)),
                           messages_list=_take_messages(), found={})
    return pages.dashboard(messages_list=_take_messages())


def _structure(db_name=None, table_name=None):
    return pages.structure_page(db_name, table_name)


def _history():
    panel = db.ns()
    request = panel.request
    if str(request.method).upper() == "POST":
        if (request.form.get("action") or "") == "undo":
            entry_id = request.form.get("id") or "0"
            try:
                ok, message = pages.history_undo(int(entry_id))
            except (TypeError, ValueError):
                ok, message = False, T("niepoprawny numer wpisu", "invalid entry number")
            except Exception as exc:
                ok, message = False, i18n.bilingual(
                    "Nie cofnięto zmiany / Change was not undone: %s" % exc,
                    "Change was not undone: %s" % exc)
            if ok:
                render.invalidate_names()
            _put_message("ok" if ok else "error", message)
        return _redirect("/editsql/history")
    try:
        page_no = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page_no = 1
    return pages.history_page(page_no=page_no, messages_list=_take_messages(),
                              table_filter=request.args.get("t") or "")


def _apply():
    panel = db.ns()
    request = panel.request
    if str(request.method).upper() == "POST":
        if (request.form.get("action") or "") == "reload":
            try:
                result = pages.apply_now()
                _put_message("ok", T("Zlecono przeładowanie: ", "Reload requested: ") + " · ".join(result))
            except Exception as exc:               # noqa: BLE001
                _put_message("error", T("Nie udało się zlecić przeładowania: %s",
                                        "The reload could not be requested: %s") % exc)
        return _redirect("/editsql/apply")
    return pages.apply_page(messages_list=_take_messages())


def _labels():
    panel = db.ns()
    request = panel.request
    if str(request.method).upper() == "POST":
        if (request.form.get("action") or "") == "save_all":
            try:
                saved = pages.labels_save_all(request.form)
                _put_message("ok", T("Zapisano nazwy (%d).", "Names saved (%d).") % saved)
            except Exception as exc:               # noqa: BLE001
                _put_message("error", T("Nie udało się zapisać nazw: %s",
                                        "The names could not be saved: %s") % exc)
        return _redirect("/editsql/labels")
    return pages.labels_page(messages_list=_take_messages())


def _api_name():
    """Podglad nazwy pod polem vnum (JSON: {"html": ...})."""
    panel = db.ns()
    request = panel.request
    kind = request.args.get("kind")
    try:
        vnum = int(request.args.get("vnum") or 0)
    except (TypeError, ValueError):
        vnum = 0
    none = '<span class="esq-dim">%s</span>' % render._esc(T("brak", "none"))
    if kind == "item":
        html = render.link_item(vnum) if vnum else none
    elif kind == "mob":
        html = render.link_mob(vnum) if vnum else none
    else:
        html = ""
    import json
    body = json.dumps({"html": html})
    try:
        from flask import Response
        return Response(body, mimetype="application/json")
    except Exception:                              # noqa: BLE001
        return body


def _pk_values(spec, pk_path):
    """Zamienia sciezke URL na wartosci klucza wiersza. None, gdy nie pasuje."""
    key_names = spec.get("key") or ()
    if not key_names:
        return None
    parts = [part for part in str(pk_path).split("/") if part != ""]
    if len(parts) != len(key_names):
        return None
    out = []
    for name, value in zip(key_names, parts):
        col = spec["tbl"]["by_name"][name]
        if col["data_type"] in ("tinyint", "smallint", "mediumint", "int", "bigint"):
            try:
                value = int(value)
            except ValueError:
                return None
        out.append(value)
    return out


def _missing_module():
    return render.page(T("Nie ma takiego modułu", "No such module"),
                       '<div class="esq-note esq-note-warn">%s</div>'
                       % render._esc(T("Tego modułu nie ma w tej bazie: brakuje jego tabel.",
                                       "This database has no such module: its tables are missing.")),
                       messages_list=_take_messages()), 404


def _module(module_id):
    """Lista modulu: wyszukiwanie, filtry, sortowanie, paginacja."""
    panel = db.ns()
    request = panel.request
    spec = editor.module_spec(module_id)
    if spec is None or not spec.get("available"):
        return _missing_module()
    args = request.args
    search = (args.get("q", "") or "").strip()
    sort = args.get("sort") or None
    direction = args.get("dir") if args.get("dir") in ("asc", "desc") else None
    try:
        page_no = max(1, int(args.get("page", 1)))
    except (TypeError, ValueError):
        page_no = 1
    filters = {}
    for name, _title, _kind in spec["filters"]:
        value = args.get(name)
        if value not in (None, ""):
            filters[name] = value
    # Podtyp bez typu nic nie znaczy (podtyp 0 to miecz u broni, a zbroja u pancerza).
    if "subtype" in filters and "type" not in filters:
        filters.pop("subtype")
    try:
        rows, total, order, per_page = editor.list_rows(
            spec, search=search, filters=filters, sort=sort, page=page_no, direction=direction)
        pages_total = max(1, (total + per_page - 1) // per_page)
        if page_no > pages_total:
            page_no = pages_total
            rows, total, order, per_page = editor.list_rows(
                spec, search=search, filters=filters, sort=sort, page=page_no,
                direction=direction)
    except Exception as exc:                       # noqa: BLE001
        return render.page(spec["title"],
                           '<div class="esq-note esq-note-warn">%s</div>'
                           % (T("Nie mogę czytać tabeli %s.%s: %s", "Cannot read the table %s.%s: %s")
                              % (render._esc(spec["db"]), render._esc(spec["table"]),
                                 render._esc(exc))),
                           active=module_id, messages_list=_take_messages())

    base = "/editsql/%s" % module_id
    params = {"q": search}
    params.update(filters)
    if sort:
        params["sort"] = order[0]
        params["dir"] = order[1]
    extra = editor.query_string(params)
    body = []
    body.append(render.notes_html(spec["db"], spec["table"]))
    if module_id == "spawns":
        try:
            current_map = int(filters.get("map_index") or args.get("map") or 0) or None
        except (TypeError, ValueError):
            current_map = None
        body.append(render.box(T("Działki na mapie", "Plots on the map"),
                               modules.lands_map_html(current_map),
                               T("Prostokąty to działki wybranej mapy. Kliknij działkę na "
                                 "liście, żeby ją edytować.",
                                 "The rectangles are the plots of the chosen map. Click a plot "
                                 "in the list to edit it.")))
    if module_id == "itemshop":
        body.append(modules.itemshop_broken_note(spec))
    select_form = None
    if _row_spec(module_id) is not None:
        select_form = ROWS_FORM
        body.append(_row_actions_html(module_id))
    body.extend([
        editor.toolbar_html(spec, base, filters, search, sort and order[0],
                            sort and order[1], total),
        editor.list_html(spec, rows, base, search, filters, order[0], order[1], page_no,
                         select_form=select_form),
        render.pager(base, page_no, per_page, total, extra=extra),
    ])
    if module_id == "bonuses":
        body.append(modules.bonuses_grid(spec["table"]))
    return render.page(spec["title"], "".join(body), active=module_id,
                       messages_list=_take_messages(),
                       subtitle="%s.%s" % (spec["db"], spec["table"]),
                       side=render.side_help(T("Wskazówki", "Tips"), (
                           T("Kliknij wiersz (albo „Edytuj”), żeby otworzyć formularz.",
                             "Click a row (or “Edit”) to open its form."),
                           T("Kliknij nagłówek kolumny, żeby posortować; drugi klik odwraca kolejność.",
                             "Click a column's heading to sort; a second click reverses the order."),
                           T("Wyszukiwanie i sortowanie robi baza - do przeglądarki trafia tylko "
                             "bieżąca strona.",
                             "The database does the searching and sorting - only the current page "
                             "reaches the browser."),
                           T("Każdy zapis najpierw pokazuje podgląd zmian.",
                             "Every save shows a preview of the changes first."))))


def _detail(module_id, db_name, pk_path):
    panel = db.ns()
    request = panel.request
    spec = editor.module_spec(module_id)
    if spec is None or not spec.get("available"):
        return _missing_module()
    if db_name != spec["db"]:
        return render.page(spec["title"],
                           '<div class="esq-note esq-note-warn">%s</div>'
                           % (T("Ten moduł czyta tabelę z bazy %s, a w adresie jest %s.",
                                "This module reads its table from database %s, and the address "
                                "says %s.") % (render._esc(spec["db"]), render._esc(db_name))),
                           active=module_id, messages_list=_take_messages())
    pk_values = _pk_values(spec, pk_path)
    if pk_values is None:
        cause = (T("Ten moduł nie ma klucza, który jednoznacznie wskazywałby wiersz, "
                   "więc jest tylko do odczytu.",
                   "This module has no key that points at one row, so it is read only.")
                 if not spec.get("key") else
                 T("Adres nie zawiera poprawnego klucza wiersza (%s).",
                   "The address does not hold a valid row key (%s).")
                 % ", ".join(spec.get("key") or ()))
        return render.page(spec["title"],
                           '<div class="esq-note esq-note-warn">%s</div>' % render._esc(cause),
                           active=module_id, messages_list=_take_messages())
    action = str(request.form.get("action") or "") if str(request.method).upper() == "POST" else ""
    here = _detail_url(module_id, spec, pk_values)

    # --- POST ---------------------------------------------------------------
    if action == "preview":
        return _preview(module_id, spec, pk_values)
    if action == "save":
        return _save(module_id, spec, pk_values)
    if action == "child_add":
        return _child_add(spec, pk_values)
    if action == "child_delete":
        return _child_delete(spec, pk_values)
    if action == "cancel":
        token = request.form.get("token") or ""
        if token:
            safety.take(token)                     # porzucony podglad nie wisi w pamieci
        _put_message("info", T("Zmiany nie zostały zapisane.", "The changes were not saved."))
        return _redirect(here)

    row = safety.fetch_row(spec["tbl"], pk_values, spec.get("key"))
    if row is None:
        return render.page(spec["title"],
                           '<div class="esq-note esq-note-warn">%s</div>'
                           % (T("Nie ma takiego wiersza (%s).", "There is no such row (%s).")
                              % render._esc(", ".join("%s=%s" % (n, v) for n, v in
                                                      zip(spec.get("key") or (), pk_values)))),
                           active=module_id, messages_list=_take_messages()), 404
    title = _row_title(spec, row)

    # --- ekran potwierdzenia (po podgladzie) --------------------------------
    token = request.args.get("preview")
    if token:
        # keep=True: ekran potwierdzenia tylko CZYTA podglad; token zuzywa zapis.
        payload = safety.take(token, keep=True)
        if not _payload_ok(payload, module_id, spec, "update") or payload.get("pk") != pk_values:
            _put_message("error", T("Podgląd wygasł - powtórz edycję.",
                                    "The preview has expired - make the edit again."))
            return _redirect(here)
        body = editor.preview_html(spec, row, payload["changes"], here, token)
        preview = T("Podgląd zmian", "Preview of the changes")
        return render.page(preview, body, active=module_id,
                           messages_list=_take_messages(), subtitle=title,
                           crumbs=[(spec["title"], "/editsql/%s" % module_id), (title, here),
                                   (preview, None)],
                           side=render.side_help(T("Przed zapisem", "Before the save"), (
                               T("Zapis idzie w jednej transakcji razem z wpisem w historii.",
                                 "The save runs in one transaction together with its history entry."),
                               T("Edytor sprawdza, czy wiersz nie zmienił się od odczytu - "
                                 "jeśli tak, odmawia zamiast nadpisać cudzą zmianę.",
                                 "The editor checks that the row has not changed since it was read "
                                 "- if it has, it refuses rather than overwrite someone else's change."),
                               T("Każdą zmianę można cofnąć w Historii zmian.",
                                 "Every change can be undone in the Change history."))))

    # --- formularz ----------------------------------------------------------
    return _render_form(module_id, spec, pk_values, row, title, here)


def _render_form(module_id, spec, pk_values, row, title, here, invalid=(), messages=None,
                 db_row=None):
    readonly = bool(spec.get("readonly"))
    body = [pages.effect_html(spec["db"], spec["table"]),
            editor.row_card(spec, db_row or row)]
    if _row_spec(module_id) is not None and not readonly:
        body.append(_row_detail_actions_html(module_id, pk_values))
    if module_id == "spawns":
        body.append(_spawn_map_block(db_row or row))
    body.append(editor.related_html(spec, db_row or row, key="related_top"))
    body.append(editor.form_html(spec, row, here, readonly=readonly, invalid=invalid))
    if module_id == "shops":
        body.append(modules.shop_items_html(row.get("vnum")))
    if module_id == "spawns":
        body.append(modules.objects_on_land(row.get("id")))
    body.append(editor.related_html(spec, db_row or row))
    if module_id == "spawns":
        body.append(modules.map_script())
    return render.page(title, "".join(body), active=module_id,
                       messages_list=_take_messages() if messages is None else messages,
                       crumbs=[(spec["title"], "/editsql/%s" % module_id), (title, None)],
                       subtitle=", ".join("%s %s" % (k, v) for k, v in
                                          zip(spec.get("key") or (), pk_values)),
                       side=render.side_help(T("Jak edytować", "How to edit"), (
                           T("Zmienione pola są podświetlone, a licznik na dole pokazuje, ile ich jest.",
                             "Changed fields are highlighted, and the counter at the bottom shows "
                             "how many there are."),
                           T("„Podgląd zmian” niczego jeszcze nie zapisuje - pokazuje było/będzie "
                             "i dopiero tam potwierdzasz zapis.",
                             "“Preview changes” saves nothing yet - it shows was/will be, "
                             "and only there do you confirm the save."),
                           T("Najedź na nazwę kolumny, żeby zobaczyć jej typ i wartość domyślną.",
                             "Hover over a column's name to see its type and default value."))))


def _detail_url(module_id, spec, pk_values):
    import urllib.parse
    return "/editsql/%s/%s/%s" % (module_id, spec["db"],
                                  "/".join(urllib.parse.quote(str(v), safe="") for v in pk_values))


def _spawn_map_block(row):
    """Podglad dzialki na mapie (world.land ma map_index i bezwzgledne x/y)."""
    if "map_index" not in row:
        return ""
    return render.box(T("Położenie na mapie", "Position on the map"),
                      modules.map_html(row.get("map_index"), row.get("x"), row.get("y"),
                                       row.get("width"), row.get("height"), clickable=True,
                                       others=modules.lands_on_map(row.get("map_index"),
                                                                   exclude=row.get("id")))
                      + '<p class="esq-hint" id="esq-map-pick"></p>',
                      T("Czerwony prostokąt to ta działka, jasne - pozostałe działki tej mapy. "
                        "Kliknięcie mapy wpisuje X/Y do formularza (zapis dopiero po podglądzie "
                        "zmian).",
                        "The red rectangle is this plot, the light ones the map's other plots. "
                        "A click on the map writes X/Y into the form (saved only after the "
                        "preview of the changes)."))


def _row_title(spec, row):
    table = spec["table"]
    if table == "land":
        return T("Działka #%s · %s", "Plot #%s · %s") % (row.get("id"), modules.map_label(row.get("map_index")))
    if table == "refine_proto":
        return T("Przepis #%s", "Recipe #%s") % row.get("id")
    if table == "exp_table":
        return T("Poziom %s", "Level %s") % row.get("level")
    if table == "shop":
        return T("Sklep #%s%s", "Shop #%s%s") % (row.get("vnum"),
                                                (" · %s" % row["name"]) if row.get("name") else "")
    if table == "itemshop_items":
        return T("Pozycja %s · %s", "Position %s · %s") % (
            row.get("index"), render.item_name(row.get("vnum")) or row.get("vnum"))
    if table == "crafting_proto":
        return T("Przepis #%s · %s", "Recipe #%s · %s") % (
            row.get("vnum"), render.item_name(row.get("item_vnum")) or row.get("item_vnum"))
    if table == "gmlist":
        return "%s (%s)" % (row.get("mName"), row.get("mAuthority"))
    for name in ("locale_name", "szName", "quest_name", "apply", "name"):
        if name in row and row.get(name) not in (None, ""):
            value = row[name]
            if isinstance(value, (bytes, bytearray)):
                value = db.decode(value)
            if name == "apply":
                return labels.bonus_text(value)[0]
            if name == "name" and table in ("item_proto", "mob_proto"):
                continue
            if name == "locale_name":
                # In the reader's language (editor.game_name); the form
                # below still shows and edits the stored Polish name.
                value = editor.game_name(spec, name, row, value)
            return str(value)[:60]
    return ", ".join("%s %s" % (n, row.get(n)) for n in (spec.get("key") or ())[:2])


def _logical(spec):
    """Klucz logiczny modulu (None, gdy tabela ma klucz glowny)."""
    return None if spec["pk"] else tuple(spec.get("key") or ())


def _preview(module_id, spec, pk_values):
    """Waliduje formularz i zapisuje podglad po stronie serwera."""
    panel = db.ns()
    request = panel.request
    back = _detail_url(module_id, spec, pk_values)
    row = safety.fetch_row(spec["tbl"], pk_values, spec.get("key"))
    if row is None:
        _put_message("error", T("Wiersz zniknął z bazy.", "The row is gone from the database."))
        return _redirect(back)
    if spec.get("readonly"):
        _put_message("error", T("Ta tabela jest tylko do odczytu.", "This table is read only."))
        return _redirect(back)
    try:
        changes, errors = safety.build_changes(spec["tbl"], row, request.form,
                                               keys=spec.get("key") or ())
    except safety.Denied as exc:
        _put_message("error", str(exc))
        return _redirect(back)
    if not errors and changes and (spec["db"], spec["table"]) == safety.ITEMSHOP:
        # An offer is judged as the edit leaves it, not field by field: a row
        # already broken (Drip's vnum 0) must come out of any edit as an offer
        # the game can sell. The save asks again under its locks.
        after = dict(row)
        after.update((change["column"], change["new"]) for change in changes)
        try:
            errors = safety.itemshop_problems(spec["tbl"], after, new=False)
        except Exception as exc:                   # noqa: BLE001 - komunikat na ekran
            errors = [T("baza: %s", "database: %s") % exc]
    if errors:
        # Formularz wraca Z WPISANYMI wartosciami (a nie z bazy), a bledne pola
        # sa zaznaczone - inaczej jedna literowka kasowalaby wszystkie zmiany.
        submitted = dict(row)
        getter = getattr(request.form, "getlist", None)
        for col in spec["tbl"]["columns"]:
            name = col["name"]
            if col["set"] and ("__set__" + name) in request.form:
                submitted[name] = ",".join(getter(name) if getter else [])
            elif name in request.form and name not in (spec.get("key") or ()):
                submitted[name] = request.form.get(name)
        invalid = [e.split(":", 1)[0] for e in errors]
        return _render_form(module_id, spec, pk_values, submitted, _row_title(spec, row), back,
                            invalid=invalid, db_row=row,
                            messages=[("error", T("Popraw zaznaczone pola: ", "Correct the marked fields: ")
                                       + "; ".join(errors[:6]))])
    if not changes:
        _put_message("info", T("Nic nie zmieniono - formularz ma te same wartości co baza.",
                               "Nothing changed - the form has the same values as the database."))
        return _redirect(back)
    ok, reason = schema.writable(spec["db"], spec["table"], _logical(spec))
    if not ok:
        _put_message("error", T("Nie mogę zapisać: %s", "Cannot save: %s") % reason)
        return _redirect(back)
    if not spec["pk"]:
        try:
            safety.uniqueness_guard(spec["tbl"], _logical(spec), pk_values)
        except safety.Denied as exc:
            _put_message("error", str(exc))
            return _redirect(back)
    token = safety.stash({"module": module_id, "db": spec["db"], "table": spec["table"],
                          "pk": pk_values, "logical_key": _logical(spec),
                          "changes": changes})
    return _redirect(back + "?preview=" + token)


def _save(module_id, spec, pk_values):
    panel = db.ns()
    request = panel.request
    back = _detail_url(module_id, spec, pk_values)
    token = request.form.get("token") or ""
    payload = safety.take(token)
    if not _payload_ok(payload, module_id, spec, "update") or payload.get("pk") != pk_values:
        _put_message("error", T("Podgląd wygasł (albo został już użyty) - powtórz edycję.",
                                "The preview has expired (or was used already) - make the edit again."))
        return _redirect(back)
    try:
        count = safety.apply_changes(payload["db"], payload["table"], payload["pk"],
                                     payload["changes"], pages._admin_name(),
                                     logical_key=payload.get("logical_key"))
        render.invalidate_names()
        _put_message("ok", T("Zapisano %d %s. Zmiana jest w Historii zmian; w grze zadziała "
                             "zgodnie z opisem „Efekt w grze”.",
                             "Saved %d %s. The change is in the Change history; in the game it "
                             "takes effect as “Effect in the game” says.")
                     % (count, i18n.plural(count, ("pole", "pola", "pól"), ("field", "fields"))))
    except safety.Conflict as exc:
        _put_message("error", T("Nie zapisano, bo wiersz się zmienił: %s",
                                "Not saved, because the row has changed: %s") % exc)
    except safety.Denied as exc:
        _put_message("error", T("Nie mogę zapisać: %s", "Cannot save: %s") % exc)
    except Exception as exc:                       # noqa: BLE001
        _put_message("error", T("Błąd zapisu: %s", "Save error: %s") % exc)
    return _redirect(back)


def _child_add(spec, pk_values):
    """Dodanie pozycji do sklepu (jeden wiersz, walidowany, z audytem)."""
    panel = db.ns()
    request = panel.request
    child_db, child_table = "world", "shop_item"
    back = _detail_url("shops", spec, pk_values)
    if spec["table"] != "shop" or not schema.table(child_db, child_table):
        _put_message("error", T("Nie ma tabeli world.shop_item.", "There is no world.shop_item table."))
        return _redirect(back)
    shop_vnum = pk_values[0]
    raw_item = (request.form.get("item_vnum") or "").strip()
    raw_count = (request.form.get("count") or "1").strip()
    shop_col = schema.table(child_db, child_table)["by_name"]
    try:
        _, item_vnum, _ = safety.validate(shop_col["item_vnum"], raw_item)
        _, count, _ = safety.validate(shop_col["count"], raw_count)
    except (safety.Invalid, KeyError) as exc:
        _put_message("error", T("Popraw dane pozycji: %s", "Correct the item's data: %s") % exc)
        return _redirect(back)
    if not item_vnum or not count or count < 1:
        _put_message("error", T("Podaj VNUM przedmiotu i ilość większą od zera.",
                                "Give the item's VNUM and a count above zero."))
        return _redirect(back)
    items = schema.table("world", "item_proto")
    if items is None:
        _put_message("error", T("Nie ma tabeli przedmiotów, nie mogę sprawdzić vnumu.",
                                "There is no item table, so the vnum cannot be checked."))
        return _redirect(back)
    exists = db.scalar("SELECT COUNT(*) AS n FROM %s WHERE %s=%%s"
                       % (db.qt(items["db"], items["name"]), db.qi("vnum")),
                       (item_vnum,), 0)
    if not exists:
        _put_message("error", T("Nie ma przedmiotu o vnum %s - nie dodaję.",
                                "There is no item with vnum %s - not adding it.") % item_vnum)
        return _redirect(back)
    dup = db.scalar("SELECT COUNT(*) AS n FROM %s WHERE `shop_vnum`=%%s AND `item_vnum`=%%s "
                    "AND `count`=%%s" % db.qt(child_db, child_table),
                    (shop_vnum, item_vnum, count), 0)
    if dup:
        _put_message("error", T("Ta pozycja (przedmiot %s × %s) już jest w sklepie.",
                                "That entry (item %s × %s) is already in the shop.") % (item_vnum, count))
        return _redirect(back)
    try:
        safety.insert_row(child_db, child_table,
                          {"shop_vnum": shop_vnum, "item_vnum": item_vnum, "count": count},
                          pages._admin_name(), note="pozycja sklepu %s" % shop_vnum)
        _put_message("ok", T("Dodano przedmiot %s × %s do sklepu %s.",
                             "Added item %s × %s to shop %s.")
                     % (render.item_name(item_vnum) or item_vnum, count, shop_vnum))
    except Exception as exc:                       # noqa: BLE001
        _put_message("error", T("Nie dodano: %s", "Not added: %s") % exc)
    return _redirect(back)


def _child_delete(spec, pk_values):
    panel = db.ns()
    request = panel.request
    back = _detail_url("shops", spec, pk_values)
    table = schema.table("world", "shop_item")
    if table is None or spec["table"] != "shop":
        _put_message("error", T("Nie ma tabeli world.shop_item.", "There is no world.shop_item table."))
        return _redirect(back)
    # shop_item nie ma klucza glownego, wiec usuwamy po pelnej krotce
    # (sklep, przedmiot, ilosc) i dokladnie jeden wiersz.
    raw_item = (request.form.get("item_vnum") or "").strip()
    raw_count = (request.form.get("count") or "").strip()
    try:
        item_vnum = int(raw_item)
        count = int(raw_count)
    except ValueError:
        _put_message("error", T("Niepoprawna pozycja do usunięcia.", "Invalid item to remove."))
        return _redirect(back)
    try:
        safety.delete_row('world', 'shop_item', (pk_values[0], item_vnum, count),
                          pages._admin_name(), note='Shop row removal')
        _put_message("ok", T("Usunięto przedmiot %s ze sklepu %s.", "Removed item %s from shop %s.")
                     % (render.item_name(item_vnum) or item_vnum, pk_values[0]))
    except Exception as exc:                       # noqa: BLE001
        _put_message("error", T("Nie usunięto: %s", "Not removed: %s") % exc)
    return _redirect(back)


# -----------------------------------------------------------------------------
#  Cale wiersze: dodawanie i usuwanie (dzis tylko Wytwarzanie)
#
#  Ten sam przeplyw co edycja: formularz -> podglad trzymany na serwerze (token
#  jednorazowy, 30 min, przypiety do sesji) -> zapis w jednej transakcji z
#  blokadami i wpisem historii (writes.py). Moduly bez spec["rows"] dostaja 404
#  - nie ma ogolnego dodawania ani usuwania wierszy dowolnej tabeli.
# -----------------------------------------------------------------------------
ROWS_FORM = "esq-rows"
ROWS_BATCH_MAX = 200


# What a module whose whole rows are added and deleted (spec["rows"]) says,
# and its own notes and table. The recipe's are the editor's words as they
# were before the ItemShop got rows (its Polish pages are pinned in
# tests/data/editsql_pl_golden.json.gz); the offer's are new (Drip, 7
# October). The two notes for the history ("note_*") are history data, always
# written in Polish, as the history always has been.
ROW_KINDS = {
    "crafting": {
        "key": "vnum",
        "forms": (("przepis", "przepisy", "przepisów"), ("recipe", "recipes")),
        "add": P("Dodaj przepis", "Add a recipe"),
        "list_hint": P("Zaznacz przepisy w pierwszej kolumnie. Dodanie i usunięcie pokazują "
                       "najpierw podgląd; każdy wiersz trafia do historii, z której można go "
                       "cofnąć.",
                       "Select recipes in the first column. Adding and deleting show a preview "
                       "first; every row goes into the history, where it can be undone."),
        "add_similar": P("Dodaj podobny przepis", "Add a similar recipe"),
        "delete_this": P("Usuń ten przepis", "Delete this recipe"),
        "new": P("Nowy przepis", "New recipe"),
        "preview_new": P("Podgląd nowego przepisu", "Preview the new recipe"),
        "new_help": (P("„Podgląd nowego przepisu” niczego jeszcze nie zapisuje.",
                       "“Preview the new recipe” saves nothing yet."),
                     P("Wynik i każdy składnik muszą być przedmiotami z item_proto, a numer "
                       "przepisu - wolny.",
                       "The result and every ingredient must be items of item_proto, and "
                       "the recipe's number a free one."),
                     P("Dodanie trafia do Historii zmian; cofnięcie usuwa ten przepis, dopóki "
                       "nikt go później nie zmienił.",
                       "The addition goes into the Change history; its undo deletes the "
                       "recipe as long as nobody has changed it since.")),
        "not_added": P("Przepis nie został dodany - popraw dane i obejrzyj podgląd jeszcze raz.",
                       "The recipe was not added - correct the data and look at the preview again."),
        "new_expired": P("Podgląd wygasł - wpisz przepis jeszcze raz.",
                         "The preview has expired - enter the recipe again."),
        "save_add": P("Dodaj przepis", "Add the recipe"),
        "preview_title": P("Podgląd nowego przepisu", "Preview of the new recipe"),
        "under_lock": P("Edytor sprawdza jeszcze raz pod blokadą, czy numer jest wolny, "
                        "a wynik i składniki istnieją.",
                        "Under a lock the editor checks again that the number is free and "
                        "that the result and the ingredients exist."),
        "copy": P("Kopia przepisu #%s - numer jest już nowy, zmień to, co ma być inne.",
                  "A copy of recipe #%s - the number is a new one already; change what "
                  "should be different."),
        "save_expired": P("Podgląd wygasł (albo został już użyty) - wpisz przepis jeszcze raz.",
                          "The preview has expired (or was used already) - enter the recipe again."),
        "note_new": "Nowy przepis wytwarzania #%s",
        "added": P("Dodano przepis #%s. Dodanie jest w Historii zmian; w grze zadziała po "
                   "restarcie rdzeni („Zastosuj”).",
                   "Recipe #%s added. The addition is in the Change history; in the game it "
                   "takes effect after a restart of the cores (“Apply”)."),
        "delete_expired": P("Podgląd usunięcia wygasł - zaznacz przepisy jeszcze raz.",
                            "The preview of the deletion has expired - select the recipes again."),
        "delete_save_expired": P("Podgląd usunięcia wygasł (albo został już użyty) - zaznacz "
                                 "przepisy jeszcze raz.",
                                 "The preview of the deletion has expired (or was used already) "
                                 "- select the recipes again."),
        "note_delete": "Usunięcie przepisów wytwarzania",
        "bad_number": P("Niepoprawny numer przepisu: %r.", "Invalid recipe number: %r."),
        "select": P("Zaznacz przepisy do usunięcia.", "Select the recipes to delete."),
        "at_most": P("Najwyżej %d przepisów naraz.", "%d recipes at most at once."),
        "missing": P("Nie ma przepisów: %s - odśwież listę.", "No such recipes: %s - reload the list."),
        "new_notes": lambda values: (modules.crafting_window_note(values.get("vnum")),),
        "delete_notes": lambda rows: "".join(modules.crafting_window_note(r.get("vnum"), deleting=True)
                                             for r in rows),
        "rows_table": lambda rows: modules.crafting_rows_table(rows),
    },
    "itemshop": {
        "key": "index",
        "forms": (("pozycję", "pozycje", "pozycji"), ("offer", "offers")),
        "add": P("Dodaj pozycję", "Add an offer"),
        "list_hint": P("Zaznacz pozycje w pierwszej kolumnie. Pozycję zdejmuje się ze sklepu "
                       "usunięciem - nie zerem w przedmiocie ani w ilości: rdzeń, który wysłał "
                       "taką pozycję, padał przy każdym otwarciu ItemShopu. Dodanie i usunięcie "
                       "pokazują najpierw podgląd; każdy wiersz trafia do historii, z której można "
                       "go cofnąć.",
                       "Select offers in the first column. An offer comes off the shop by deleting "
                       "it - not with a 0 in its item or count: a core that sent such an offer "
                       "went down at every open of the ItemShop. Adding and deleting show a "
                       "preview first; every row goes into the history, where it can be undone."),
        "add_similar": P("Dodaj podobną pozycję", "Add a similar offer"),
        "delete_this": P("Usuń tę pozycję", "Delete this offer"),
        "new": P("Nowa pozycja", "New offer"),
        "preview_new": P("Podgląd nowej pozycji", "Preview the new offer"),
        "new_help": (P("„Podgląd nowej pozycji” niczego jeszcze nie zapisuje.",
                       "“Preview the new offer” saves nothing yet."),
                     P("Przedmiot musi być w item_proto, ilość - od 1 do jego stosu, a numer "
                       "pozycji - wolny. Numer wybiera stronę okna ItemShopu w kliencie.",
                       "The item must be in item_proto, the count from 1 to its stack, and the "
                       "position's number a free one. The number picks the page of the client's "
                       "ItemShop window."),
                     P("Dodanie trafia do Historii zmian; cofnięcie usuwa tę pozycję, dopóki "
                       "nikt jej później nie zmienił.",
                       "The addition goes into the Change history; its undo deletes the offer "
                       "as long as nobody has changed it since.")),
        "not_added": P("Pozycja nie została dodana - popraw dane i obejrzyj podgląd jeszcze raz.",
                       "The offer was not added - correct the data and look at the preview again."),
        "new_expired": P("Podgląd wygasł - wpisz pozycję jeszcze raz.",
                         "The preview has expired - enter the offer again."),
        "save_add": P("Dodaj pozycję", "Add the offer"),
        "preview_title": P("Podgląd nowej pozycji", "Preview of the new offer"),
        "under_lock": P("Edytor sprawdza jeszcze raz pod blokadą, czy numer jest wolny, "
                        "a przedmiot istnieje i ilość mieści się w jego stosie.",
                        "Under a lock the editor checks again that the number is free, the item "
                        "exists and the count fits its stack."),
        "copy": P("Kopia pozycji %s - numer jest już nowy, zmień to, co ma być inne.",
                  "A copy of position %s - the number is a new one already; change what "
                  "should be different."),
        "save_expired": P("Podgląd wygasł (albo został już użyty) - wpisz pozycję jeszcze raz.",
                          "The preview has expired (or was used already) - enter the offer again."),
        "note_new": "Nowa pozycja ItemShopu %s",
        "added": P("Dodano pozycję %s. Dodanie jest w Historii zmian; w grze zadziała po "
                   "restarcie rdzeni („Zastosuj”).",
                   "Offer %s added. The addition is in the Change history; in the game it "
                   "takes effect after a restart of the cores (“Apply”)."),
        "delete_expired": P("Podgląd usunięcia wygasł - zaznacz pozycje jeszcze raz.",
                            "The preview of the deletion has expired - select the offers again."),
        "delete_save_expired": P("Podgląd usunięcia wygasł (albo został już użyty) - zaznacz "
                                 "pozycje jeszcze raz.",
                                 "The preview of the deletion has expired (or was used already) "
                                 "- select the offers again."),
        "note_delete": "Usunięcie pozycji ItemShopu",
        "bad_number": P("Niepoprawny numer pozycji: %r.", "Invalid position number: %r."),
        "select": P("Zaznacz pozycje do usunięcia.", "Select the offers to delete."),
        "at_most": P("Najwyżej %d pozycji naraz.", "%d offers at most at once."),
        "missing": P("Nie ma pozycji: %s - odśwież listę.", "No such offers: %s - reload the list."),
        "new_notes": lambda values: (modules.itemshop_page_note(values.get("index"),
                                                                 _text(values.get("currency"))),),
        "delete_notes": lambda rows: modules.itemshop_delete_note(rows),
        "rows_table": lambda rows: modules.itemshop_rows_table(rows),
    },
}
# The table each module's rows are in, and its key: nothing else gets rows.
_ROW_TABLES = {"crafting": (safety.CRAFTING, ("vnum",)), "itemshop": (safety.ITEMSHOP, ("index",))}


def _text(value):
    return db.decode(value) if isinstance(value, (bytes, bytearray)) else value


def _payload_ok(payload, module_id, spec, op):
    """Podglad pasuje do tej strony: ten sam modul, tabela i rodzaj operacji."""
    return (payload is not None and payload.get("op", "update") == op
            and payload.get("module") == module_id and payload.get("db") == spec["db"]
            and payload.get("table") == spec["table"])


def _row_spec(module_id):
    spec = editor.module_spec(module_id)
    table_key = _ROW_TABLES.get(module_id)
    if (spec is None or table_key is None or not spec.get("available") or not spec.get("rows")
            or (spec["db"], spec["table"]) != table_key[0]
            or tuple(spec.get("key") or ()) != table_key[1] or spec.get("readonly")):
        return None
    return spec


def _row_actions_html(module_id):
    words = ROW_KINDS[module_id]
    return ('<div class="esq-row-actions">'
            '<a class="esq-btn esq-btn-small esq-btn-go" href="/editsql/%s/new">%s</a>'
            '<form id="%s" method="post" action="/editsql/%s/delete" class="esq-inline-form">%s'
            '<input type="hidden" name="action" value="preview" />'
            '<button class="esq-btn esq-btn-small esq-btn-danger" type="submit">%s</button>'
            '</form><span class="esq-hint">%s</span></div>'
            % (render._esc(module_id), render._esc(tr(words["add"])),
               ROWS_FORM, render._esc(module_id), render.csrf_input(),
               render._esc(T("Usuń zaznaczone", "Delete the selected")),
               render._esc(tr(words["list_hint"]))))


def _row_detail_actions_html(module_id, pk_values):
    words = ROW_KINDS[module_id]
    key = render._esc("/".join(str(v) for v in pk_values))
    return ('<div class="esq-row-actions">'
            '<a class="esq-btn esq-btn-small esq-btn-go" href="/editsql/%s/new?from=%s">%s</a>'
            '<form method="post" action="/editsql/%s/delete" class="esq-inline-form">%s'
            '<input type="hidden" name="action" value="preview" />'
            '<input type="hidden" name="pk" value="%s" />'
            '<button class="esq-btn esq-btn-small esq-btn-danger" type="submit">%s'
            '</button></form></div>'
            % (render._esc(module_id), key, render._esc(tr(words["add_similar"])),
               render._esc(module_id), render.csrf_input(), key,
               render._esc(tr(words["delete_this"]))))


def _blank_row(spec, source=None):
    """Wartosci startowe nowego wiersza: kopia `source` albo rozsadne domyslne."""
    table = spec["tbl"]
    key = ROW_KINDS[spec["id"]]["key"]
    row = {}
    for col in table["columns"]:
        if col["default"] is not None:
            row[col["name"]] = col["default"]
        elif col["nullable"]:
            row[col["name"]] = None
        else:
            row[col["name"]] = 0 if col["data_type"] in editor.INT_TYPES else ""
    if "count" in row:
        row["count"] = 1
    if "chance" in row:
        row["chance"] = 100
    if (spec["db"], spec["table"]) == safety.ITEMSHOP and "vnum" in row:
        # An offer's item is the operator's to name: an empty field, never the
        # 0 the column would default to (a 0 is what crashed Drip's core).
        row["vnum"] = ""
    if source:
        row.update({k: v for k, v in source.items() if k in table["by_name"]})
    free = db.scalar("SELECT COALESCE(MAX(%s), 0) + 1 AS n FROM %s"
                     % (db.qi(key), db.qt(spec["db"], spec["table"])), None, 1)
    row[key] = int(free or 1)
    return row


def _row_new_form(module_id, spec, base, row, invalid=(), messages=None, notes=()):
    words = ROW_KINDS[module_id]
    new = tr(words["new"])
    return render.page(new,
                       editor.insert_form_html(spec, row, base, invalid, notes,
                                               preview_label=tr(words["preview_new"])),
                       active=module_id,
                       messages_list=_take_messages() if messages is None else messages,
                       crumbs=[(spec["title"], "/editsql/%s" % module_id), (new, None)],
                       subtitle="%s.%s" % (spec["db"], spec["table"]),
                       side=render.side_help(new, tuple(tr(text) for text in words["new_help"])))


def _row_new(module_id):
    """GET formularz / ekran potwierdzenia; POST preview, save, cancel."""
    spec = _row_spec(module_id)
    if spec is None:
        return _missing_module()
    words = ROW_KINDS[module_id]
    request = db.ns().request
    base = "/editsql/%s/new" % module_id
    if str(request.method).upper() == "POST":
        action = str(request.form.get("action") or "")
        if action == "save":
            return _row_new_save(module_id, spec, base)
        if action == "cancel":
            payload = safety.take(request.form.get("token") or "")
            if not _payload_ok(payload, module_id, spec, "insert"):
                return _redirect(base)
            row = {name: (db.decode(value, spec["tbl"]["by_name"][name]["charset"])
                          if isinstance(value, (bytes, bytearray)) else value)
                   for name, value in payload["values"].items()}
            return _row_new_form(module_id, spec, base, row,
                                 messages=[("info", tr(words["not_added"]))])
        if action == "preview":
            return _row_new_preview(module_id, spec, base)
        return _redirect(base)

    token = request.args.get("preview")
    if token:
        payload = safety.take(token, keep=True)
        if not _payload_ok(payload, module_id, spec, "insert"):
            _put_message("error", tr(words["new_expired"]))
            return _redirect(base)
        number = payload["values"].get(words["key"])
        body = (pages.effect_html(spec["db"], spec["table"]) +
                editor.insert_preview_html(spec, payload["values"], base, token,
                                           notes=words["new_notes"](payload["values"]),
                                           save_label=tr(words["save_add"])))
        return render.page(tr(words["preview_title"]), body,
                           active=module_id, messages_list=_take_messages(), subtitle="#%s" % number,
                           crumbs=[(spec["title"], "/editsql/%s" % module_id),
                                   (tr(words["new"]), base),
                                   (T("Podgląd", "Preview"), None)],
                           side=render.side_help(T("Przed zapisem", "Before the save"), (
                               T("Zapis idzie w jednej transakcji razem z wpisem w historii.",
                                 "The save runs in one transaction together with its history entry."),
                               tr(words["under_lock"]),
                               T("Dodanie można cofnąć w Historii zmian.",
                                 "The addition can be undone in the Change history."))))

    source, notes = None, ()
    from_key = request.args.get("from")
    if from_key and safety._DIGITS.match(str(from_key)):
        source = safety.fetch_row(spec["tbl"], [int(from_key)], (words["key"],))
        if source is not None:
            notes = ('<div class="esq-note esq-note-info">%s</div>'
                     % (tr(words["copy"]) % render._esc(from_key)),)
    return _row_new_form(module_id, spec, base, _blank_row(spec, source), notes=notes)


def _row_new_preview(module_id, spec, base):
    request = db.ns().request
    table = spec["tbl"]
    values, errors = safety.build_row(table, request.form)
    # Pola, ktore przeszly typ, sprawdzamy w bazie od razu - operator widzi
    # wszystkie bledy naraz, a nie jeden po drugim.
    try:
        errors.extend(safety.row_problems(table, values, new=True))
    except Exception as exc:                       # noqa: BLE001 - komunikat na ekran
        errors.append(T("baza: %s", "database: %s") % exc)
    ok, reason = schema.writable(spec["db"], spec["table"], for_insert=True)
    if not ok:
        errors.append(T("tabela: %s", "table: %s") % reason)
    if errors:
        # Formularz wraca z wpisanymi wartosciami, bledne pola sa zaznaczone.
        submitted = {col["name"]: request.form.get(col["name"]) for col in table["columns"]}
        return _row_new_form(module_id, spec, base, submitted,
                             invalid=[e.split(":", 1)[0] for e in errors],
                             messages=[("error", T("Popraw zaznaczone pola: ", "Correct the marked fields: ")
                                        + "; ".join(errors[:6]))])
    token = safety.stash({"module": module_id, "db": spec["db"], "table": spec["table"],
                          "op": "insert", "pk": [values.get(ROW_KINDS[module_id]["key"])],
                          "values": values})
    return _redirect(base + "?preview=" + token)


def _row_new_save(module_id, spec, base):
    words = ROW_KINDS[module_id]
    request = db.ns().request
    payload = safety.take(request.form.get("token") or "")
    if not _payload_ok(payload, module_id, spec, "insert"):
        _put_message("error", tr(words["save_expired"]))
        return _redirect(base)
    number = payload["values"].get(words["key"])
    try:
        # The note is history data and stays as it has always been written.
        safety.insert_row(spec["db"], spec["table"], payload["values"], pages._admin_name(),
                          note=words["note_new"] % number)
    except safety.Conflict as exc:
        _put_message("error", T("Nie dodano: %s", "Not added: %s") % exc)
        return _redirect(base)
    except (safety.Denied, safety.Invalid) as exc:
        _put_message("error", T("Nie mogę dodać: %s", "Cannot add: %s") % exc)
        return _redirect(base)
    except Exception as exc:                       # noqa: BLE001
        _put_message("error", T("Błąd zapisu: %s", "Save error: %s") % exc)
        return _redirect(base)
    render.invalidate_names()
    _put_message("ok", tr(words["added"]) % number)
    return _redirect(_detail_url(module_id, spec, [number]))


def _row_delete(module_id):
    """POST preview (pola "pk"), GET ekran potwierdzenia, POST save / cancel."""
    spec = _row_spec(module_id)
    if spec is None:
        return _missing_module()
    words = ROW_KINDS[module_id]
    key = words["key"]
    request = db.ns().request
    base = "/editsql/%s/delete" % module_id
    back = "/editsql/%s" % module_id
    if str(request.method).upper() != "POST":
        token = request.args.get("preview")
        payload = safety.take(token, keep=True) if token else None
        if not _payload_ok(payload, module_id, spec, "delete"):
            _put_message("error", tr(words["delete_expired"]))
            return _redirect(back)
        rows = payload["rows"]
        count = len(rows)
        noun = i18n.plural(count, *words["forms"])
        body = "".join([
            pages.effect_html(spec["db"], spec["table"]),
            '<div class="esq-note esq-note-warn">%s</div>'
            % (T('Usuniesz <b>%d %s</b> z tabeli <b>%s.%s</b>. '
                 '<b>Nic nie zostało jeszcze usunięte</b> - sprawdź listę i potwierdź. Usunięcie trafi do '
                 'Historii zmian; jedno „Cofnij” przywróci wszystkie te wiersze naraz.',
                 'You are about to delete <b>%d %s</b> from the table <b>%s.%s</b>. '
                 '<b>Nothing has been deleted yet</b> - check the list and confirm. The deletion goes '
                 'into the Change history; one “Undo” brings all these rows back at once.')
               % (count, noun, render._esc(spec["db"]), render._esc(spec["table"]))),
            words["delete_notes"](rows), words["rows_table"](rows),
            '<div id="register"><form method="post" action="%s">%s'
            '<input type="hidden" name="token" value="%s" />%s</form></div>'
            % (render._esc(base), render.csrf_input(), render._esc(token),
               render.actions(((T("Usuń %d %s", "Delete %d %s") % (count, noun),
                                "danger", 'name="action" value="save"'),
                               (T("Anuluj", "Cancel"), "plain", 'name="action" value="cancel"'))))])
        title = T("Podgląd usunięcia", "Preview of the deletion")
        return render.page(title, body, active=module_id,
                           messages_list=_take_messages(),
                           crumbs=[(spec["title"], back), (title, None)])

    action = str(request.form.get("action") or "preview")
    if action == "cancel":
        safety.take(request.form.get("token") or "")
        _put_message("info", T("Nic nie zostało usunięte.", "Nothing was deleted."))
        return _redirect(back)
    if action == "save":
        payload = safety.take(request.form.get("token") or "")
        if not _payload_ok(payload, module_id, spec, "delete"):
            _put_message("error", tr(words["delete_save_expired"]))
            return _redirect(back)
        try:
            # The note is history data and stays as it has always been written.
            count = safety.delete_rows(spec["db"], spec["table"], payload["rows"],
                                       pages._admin_name(), note=words["note_delete"])
        except safety.Conflict as exc:
            _put_message("error", T("Nic nie usunięto: %s", "Nothing deleted: %s") % exc)
            return _redirect(back)
        except (safety.Denied, safety.Invalid) as exc:
            _put_message("error", T("Nie mogę usunąć: %s", "Cannot delete: %s") % exc)
            return _redirect(back)
        except Exception as exc:                   # noqa: BLE001
            _put_message("error", T("Błąd zapisu: %s", "Save error: %s") % exc)
            return _redirect(back)
        render.invalidate_names()
        _put_message("ok", T("Usunięto %d %s. Cofniesz to jednym „Cofnij” w Historii zmian.",
                             "Deleted %d %s. One “Undo” in the Change history brings them back.")
                     % (count, i18n.plural(count, *words["forms"])))
        return _redirect(back)

    # --- podglad: zaznaczone wiersze -> pelne wiersze trzymane na serwerze ----
    getter = getattr(request.form, "getlist", None)
    raw = getter("pk") if getter else [request.form.get("pk")]
    keys = []
    for value in raw or ():
        text = str(value or "").strip()
        if not safety._DIGITS.match(text):
            _put_message("error", tr(words["bad_number"]) % text[:20])
            return _redirect(back)
        if int(text) not in keys:
            keys.append(int(text))
    if not keys:
        _put_message("error", tr(words["select"]))
        return _redirect(back)
    if len(keys) > ROWS_BATCH_MAX:
        _put_message("error", tr(words["at_most"]) % ROWS_BATCH_MAX)
        return _redirect(back)
    ok, reason = schema.writable(spec["db"], spec["table"])
    if not ok:
        _put_message("error", T("Nie mogę usunąć: %s", "Cannot delete: %s") % reason)
        return _redirect(back)
    found = {int(row[key]): row for row in (safety.decode_row(spec["tbl"], r) for r in db.query(
        "SELECT * FROM %s WHERE %s IN (%s)" % (db.qt(spec["db"], spec["table"]), db.qi(key),
                                               ",".join(["%s"] * len(keys))), tuple(keys)))}
    missing = [k for k in keys if k not in found]
    if missing:
        _put_message("error", tr(words["missing"]) % ", ".join("#%d" % k for k in missing))
        return _redirect(back)
    token = safety.stash({"module": module_id, "db": spec["db"], "table": spec["table"],
                          "op": "delete", "pk": keys, "rows": [found[k] for k in keys]})
    return _redirect(base + "?preview=" + token)


def _url_quote(value):
    import urllib.parse
    return urllib.parse.quote(str(value), safe="")


# -----------------------------------------------------------------------------
#  Rejestracja
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
#  Haslo do edytora
#
#  Edytor zmienia dane gry, wiec ZAWSZE pyta o haslo panelu administratora -
#  takze na instalacji lokalnej, gdzie sam panel admina otwiera sie bez hasla
#  (local_open). Haslo jest to samo co do panelu (check_pass z admin_panel.py,
#  PBKDF2 z m2panel.conf); kto wpisal je juz przy logowaniu do panelu
#  (session["auth"]), nie jest pytany drugi raz. Blokada po 5 nieudanych probach
#  jest wspolna z logowaniem do panelu (FAILS / MAX_FAIL / LOCK_SEC).
# -----------------------------------------------------------------------------
AUTH_KEY = "editsql_auth"
AUTH_IDLE = 8 * 3600                      # po 8 h bezczynnosci trzeba wpisac haslo znowu


def _authorized():
    import time
    session = db.ns().session
    if session.get("auth"):
        return True
    stamp = session.get(AUTH_KEY)
    try:
        stamp = float(stamp or 0)
    except (TypeError, ValueError):
        stamp = 0
    if stamp and 0 <= time.time() - stamp < AUTH_IDLE:
        if time.time() - stamp > 300:      # odswiezamy rzadko, zeby nie pisac ciasteczka co klik
            session[AUTH_KEY] = time.time()
        return True
    session.pop(AUTH_KEY, None)
    return False


def _safe_next(target):
    target = str(target or "")
    # /drops is the panel's chest and drop editor (admin_panel.py), behind
    # this same password: it changes game data as this editor does.
    if (target.startswith("/editsql") or target.startswith("/drops")) \
            and not target.startswith("//") and "\\" not in target:
        return target.rstrip("?")
    return "/editsql"


def _login_page(target, status=401):
    panel = db.ns()
    local = False
    try:
        local = bool(panel.local_open())
    except Exception:                              # noqa: BLE001
        local = False
    hint = (T("Na tej instalacji panel administratora otwiera się bez hasła, ale edytor bazy "
              "zawsze o nie pyta. Nie znasz hasła? Ustaw nowe w <a href=\"/admin\">Panelu "
              "administratora</a>, w ramce „Hasło administratora”.",
              "On this installation the admin panel opens without a password, but the database "
              "editor always asks for it. Don't know it? Set a new one in the <a href=\"/admin\">"
              "Admin panel</a>, in the “Admin password” box.") if local else
            T("To samo hasło, którym logujesz się do panelu administratora. Nie znasz go? "
              "Zobacz stronę <a href=\"/?s=admin\">Hasło panelu admina</a>.",
              "The same password you log in to the admin panel with. Don't know it? "
              "See the <a href=\"/?s=admin\">Admin panel password</a> page."))
    body = ('<div class="esq-login"><div id="register"><form method="post" action="/editsql/login">%s'
            '<input type="hidden" name="next" value="%s" />'
            '<p class="esq-lead">%s</p>'
            '<div class="esq-field"><label for="esq-pw"><span class="esq-label">%s</span></label>'
            '<input type="password" id="esq-pw" name="pw" '
            'autocomplete="current-password" required autofocus /></div>'
            '%s<p class="esq-hint">%s</p></form></div></div>'
            % (render.csrf_input(), render._esc(_safe_next(target)),
               T('Edytor bazy danych zmienia dane gry, dlatego jest chroniony '
                 '<b>hasłem panelu administratora</b>.',
                 'The database editor changes the game\'s data, so it is protected by '
                 '<b>the admin panel\'s password</b>.'),
               render._esc(T("Hasło panelu administratora", "Admin panel password")),
               render.actions(((T("Wejdź do edytora", "Enter the editor"), "primary", ""),)), hint))
    return render.page(T("Logowanie do edytora", "Log in to the editor"), body, found={},
                       messages_list=_take_messages(), crumbs=[]), status


def _login():
    # Serialize attempts in this module so concurrent requests cannot lose a
    # failed-attempt increment while the password hash is being checked.
    with safety._lock:
        return _login_locked()


def _login_locked():
    import time
    panel = db.ns()
    request = panel.request
    if str(request.method).upper() != "POST":
        if _authorized():
            return _redirect(_safe_next(request.args.get("next")))
        return _login_page(request.args.get("next"), status=200)
    target = _safe_next(request.form.get("next"))
    fails = panel.get("FAILS")
    max_fail = panel.get("MAX_FAIL") or 5
    lock_sec = panel.get("LOCK_SEC") or 900
    ip = request.remote_addr
    if fails is not None:
        count, lock = fails.get(ip, [0, 0])
        if time.time() < lock:
            _put_message("error", T("Za dużo nieudanych prób. Spróbuj ponownie za %d min.",
                                    "Too many failed attempts. Try again in %d min.")
                         % max(1, int((lock - time.time()) // 60) + 1))
            return _login_page(target)
    check = panel.get("check_pass")
    ok = False
    try:
        ok = bool(check and check(request.form.get("pw", "")))
    except Exception:                              # noqa: BLE001 - brak hasla w konfiguracji = brak wejscia
        ok = False
    if ok:
        if fails is not None:
            fails.pop(ip, None)
        panel.session[AUTH_KEY] = time.time()
        return _redirect(target)
    if fails is not None:
        count, _lock = fails.get(ip, [0, 0])
        count += 1
        fails[ip] = [count, time.time() + lock_sec if count >= max_fail else 0]
    time.sleep(1.0)
    _put_message("error", T("Nieprawidłowe hasło.", "Wrong password."))
    return _login_page(target)


def _logout():
    panel = db.ns()
    panel.session.pop(AUTH_KEY, None)
    _put_message("ok", T("Wylogowano z edytora bazy danych.", "Logged out of the database editor."))
    return _redirect("/editsql/login")


def _protect(view):
    """Kazda trasa edytora (poza logowaniem) wymaga hasla panelu."""
    import functools

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if _authorized():
            return view(*args, **kwargs)
        request = db.ns().request
        path = str(getattr(request, "path", "") or "")
        if path.startswith("/editsql/api/"):
            try:
                from flask import Response
                return Response('{"html": "", "error": "login"}', status=401,
                                mimetype="application/json")
            except Exception:                      # noqa: BLE001
                return "", 401
        if str(request.method).upper() == "POST":
            _put_message("error", T("Sesja edytora wygasła - zaloguj się ponownie. "
                                    "Zmiany z formularza nie zostały zapisane.",
                                    "The editor's session has expired - log in again. "
                                    "The form's changes were not saved."))
            return _redirect("/editsql/login?next=" + _url_quote(path))
        full = path
        query = getattr(request, "query_string", b"") or b""
        if query:
            full += "?" + (query.decode("utf-8", "replace") if isinstance(query, bytes) else str(query))
        return _login_page(full)
    return wrapped


# -----------------------------------------------------------------------------
#  Rejestracja
# -----------------------------------------------------------------------------
def init(module):
    """Wolane raz z admin_panel.py: editsql.init(globals())."""
    if _registered["done"]:
        raise RuntimeError("Editor package already installed")
    db.install(module)
    panel = db.ns()
    app = panel.app

    def add(rule, endpoint, view, methods=("GET",), protect=True):
        app.add_url_rule(rule, endpoint, _protect(view) if protect else view,
                         methods=list(methods))

    add("/editsql/login", "editsql_login", _login, ("GET", "POST"), protect=False)
    add("/editsql/logout", "editsql_logout", _logout, protect=False)
    add("/editsql", "editsql_home", _home)
    add("/editsql/", "editsql_home_slash", _home)
    add("/editsql/api/name", "editsql_api_name", _api_name)
    add("/editsql/structure", "editsql_structure", _structure)
    add("/editsql/structure/<db_name>", "editsql_structure_db", _structure)
    add("/editsql/structure/<db_name>/<table_name>", "editsql_structure_table", _structure)
    add("/editsql/history", "editsql_history", _history, ("GET", "POST"))
    add("/editsql/apply", "editsql_apply", _apply, ("GET", "POST"))
    add("/editsql/labels", "editsql_labels", _labels, ("GET", "POST"))
    add("/editsql/<module_id>", "editsql_module", _module)
    # Tylko moduly z spec["rows"]; reszta dostaje 404 (_row_spec).
    add("/editsql/<module_id>/new", "editsql_row_new", _row_new, ("GET", "POST"))
    add("/editsql/<module_id>/delete", "editsql_row_delete", _row_delete, ("GET", "POST"))
    add("/editsql/<module_id>/<db_name>/<path:pk_path>", "editsql_detail", _detail,
        ("GET", "POST"))
    _registered["done"] = True
    return app


def registered():
    return _registered["done"]
