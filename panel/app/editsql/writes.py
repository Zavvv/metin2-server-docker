"""Transactional editor mutations, including their audit and undo markers.

Read and check the row under the same InnoDB lock as the write. This also
locks matching ranges for logical keys, so a concurrent duplicate cannot
silently make a one-row update ambiguous.

The messages here have always been written "Polish / English"; a Polish reader
keeps them whole, an English one gets the English half (i18n.bilingual).
"""
import json
import uuid

from . import db, safety, schema
from .i18n import bilingual as _say


def _table(database, name, logical=None, insert=False):
    table = safety.whitelist(database, name, logical, for_insert=insert)
    if not db.is_transactional(database, name):
        raise safety.Denied(_say("Tabela wymaga silnika InnoDB / This table requires InnoDB.",
                                 "This table requires InnoDB."))
    db.ensure_history()
    if not db.is_transactional(db.HISTORY_DB, db.HISTORY_TABLE):
        raise safety.Denied(_say("Historia wymaga InnoDB / History requires InnoDB.",
                                 "History requires InnoDB."))
    # A failed backup blocks mutation. DDL happens before opening the write TX.
    db.snapshot_table(database, name, "before /editsql mutation")
    return table


def _where(names):
    return " AND ".join("%s <=> %%s" % db.qi(n) for n in names)


def _row(tx, table, names, values):
    if not names or len(names) != len(values):
        raise safety.Denied(_say("Nieprawidłowy klucz / Invalid row key.", "Invalid row key."))
    for name in names:
        safety.column(table, name)
    rows = tx.query("SELECT * FROM %s WHERE %s FOR UPDATE"
                    % (db.qt(table['db'], table['name']), _where(names)), tuple(values))
    if len(rows) != 1:
        raise safety.Conflict(_say("Klucz wskazuje %d wierszy / Row key matches %d rows."
                                   % (len(rows), len(rows)), "Row key matches %d rows." % len(rows)))
    return safety.decode_row(table, rows[0])


def _history_value(value, col):
    if isinstance(value, (bytes, bytearray)):
        return db.decode(value, col.get('charset'))
    return value


def apply_changes(db_name, table_name, pk_values, changes, admin, note='', verify=True,
                  logical_key=None):
    if not changes:
        return 0
    table = _table(db_name, table_name, logical_key)
    names = safety.key_columns(table, logical_key or schema.logical_key(db_name, table_name))
    blocked = safety.locked_columns(db_name, table_name) | set(names) | set(table['pk'])
    checked = []
    for change in changes:
        col = safety.column(table, change['column'])
        if col['name'] in blocked:
            raise safety.Denied(_say("Pole tylko do odczytu / Read-only field: ",
                                     "Read-only field: ") + col['name'])
        _, value, _ = safety.validate(col, _history_value(change['new'], col))
        # The game's own rules (a crafting recipe the db core can parse) are
        # checked again here, not only in the preview that built the change.
        value = safety.column_rule(table, col, value)
        checked.append((col, change['old'], value))
    with db.Tx() as tx:
        current = _row(tx, table, names, pk_values)
        # Verification is mandatory, even if a caller supplies verify=False.
        if any(not safety._same(current.get(c['name']), old) for c, old, new in checked):
            raise safety.Conflict(_say("Wiersz zmienił się po podglądzie / Row changed after preview.",
                                       "Row changed after preview."))
        if (db_name, table_name) == ITEMSHOP:
            # The offer as the edit leaves it must be one the game can sell,
            # judged under the lock with the item share-locked to the commit.
            after = dict(current)
            after.update((c['name'], v) for c, old, v in checked)
            _itemshop_refs(tx, after, strict=True)
        sql = "UPDATE %s SET %s WHERE %s" % (
            db.qt(db_name, table_name),
            ', '.join('%s=%s' % (db.qi(c['name']), safety.placeholder_for(c))
                      for c, old, new in checked), _where(names))
        changed = tx.execute(sql, tuple([v for c, old, v in checked] + list(pk_values)))
        if changed != 1:
            raise safety.Conflict(_say("Zapis nie zmienił jednego wiersza / Write did not change one row.",
                                       "Write did not change one row."))
        stored = _row(tx, table, names, pk_values)
        db.record_history(admin, db_name, table_name, safety.pk_json(table, current, names),
                          [(c['name'], current.get(c['name']), stored.get(c['name']))
                           for c, old, v in checked], uuid.uuid4().hex, note=note, tx=tx)
    return len(checked)


SHOP_KEY = ('shop_vnum', 'item_vnum', 'count')


def _shop(table):
    if (table['db'], table['name']) != ('world', 'shop_item'):
        raise safety.Denied(_say("Dodawanie/usuwanie tylko dla sklepów / Row changes are limited to shops.",
                                 "Row changes are limited to shops."))
    if set(table['by_name']) != set(SHOP_KEY):
        raise safety.Denied(_say("Nieobsługiwany schemat shop_item / Unsupported shop_item schema.",
                                 "Unsupported shop_item schema."))


def _shop_values(table, values):
    _shop(table)
    if set(values) != set(SHOP_KEY):
        raise safety.Denied(_say("Wymagany pełny wiersz sklepu / Complete shop row required.",
                                 "Complete shop row required."))
    out = {}
    for name in SHOP_KEY:
        _, value, _ = safety.validate(safety.column(table, name), values[name])
        if value is None or value <= 0:
            raise safety.Invalid(_say("Wartości sklepu muszą być dodatnie / Shop values must be positive.",
                                      "Shop values must be positive."))
        out[name] = value
    return out


def _shop_write(tx, table, values, insert):
    params = tuple(values[n] for n in SHOP_KEY)
    rows = tx.query("SELECT * FROM %s WHERE %s FOR UPDATE" % (
        db.qt(table['db'], table['name']), _where(SHOP_KEY)), params)
    if insert:
        if rows:
            raise safety.Conflict(_say("Pozycja już istnieje / Shop row already exists.",
                                       "Shop row already exists."))
        # Do not restore a dangling reference when its parent/item was removed.
        for name, target in (('shop_vnum', 'shop'), ('item_vnum', 'item_proto')):
            if len(tx.query('SELECT vnum FROM %s WHERE vnum=%%s LOCK IN SHARE MODE'
                            % db.qt('world', target), (values[name],))) != 1:
                raise safety.Conflict(_say("Brak sklepu lub przedmiotu / Shop or item no longer exists.",
                                           "Shop or item no longer exists."))
        changed = tx.execute("INSERT INTO %s (%s) VALUES (%%s,%%s,%%s)" % (
            db.qt(table['db'], table['name']), ','.join(db.qi(n) for n in SHOP_KEY)), params)
    else:
        if len(rows) != 1:
            raise safety.Conflict(_say("Niejednoznaczna pozycja / Shop row is missing or duplicated.",
                                       "Shop row is missing or duplicated."))
        changed = tx.execute("DELETE FROM %s WHERE %s" % (
            db.qt(table['db'], table['name']), _where(SHOP_KEY)), params)
    if changed != 1:
        raise safety.Conflict(_say("Oczekiwano jednego wiersza / Expected exactly one changed row.",
                                   "Expected exactly one changed row."))


def insert_row(db_name, table_name, values, admin, note=''):
    if (db_name, table_name) == CRAFTING:
        return _crafting_insert(values, admin, note)
    if (db_name, table_name) == ITEMSHOP:
        return _itemshop_insert(values, admin, note)
    table = _table(db_name, table_name, insert=True)
    values = _shop_values(table, values)
    with db.Tx() as tx:
        _shop_write(tx, table, values, True)
        db.record_history(admin, db_name, table_name, json.dumps(values),
                          [('item_vnum', None, str(values['item_vnum']))], uuid.uuid4().hex,
                          operation='insert', note=note, tx=tx)
    return True


def delete_row(db_name, table_name, pk_values, admin, note='', logical_key=None):
    table = _table(db_name, table_name, SHOP_KEY)
    if len(pk_values) != len(SHOP_KEY):
        raise safety.Denied(_say("Wymagany pełny klucz sklepu / Complete shop key required.",
                                 "Complete shop key required."))
    values = _shop_values(table, dict(zip(SHOP_KEY, pk_values)))
    with db.Tx() as tx:
        _shop_write(tx, table, values, False)
        db.record_history(admin, db_name, table_name, json.dumps(values),
                          [('item_vnum', str(values['item_vnum']), None)], uuid.uuid4().hex,
                          operation='delete', note=note, tx=tx)
    return True


# --- Crafting recipes (world.crafting_proto): whole-row inserts and deletes ---
#
# A recipe is one row keyed by its vnum. Its history entry carries the whole
# row as JSON in a single column '*', so undoing a delete puts back every
# column exactly as it was read under the lock, and undoing an insert removes
# the row only while it still is what was inserted. A batch delete is one
# transaction with one txid, and its undo restores the whole batch at once.
CRAFTING = safety.CRAFTING
CRAFTING_KEY = ('vnum',)
CRAFTING_BATCH_MAX = 200
_ROW_TYPES = ('tinyint', 'smallint', 'mediumint', 'int', 'bigint',
              'char', 'varchar', 'text', 'tinytext', 'mediumtext', 'longtext')


def _crafting(table):
    """Only the reviewed recipe schema: vnum key, plain integer and text columns."""
    if (table['db'], table['name']) != CRAFTING:
        raise safety.Denied(_say("Dodawanie/usuwanie przepisów tylko w world.crafting_proto / "
                                 "Recipe rows are limited to world.crafting_proto.",
                                 "Recipe rows are limited to world.crafting_proto."))
    if (tuple(table['pk']) != CRAFTING_KEY
            or not {'vnum', 'item_vnum', 'count', 'recipe'} <= set(table['by_name'])):
        raise safety.Denied(_say("Nieobsługiwany schemat crafting_proto / "
                                 "Unsupported crafting_proto schema.",
                                 "Unsupported crafting_proto schema."))
    for col in table['columns']:
        if (col['auto'] or col.get('extra', '').startswith('on update')
                or col['data_type'] not in _ROW_TYPES or col['choices'] is not None):
            raise safety.Denied(_say("Nieobsługiwana kolumna crafting_proto / Unsupported crafting_proto "
                                     "column: ", "Unsupported crafting_proto column: ") + col['name'])
    return table


def _row_json(table, row):
    """The stored row as JSON text: integers stay numbers, text is decoded per column."""
    out = {}
    for col in table['columns']:
        value = row.get(col['name'])
        if value is not None and not isinstance(value, int):
            value = str(_history_value(value, col))
        out[col['name']] = value
    return json.dumps(out, ensure_ascii=False)


def _row_from_json(table, text):
    data = json.loads(text or 'null')
    if not isinstance(data, dict) or set(data) != set(table['by_name']):
        raise safety.Denied(_say("Schemat tabeli zmienił się od zapisu - nie cofam / "
                                 "The table schema changed since this entry was written.",
                                 "The table schema changed since this entry was written."))
    return {col['name']: _restore(col, None if data[col['name']] is None else str(data[col['name']]))
            for col in table['columns']}


def _recipe_vnums(table, value, strict):
    text = _history_value(value, table['by_name']['recipe'])
    if strict:
        return [vnum for vnum, _count in safety.parse_recipe(text)]
    # A restore puts back what was there; read its materials as the db core does.
    numbers = [part.strip() for part in str(text or '').split(',')]
    return [int(numbers[i]) for i in range(0, len(numbers) - 1, 2)
            if safety._DIGITS.match(numbers[i])]


def _crafting_refs(tx, table, values, strict=True):
    """The result and every material must be item_proto rows, share-locked to commit."""
    items = schema.table('world', 'item_proto') or schema.table('player', 'item_proto')
    if items is None:
        raise safety.Denied(_say("Brak item_proto - nie sprawdzę przedmiotów / item_proto is missing.",
                                 "item_proto is missing."))
    wanted = {int(values['item_vnum'])} | set(_recipe_vnums(table, values['recipe'], strict))
    wanted = sorted(v for v in wanted if v > 0)
    rows = tx.query('SELECT vnum FROM %s WHERE vnum IN (%s) LOCK IN SHARE MODE'
                    % (db.qt(items['db'], items['name']), ','.join(['%s'] * len(wanted))),
                    tuple(wanted)) if wanted else []
    missing = sorted(set(wanted) - {int(r['vnum']) for r in rows})
    if missing or int(values['item_vnum']) <= 0:
        which = ", ".join(map(str, missing)) or values['item_vnum']
        raise safety.Conflict(_say("Nie ma przedmiotu %s w item_proto / Item does not exist: %s"
                                   % (which, which), "Item does not exist: %s" % which))


def _crafting_values(table, values):
    """Re-validate a previewed row: every column, its type and the game's rules."""
    names = [col['name'] for col in table['columns']]
    if set(values) != set(names):
        raise safety.Denied(_say("Wymagany pełny wiersz przepisu / Complete recipe row required.",
                                 "Complete recipe row required."))
    out = {}
    for col in table['columns']:
        _, value, _ = safety.validate(col, _history_value(values[col['name']], col))
        out[col['name']] = safety.column_rule(table, col, value)
    return out


def _crafting_put(tx, table, values, strict):
    vnum = values['vnum']
    if tx.query('SELECT vnum FROM %s WHERE %s FOR UPDATE'
                % (db.qt(table['db'], table['name']), _where(CRAFTING_KEY)), (vnum,)):
        raise safety.Conflict(_say("Przepis #%s już istnieje / Recipe #%s already exists." % (vnum, vnum),
                                   "Recipe #%s already exists." % vnum))
    _crafting_refs(tx, table, values, strict)
    cols = table['columns']
    changed = tx.execute('INSERT INTO %s (%s) VALUES (%s)' % (
        db.qt(table['db'], table['name']), ','.join(db.qi(c['name']) for c in cols),
        ','.join(safety.placeholder_for(c) for c in cols)), tuple(values[c['name']] for c in cols))
    if changed != 1:
        raise safety.Conflict(_say("Oczekiwano jednego wiersza / Expected exactly one changed row.",
                                   "Expected exactly one changed row."))
    return _row(tx, table, CRAFTING_KEY, [vnum])


def _crafting_take(tx, table, expected, what):
    """`what` = (Polish, English): when the recipe was expected unchanged."""
    current = _row(tx, table, CRAFTING_KEY, [expected['vnum']])
    for col in table['columns']:
        if not safety._same(current.get(col['name']), _history_value(expected[col['name']], col)):
            raise safety.Conflict(_say("Przepis #%s zmienił się %s (%s) / Recipe changed: %s"
                                       % (expected['vnum'], what[0], col['name'], col['name']),
                                       "Recipe #%s changed %s (%s)"
                                       % (expected['vnum'], what[1], col['name'])))
    changed = tx.execute('DELETE FROM %s WHERE %s' % (db.qt(table['db'], table['name']),
                                                      _where(CRAFTING_KEY)), (expected['vnum'],))
    if changed != 1:
        raise safety.Conflict(_say("Oczekiwano jednego wiersza / Expected exactly one changed row.",
                                   "Expected exactly one changed row."))
    return current


def _crafting_insert(values, admin, note):
    table = _crafting(_table(CRAFTING[0], CRAFTING[1], insert=True))
    values = _crafting_values(table, values)
    with db.Tx() as tx:
        stored = _crafting_put(tx, table, values, strict=True)
        db.record_history(admin, CRAFTING[0], CRAFTING[1],
                          safety.pk_json(table, stored, CRAFTING_KEY),
                          [(safety.ROW_COLUMN, None, _row_json(table, stored))], uuid.uuid4().hex,
                          operation='insert', note=note, tx=tx)
    return True


def delete_rows(db_name, table_name, rows, admin, note=''):
    """Delete previewed whole rows in one transaction; each must still equal its preview.

    Recipes (world.crafting_proto) and ItemShop offers (common.itemshop_items);
    any other table is refused by the recipe's own schema check."""
    kind = _ROW_KINDS.get((db_name, table_name), _ROW_KINDS[CRAFTING])
    table = kind['check'](_table(db_name, table_name))
    kind['prepare']()
    names = set(table['by_name'])
    key = kind['key'][0]
    if not rows or len(rows) > CRAFTING_BATCH_MAX:
        raise safety.Denied(kind['say']['batch'](CRAFTING_BATCH_MAX))
    if any(set(row) != names for row in rows):
        raise safety.Denied(kind['say']['whole']())
    keys = [safety.validate(table['by_name'][key], row[key])[1] for row in rows]
    if len(set(keys)) != len(keys):
        raise safety.Denied(kind['say']['twice']())
    txid = uuid.uuid4().hex
    with db.Tx() as tx:
        # Lock in key order, so two batches touching the same rows queue
        # instead of deadlocking each other.
        for row in sorted(rows, key=lambda r: int(r[key])):
            current = kind['take'](tx, table, row, ("po podglądzie", "after the preview"))
            db.record_history(admin, db_name, table_name,
                              safety.pk_json(table, current, kind['key']),
                              [(safety.ROW_COLUMN, _row_json(table, current), None)], txid,
                              operation='delete', note=note, tx=tx)
    return len(rows)


def _undo_whole_rows(entry_id, operation, admin, kind):
    """Undo a whole-row insert or delete together with the rest of its batch (same txid)."""
    database, name = kind['table']
    table = kind['check'](_table(database, name, insert=(operation == 'delete')))
    kind['prepare']()
    undo_txid = uuid.uuid4().hex
    with db.Tx() as tx:
        locked = tx.query('SELECT * FROM player.editsql_history WHERE id=%s FOR UPDATE',
                          (int(entry_id),))
        if len(locked) != 1 or locked[0]['undone']:
            raise safety.Conflict(_say("Zmiana już cofnięta / Change was already undone.",
                                       "Change was already undone."))
        txid = db.decode(locked[0]['txid']) or ''
        group = locked
        if txid:
            group = tx.query('SELECT * FROM player.editsql_history WHERE txid=%s AND db_name=%s '
                             'AND table_name=%s AND operation=%s AND undone=0 ORDER BY id FOR UPDATE',
                             (txid, database, name, operation))
        if int(entry_id) not in [int(entry['id']) for entry in group]:
            raise safety.Conflict(_say("Wpis historii nie pasuje / History entry does not match.",
                                       "History entry does not match."))
        done = []
        for entry in group:
            if db.decode(entry['column_name']) != safety.ROW_COLUMN:
                raise safety.Denied(_say("Wpis nie opisuje całego wiersza / Entry is not a whole row.",
                                         "Entry is not a whole row."))
            text = db.decode(entry['new_value'] if operation == 'insert' else entry['old_value'])
            expected = _row_from_json(table, text)
            if operation == 'insert':
                kind['take'](tx, table, expected,
                             ("po dodaniu - najpierw cofnij późniejsze zmiany",
                              "after it was added - undo the later changes first"))
                columns = [(safety.ROW_COLUMN, text, None)]
            else:
                stored = kind['put'](tx, table, expected, strict=False)
                columns = [(safety.ROW_COLUMN, None, _row_json(table, stored))]
            db.record_history(admin, database, name, db.decode(entry['pk_json']), columns,
                              undo_txid, operation='undo', note='Undo #%s' % entry['id'], tx=tx,
                              undo_of=int(entry['id']))
            done.append(int(entry['id']))
        tx.execute('UPDATE player.editsql_history SET undone=1 WHERE id IN (%s)'
                   % ','.join(['%s'] * len(done)), tuple(done))
    count = len(done)
    if count == 1:
        return True, _say("Cofnięto zmianę / Change undone: #%s" % done[0],
                          "Change undone: #%s" % done[0])
    return True, kind['say']['together'](count, ", ".join("#%d" % i for i in done))


def _few(count):
    """Polish's "few" form: 2-4, 22-24... but not 12-14."""
    return 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14


_CRAFTING_SAY = {
    'batch': lambda most: _say("Od 1 do %d przepisów naraz / Between 1 and %d recipes at once."
                               % (most, most), "Between 1 and %d recipes at once." % most),
    'whole': lambda: _say("Wymagany pełny wiersz przepisu / Complete recipe row required.",
                          "Complete recipe row required."),
    'twice': lambda: _say("Przepis podany dwa razy / Duplicate recipe in the batch.",
                          "Duplicate recipe in the batch."),
    'together': lambda count, ids: _say(
        "Cofnięto razem %d %s z jednej operacji / Undone %d recipes together: %s"
        % (count, "przepisy" if _few(count) else "przepisów", count, ids),
        "Undone %d recipes together: %s" % (count, ids)),
}


# --- ItemShop offers (common.itemshop_items, mt2009): whole-row inserts and deletes ---
#
# Drip had no delete for an offer and zeroed one instead, and the game core
# that sent the zeroed rows died at every open of the ItemShop (7 October).
# An offer is one row keyed by its index, and goes the recipe's way: the whole
# row as JSON in one history entry (column '*'), a batch delete one txid and
# one undo, a restore only while the item still exists. One thing more: the
# migrator puts its own offers (6-8, the wedding page 201-211, 617) back at
# every start with INSERT IGNORE, so a deleted offer keeps its index in
# common.m2_itemshop_removed - written in the same transaction, taken out when
# the index comes back (an insert, or the undo of the delete) - and the
# migrator does not put back what is marked there (port/migratorify.py,
# itemshop_seed). Both make the table with the same definition.
ITEMSHOP = safety.ITEMSHOP
ITEMSHOP_KEY = ('index',)
ITEMSHOP_COLUMNS = ('index', 'vnum', 'count', 'price', 'currency', 'minLevel')
REMOVED = ('common', 'm2_itemshop_removed')
REMOVED_DDL = ('CREATE TABLE IF NOT EXISTS `common`.`m2_itemshop_removed` ('
               '`index` INT NOT NULL PRIMARY KEY, '
               'removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB')

_ITEMSHOP_SAY = {
    'batch': lambda most: _say("Od 1 do %d pozycji naraz / Between 1 and %d offers at once."
                               % (most, most), "Between 1 and %d offers at once." % most),
    'whole': lambda: _say("Wymagany pełny wiersz pozycji / Complete offer row required.",
                          "Complete offer row required."),
    'twice': lambda: _say("Pozycja podana dwa razy / Duplicate offer in the batch.",
                          "Duplicate offer in the batch."),
    'together': lambda count, ids: _say(
        "Cofnięto razem %d %s z jednej operacji / Undone %d offers together: %s"
        % (count, "pozycje" if _few(count) else "pozycji", count, ids),
        "Undone %d offers together: %s" % (count, ids)),
}


def _itemshop(table):
    """Only the reviewed offer schema: index key, integer columns and the currency ENUM."""
    if (table['db'], table['name']) != ITEMSHOP:
        raise safety.Denied(_say("Dodawanie/usuwanie pozycji tylko w common.itemshop_items / "
                                 "Offer rows are limited to common.itemshop_items.",
                                 "Offer rows are limited to common.itemshop_items."))
    if tuple(table['pk']) != ITEMSHOP_KEY or not set(ITEMSHOP_COLUMNS) <= set(table['by_name']):
        raise safety.Denied(_say("Nieobsługiwany schemat itemshop_items / "
                                 "Unsupported itemshop_items schema.",
                                 "Unsupported itemshop_items schema."))
    for col in table['columns']:
        enum = bool(col['enum']) and not col['set']
        if (col['auto'] or col.get('extra', '').startswith('on update')
                or (col['data_type'] not in _ROW_TYPES and not enum)
                or (col['choices'] is not None and not enum)):
            raise safety.Denied(_say("Nieobsługiwana kolumna itemshop_items / Unsupported itemshop_items "
                                     "column: ", "Unsupported itemshop_items column: ") + col['name'])
    return table


def _itemshop_marks():
    """The removal marks the migrator reads; made before the write transaction (DDL commits)."""
    db.ddl(REMOVED_DDL)
    if not db.is_transactional(*REMOVED):
        raise safety.Denied(_say("Tabela common.m2_itemshop_removed wymaga InnoDB / "
                                 "common.m2_itemshop_removed requires InnoDB.",
                                 "common.m2_itemshop_removed requires InnoDB."))


def _itemshop_refs(tx, row, strict):
    """The offer's item must be an item_proto row, share-locked to the commit.

    `strict` judges the whole offer as safety.offer_problems does (index, vnum
    and count from 1, the count within the item's stack); a restore (strict
    False) puts back what was there and stops only for an item gone since."""
    items = schema.table('world', 'item_proto') or schema.table('player', 'item_proto')
    if items is None:
        raise safety.Denied(_say("Brak item_proto - nie sprawdzę przedmiotów / item_proto is missing.",
                                 "item_proto is missing."))
    vnum = int(row['vnum'])
    has_stack = 'stack' in items['by_name']
    found = tx.query('SELECT %s AS s FROM %s WHERE %s=%%s LOCK IN SHARE MODE'
                     % (db.qi('stack') if has_stack else 'NULL', db.qt(items['db'], items['name']),
                        db.qi('vnum')), (vnum,)) if vnum > 0 else []
    if not strict:
        if vnum > 0 and not found:
            raise safety.Conflict(_say("Nie ma przedmiotu %s w item_proto / Item does not exist: %s"
                                       % (vnum, vnum), "Item does not exist: %s" % vnum))
        return
    stack = found[0]['s'] if found else None
    problems = safety.offer_problems(vnum, int(row['count']), bool(found),
                                     None if stack is None else int(stack))
    if int(row['index']) < 1:
        problems.insert(0, _say("index: dozwolone od 1 (jest %s)" % row['index'],
                                "index: allowed from 1 (it is %s)" % row['index']))
    if problems:
        raise safety.Conflict("; ".join(problems))


def _whole_values(table, values, say):
    """Re-validate a previewed row: every column, its type and the game's rules."""
    names = [col['name'] for col in table['columns']]
    if set(values) != set(names):
        raise safety.Denied(say['whole']())
    out = {}
    for col in table['columns']:
        _, value, _ = safety.validate(col, _history_value(values[col['name']], col))
        out[col['name']] = safety.column_rule(table, col, value)
    return out


def _itemshop_put(tx, table, values, strict):
    index = values['index']
    if tx.query('SELECT %s FROM %s WHERE %s FOR UPDATE'
                % (db.qi('index'), db.qt(table['db'], table['name']), _where(ITEMSHOP_KEY)), (index,)):
        raise safety.Conflict(_say("Pozycja %s już istnieje / Offer %s already exists." % (index, index),
                                   "Offer %s already exists." % index))
    _itemshop_refs(tx, values, strict)
    cols = table['columns']
    changed = tx.execute('INSERT INTO %s (%s) VALUES (%s)' % (
        db.qt(table['db'], table['name']), ','.join(db.qi(c['name']) for c in cols),
        ','.join(safety.placeholder_for(c) for c in cols)), tuple(values[c['name']] for c in cols))
    if changed != 1:
        raise safety.Conflict(_say("Oczekiwano jednego wiersza / Expected exactly one changed row.",
                                   "Expected exactly one changed row."))
    # The index is the operator's again: the migrator may seed it.
    tx.execute('DELETE FROM %s WHERE %s=%%s' % (db.qt(*REMOVED), db.qi('index')), (index,))
    return _row(tx, table, ITEMSHOP_KEY, [index])


def _itemshop_take(tx, table, expected, what):
    """`what` = (Polish, English): when the offer was expected unchanged."""
    current = _row(tx, table, ITEMSHOP_KEY, [expected['index']])
    for col in table['columns']:
        if not safety._same(current.get(col['name']), _history_value(expected[col['name']], col)):
            raise safety.Conflict(_say("Pozycja %s zmieniła się %s (%s) / Offer changed: %s"
                                       % (expected['index'], what[0], col['name'], col['name']),
                                       "Offer %s changed %s (%s)"
                                       % (expected['index'], what[1], col['name'])))
    changed = tx.execute('DELETE FROM %s WHERE %s' % (db.qt(table['db'], table['name']),
                                                      _where(ITEMSHOP_KEY)), (expected['index'],))
    if changed != 1:
        raise safety.Conflict(_say("Oczekiwano jednego wiersza / Expected exactly one changed row.",
                                   "Expected exactly one changed row."))
    # Removed by the operator: the migrator does not seed it back.
    tx.execute('INSERT IGNORE INTO %s (%s) VALUES (%%s)' % (db.qt(*REMOVED), db.qi('index')),
               (expected['index'],))
    return current


def _itemshop_insert(values, admin, note):
    table = _itemshop(_table(ITEMSHOP[0], ITEMSHOP[1], insert=True))
    _itemshop_marks()
    values = _whole_values(table, values, _ITEMSHOP_SAY)
    with db.Tx() as tx:
        stored = _itemshop_put(tx, table, values, strict=True)
        db.record_history(admin, ITEMSHOP[0], ITEMSHOP[1],
                          safety.pk_json(table, stored, ITEMSHOP_KEY),
                          [(safety.ROW_COLUMN, None, _row_json(table, stored))], uuid.uuid4().hex,
                          operation='insert', note=note, tx=tx)
    return True


_ROW_KINDS = {
    CRAFTING: {'table': CRAFTING, 'key': CRAFTING_KEY, 'check': _crafting, 'prepare': lambda: None,
               'put': _crafting_put, 'take': _crafting_take, 'say': _CRAFTING_SAY},
    ITEMSHOP: {'table': ITEMSHOP, 'key': ITEMSHOP_KEY, 'check': _itemshop, 'prepare': _itemshop_marks,
               'put': _itemshop_put, 'take': _itemshop_take, 'say': _ITEMSHOP_SAY},
}


def _restore(col, text):
    if text is None:
        if not col['nullable']:
            raise safety.Invalid(_say("NULL nie jest dozwolone / NULL is not allowed.",
                                      "NULL is not allowed."))
        return None
    # Audit values are native DB values: retain empty strings and whitespace.
    if col['data_type'] in ('char', 'varchar', 'text', 'tinytext', 'mediumtext', 'longtext'):
        safety.validate(col, text)
        return safety._prepare(col, text)
    return safety.validate(col, text)[1]


def undo(entry_id, admin):
    entry = db.history_get(entry_id)
    if not entry or entry.get('undone'):
        return False, _say("Brak zmiany do cofnięcia / No change to undo.", "No change to undo.")
    database, name = db.decode(entry['db_name']), db.decode(entry['table_name'])
    operation = db.decode(entry['operation'])
    if (database, name) in _ROW_KINDS and operation in ('insert', 'delete'):
        try:
            return _undo_whole_rows(entry_id, operation, admin, _ROW_KINDS[(database, name)])
        except (safety.Conflict, safety.Denied, safety.Invalid, ValueError) as exc:
            return False, str(exc)
    try:
        table = _table(database, name, SHOP_KEY if operation in ('insert', 'delete') else None)
        with db.Tx() as tx:
            locked = tx.query('SELECT * FROM player.editsql_history WHERE id=%s FOR UPDATE',
                              (int(entry_id),))
            if len(locked) != 1 or locked[0]['undone']:
                raise safety.Conflict(_say("Zmiana już cofnięta / Change was already undone.",
                                           "Change was already undone."))
            entry = locked[0]
            key = json.loads(db.decode(entry['pk_json']))
            if operation in ('insert', 'delete'):
                values = _shop_values(table, key)
                _shop_write(tx, table, values, operation == 'delete')
                columns = [('item_vnum', db.decode(entry['new_value']), db.decode(entry['old_value']))]
            elif operation == 'update':
                names = safety.key_columns(table, schema.logical_key(database, name))
                if set(key) != set(names):
                    raise safety.Denied(_say("Klucz historii nie pasuje / History key does not match.",
                                             "History key does not match."))
                values = [key[n] for n in names]
                col = safety.column(table, db.decode(entry['column_name']))
                if col['name'] in safety.locked_columns(database, name) | set(names):
                    raise safety.Denied(_say("Pole tylko do odczytu / Read-only field.", "Read-only field."))
                current = _row(tx, table, names, values)
                new_text, old_text = db.decode(entry['new_value']), db.decode(entry['old_value'])
                expected = _restore(col, new_text)
                if not safety._same(current.get(col['name']), _history_value(expected, col)):
                    raise safety.Conflict(_say("Późniejsza zmiana blokuje cofnięcie / A later change "
                                               "prevents undo.", "A later change prevents undo."))
                value = _restore(col, old_text)
                changed = tx.execute('UPDATE %s SET %s=%s WHERE %s' % (
                    db.qt(database, name), db.qi(col['name']), safety.placeholder_for(col), _where(names)),
                    tuple([value] + values))
                if changed != 1:
                    raise safety.Conflict(_say("Cofnięcie nie zmieniło wiersza / Undo did not change the row.",
                                               "Undo did not change the row."))
                columns = [(col['name'], new_text, old_text)]
            else:
                raise safety.Denied(_say("Tej operacji nie można cofnąć / This operation cannot be undone.",
                                         "This operation cannot be undone."))
            db.record_history(admin, database, name, db.decode(entry['pk_json']), columns,
                              uuid.uuid4().hex, operation='undo', note='Undo #%s' % entry_id,
                              tx=tx, undo_of=int(entry_id))
            tx.execute('UPDATE player.editsql_history SET undone=1 WHERE id=%s', (int(entry_id),))
        return True, _say("Cofnięto zmianę / Change undone: #%s" % entry_id,
                          "Change undone: #%s" % entry_id)
    except (safety.Conflict, safety.Denied, safety.Invalid, ValueError) as exc:
        return False, str(exc)
