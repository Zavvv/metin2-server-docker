# =============================================================================
#  /editsql -- warstwa dostepu do bazy.
#
#  Trzy rzeczy, ktore musza byc zrobione inaczej niz w reszcie panelu:
#
#  1. KODOWANIE. Polaczenie jest utf8mb4 (parametry - takze polskie znaki
#     i wpisy historii - ida bez strat), ale wyniki przychodza jako SUROWE
#     BAJTY (character_set_results=binary). Kolumny w tej bazie sa w cp1250,
#     latin1, latin2 albo utf8mb3 - czesto w jednej tabeli trzy rozne - wiec
#     dekodujemy kazda kolumne jej wlasnym kodowaniem (decode_row). Gdyby
#     serwer konwertowal wyniki do latin1 (jak wczesniej), "Długi Miecz"
#     przychodzilby jako "D?ugi Miecz" - znak, ktorego latin1 nie ma, ginie
#     po stronie serwera i nie da sie go juz odzyskac.
#     Zapis tekstu: CONVERT(%s USING <charset kolumny>) z bajtami zakodowanymi
#     w kodowaniu kolumny.
#
#  2. TRANSAKCJE. db() w panelu ma autocommit=True. Edytor danych nie moze tego
#     miec: polowa zapisu to gorszy wynik niz brak zapisu. Wlasne polaczenie,
#     autocommit=False, jawne BEGIN/COMMIT/ROLLBACK.
#
#  3. BIALA LISTA. Nazwy tabel i kolumn NIGDY nie pochodza z zadania HTTP -
#     tylko z metamodelu (information_schema) zbudowanego przez schema.py.
#     Tutaj jest ostatnia linia obrony: qi() odrzuca wszystko, co nie jest
#     prostym identyfikatorem, a assert_table/assert_column sprawdzaja
#     czlonekstwo w metamodelu.
# =============================================================================

import re
import threading
import time

# Identyfikator, ktory wolno wstawic do SQL. Swiadomie wasko: bez kropek, bez
# backtickow, bez myslnikow. Nazwy tabel w tym projekcie to [a-z0-9_], a nazwy
# kolumn dodatkowo $ (nie ma ich tu, ale MySQL je dopuszcza).
_IDENT = re.compile(r"^[A-Za-z0-9_$]{1,64}$")

# Kolejnosc prob przy dekodowaniu bajtow, ktore przyszly z bazy bez informacji
# o kodowaniu (np. VARBINARY albo kolumna bez CHARACTER_SET_NAME). Ta sama
# kolejnosc co panel.log_text() - jedno miejsce w projekcie juz ja ustalilo.
_DECODE_CHAIN = ("utf-8", "cp1250", "latin2", "cp1252")

# Nazwy kodowan MySQL -> kodeki Pythona. MySQL-owe "latin1" to naprawde cp1252,
# a utf8mb4/utf8mb3 Python zna tylko jako utf-8.
_CODECS = {
    "utf8mb4": "utf-8", "utf8mb3": "utf-8", "utf8": "utf-8", "latin1": "cp1252",
    "latin2": "iso8859_2", "cp1250": "cp1250", "cp1251": "cp1251", "cp1256": "cp1256",
    "cp1257": "cp1257", "euckr": "euc_kr", "big5": "big5", "gbk": "gbk", "gb2312": "gb2312",
    "sjis": "shift_jis", "cp932": "cp932", "ujis": "euc_jp", "tis620": "tis_620",
    "ascii": "ascii", "binary": None,
}


def py_codec(charset):
    """Kodek Pythona dla kodowania MySQL (None dla binary/nieznanego)."""
    if not charset:
        return None
    name = str(charset).lower()
    if name in _CODECS:
        return _CODECS[name]
    return name

# Ile czasu trzymamy metamodel, zanim zapytamy information_schema ponownie.
SCHEMA_TTL = 300.0

_lock = threading.RLock()
_state = {"ns": None, "conn": None}


# -----------------------------------------------------------------------------
#  Namespace panelu (admin_panel przekazuje swoje globals() przez init())
# -----------------------------------------------------------------------------
class Namespace(object):
    """Leniwy dostep do zmiennych admin_panel.py.

    Leniwy, bo panel importuje ten modul na samym koncu swojego pliku: w chwili
    init() czesc stalych juz istnieje, ale nie chcemy polegac na kolejnosci.
    """

    def __init__(self, module):
        self._m = module if isinstance(module, dict) else vars(module)

    def __getattr__(self, name):
        try:
            return self._m[name]
        except KeyError:
            raise AttributeError(name)

    # Dostep jak do slownika: wygodny w kodzie i niezbedny w testach, gdzie
    # podmieniamy pojedyncze zmienne panelu (np. session, local_open).
    def __getitem__(self, name):
        return self._m[name]

    def __setitem__(self, name, value):
        self._m[name] = value

    def __contains__(self, name):
        return name in self._m

    def get(self, name, default=None):
        return self._m.get(name, default)

    def has(self, name):
        return name in self._m


def install(module):
    """Zapamietuje namespace panelu. Wolane raz z editsql.init()."""
    with _lock:
        _state["ns"] = Namespace(module)


def ns():
    m = _state["ns"]
    if m is None:
        raise RuntimeError("editsql: install() nie zostalo wywolane")
    return m


# -----------------------------------------------------------------------------
#  Polaczenie
# -----------------------------------------------------------------------------
def conf():
    """Konfiguracja bazy z panelu (m2panel.conf / M2PANEL_DB_*)."""
    c = ns().CONF
    return {
        "host": c.get("db_host", "127.0.0.1"),
        "user": c.get("db_user", ""),
        "password": c.get("db_pass", ""),
        "port": int(c.get("db_port", 3306) or 3306),
    }


def connect():
    """Nowe polaczenie edytora: utf8mb4 na wejsciu, surowe bajty na wyjsciu.

    Dlaczego nie panel.db(): bo tamto ma autocommit=True i wspoldzieli jedno
    ustawienie kodowania z reszta panelu. Edytor potrzebuje wlasnej transakcji.
    """
    pymysql = ns().pymysql
    c = conf()
    return pymysql.connect(host=c["host"], user=c["user"], password=c["password"],
                           port=c["port"], charset="utf8mb4", autocommit=False,
                           init_command="SET character_set_results = binary",
                           cursorclass=pymysql.cursors.DictCursor)


def query(sql, params=None):
    """SELECT na wlasnym polaczeniu; zawsze zamyka kursor. Zwraca liste dictow."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return list(cur.fetchall())


def scalar(sql, params=None, default=None):
    rows = query(sql, params)
    if not rows:
        return default
    row = rows[0]
    for value in row.values():
        return value
    return default


def server_alive():
    """(True, wersja) albo (False, komunikat). Uzywane przez dashboard."""
    try:
        rows = query("SELECT VERSION() AS v")
        return True, (rows[0]["v"] if rows else "")
    except Exception as exc:                      # noqa: BLE001 - komunikat na ekran
        return False, str(exc)


# -----------------------------------------------------------------------------
#  Identyfikatory i biale listy
# -----------------------------------------------------------------------------
def qi(ident):
    """Bezpieczna nazwa tabeli/kolumny do SQL. Wszystko inne -> wyjatek."""
    if not isinstance(ident, str) or not _IDENT.fullmatch(ident):
        from .i18n import T                        # i18n reads the panel through this module
        raise ValueError(T("niepoprawna nazwa identyfikatora: %r", "invalid identifier: %r") % (ident,))
    return "`" + ident + "`"


def qt(db_name, table):
    return qi(db_name) + "." + qi(table)


def qc(table, column):
    return qi(table) + "." + qi(column)


# -----------------------------------------------------------------------------
#  Bajty <-> tekst
# -----------------------------------------------------------------------------
def decode(value, charset=None):
    """Bajty z bazy na str. Nigdy nie rzuca - najgorszy przypadek to '?'."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        codec = py_codec(charset)
        if codec:
            try:
                return raw.decode(codec)
            except (LookupError, UnicodeDecodeError):
                pass
        for enc in _DECODE_CHAIN:
            try:
                return raw.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("cp1250", "replace")
    return value


def encode(text, charset):
    """Str na bajty w kodowaniu kolumny. Nieuzywane znaki -> '?' (jak MySQL)."""
    if text is None:
        return None
    if isinstance(text, (bytes, bytearray)):
        return bytes(text)
    return str(text).encode(py_codec(charset) or "cp1250", "strict")


def encodable(text, charset):
    """Czy tekst da sie zapisac w kodowaniu kolumny bez utraty znakow."""
    if text is None or isinstance(text, (bytes, bytearray)):
        return True
    try:
        str(text).encode(py_codec(charset) or "cp1250")
        return True
    except (LookupError, UnicodeEncodeError):
        return False


def is_text_column(col):
    """Czy kolumna jest tekstowa (a wiec wymaga kodowania przy zapisie)."""
    return bool(col.get("charset")) and col.get("data_type") not in (
        "binary", "varbinary", "blob", "tinyblob", "mediumblob", "longblob")


# -----------------------------------------------------------------------------
#  Transakcje
# -----------------------------------------------------------------------------
class Tx(object):
    """Kontekst transakcji: COMMIT na wyjsciu, ROLLBACK na wyjatku.

    Uzycie:
        with Tx() as tx:
            tx.execute("UPDATE ...", args)
            tx.execute("UPDATE ...", args)
    """

    def __init__(self):
        self.conn = None
        self.statements = []
        self.committed = False

    def __enter__(self):
        self.conn = connect()
        with self.conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        self.conn.begin()
        return self

    def query(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()

    def execute(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params or ())
            self.statements.append((sql, params))
            return cur.rowcount

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
                self.committed = True
            else:
                self.conn.rollback()
        finally:
            try:
                self.conn.close()
            except Exception:                      # noqa: BLE001
                pass
        return False


def ddl(sql, params=None):
    """DDL/poza transakcja (tworzy tabele audytu i snapshoty).

    DDL w MySQL wymusza COMMIT, wiec nie ma sensu trzymac go w Tx(); wazne, ze
    snapshot powstaje PRZED transakcja zmieniajaca dane.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            count = cur.rowcount
        conn.commit()
        return count


def table_engine(db_name, table):
    value = scalar("SELECT ENGINE FROM information_schema.TABLES "
                   "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (db_name, table))
    return decode(value) or ""


def is_transactional(db_name, table):
    """MyISAM nie zna transakcji - dla takich tabel edytor musi to powiedziec."""
    return table_engine(db_name, table).upper() == "INNODB"


def snapshot_table(db_name, table, reason, keep=8):
    """Kopia tabeli w konwencji operatora: <tabela>_editsql_<data>.

    Dokladnie tak, jak juz robi to wlasciciel tego serwera (item_proto_01_02,
    mob_proto_przed_rozjebaniem, skill_proto_copy_przed_zmianami_barabasza):
    CREATE TABLE ... AS SELECT *, z data i powodem w nazwie. Tworzymy ja raz na
    dobe na tabele; starsze niz `keep` usuwamy, zeby baza nie puchla.
    """
    stamp = time.strftime("%Y%m%d")
    name = "%s_editsql_%s" % (table, stamp)
    existing = scalar("SELECT COUNT(*) AS n FROM information_schema.TABLES "
                      "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (db_name, name), 0)
    if not existing:
        ddl("CREATE TABLE IF NOT EXISTS %s ENGINE=InnoDB AS SELECT * FROM %s"
            % (qt(db_name, name), qt(db_name, table)))
    _prune_snapshots(db_name, table, keep)
    return name


def _prune_snapshots(db_name, table, keep):
    rows = query(
        "SELECT TABLE_NAME AS n FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME LIKE %s ORDER BY TABLE_NAME DESC",
        (db_name, table + "\\_editsql\\_%"))
    names = [decode(row['n']) for row in rows]
    names = [name for name in names if re.fullmatch(re.escape(table) + r'_editsql_\d{8}', name or '')]
    for name in names[keep:]:
        if _IDENT.fullmatch(name):
            try:
                ddl("DROP TABLE " + qt(db_name, name))
            except Exception:                      # noqa: BLE001 - sprzatanie nie moze przerwac zapisu
                pass


# -----------------------------------------------------------------------------
#  Historia zmian (audyt + cofanie)
# -----------------------------------------------------------------------------
HISTORY_DB = "player"
HISTORY_TABLE = "editsql_history"

_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS `player`.`editsql_history` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `ts` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `admin` VARCHAR(64) NOT NULL DEFAULT '',
  `db_name` VARCHAR(64) NOT NULL,
  `table_name` VARCHAR(64) NOT NULL,
  `pk_json` VARCHAR(255) NOT NULL DEFAULT '',
  `column_name` VARCHAR(64) NOT NULL,
  `old_value` TEXT NULL,
  `new_value` TEXT NULL,
  `operation` VARCHAR(16) NOT NULL DEFAULT 'update',
  `status` VARCHAR(16) NOT NULL DEFAULT 'ok',
  `note` VARCHAR(255) NOT NULL DEFAULT '',
  `txid` VARCHAR(40) NOT NULL DEFAULT '',
  `undo_of` BIGINT UNSIGNED NULL,
  `undone` TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `ts_idx` (`ts`),
  KEY `table_idx` (`db_name`,`table_name`),
  KEY `tx_idx` (`txid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_history():
    """Tabela audytu - idempotentnie, jak schema/web_admin_schema.sql."""
    ddl(_HISTORY_DDL)


def record_history(admin, db_name, table, pk_json, changes, txid, operation="update",
                   status="ok", note="", tx=None, undo_of=None):
    """Zapisuje jedna zmiane na kolumne. changes = [(kolumna, stara, nowa), ...].

    `tx` to transakcja, w ktorej wlasnie zmieniamy dane. Wtedy wpisy ida TYM
    SAMYM polaczeniem i COMMIT-em: albo zmiana i jej slad, albo nic. Wersja
    "po commicie" zostawialaby niezalogowana zmiane, gdyby zapis historii sie
    nie powiodl - a wtedy cofniecie nie mialoby czego cofnac.
    """
    if not changes:
        return 0
    sql = ("INSERT INTO `player`.`editsql_history` "
           "(admin, db_name, table_name, pk_json, column_name, old_value, new_value, "
           " operation, status, note, txid, undo_of) "
           "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
    if len(pk_json) > 255:
        raise ValueError('History row key is too long')
    rows = [(admin[:64], db_name, table, pk_json, column,
             _clip(old), _clip(new), operation, status, note[:255], txid, undo_of)
            for column, old, new in changes]
    if tx is not None:
        for args in rows:
            tx.execute(sql, args)
        return len(rows)
    ensure_history()
    with connect() as conn:
        with conn.cursor() as cur:
            for args in rows:
                cur.execute(sql, args)
            conn.commit()
            return cur.rowcount


def _clip(value, limit=60000):
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    if len(text.encode('utf-8')) > limit:
        raise ValueError('Value is too large for reversible history')
    return text


def history_rows(limit=100, offset=0, db_name=None, table=None):
    ensure_history()
    where, params = [], []
    if db_name:
        where.append("db_name=%s")
        params.append(db_name)
    if table:
        where.append("table_name=%s")
        params.append(table)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.extend([int(limit), int(offset)])
    return query(
        "SELECT id, ts, admin, db_name, table_name, pk_json, column_name, old_value, "
        "new_value, operation, status, note, txid, undone, undo_of "
        "FROM `player`.`editsql_history`" + clause +
        " ORDER BY id DESC LIMIT %s OFFSET %s", params)


def history_count(db_name=None, table=None):
    ensure_history()
    where, params = [], []
    if db_name:
        where.append("db_name=%s")
        params.append(db_name)
    if table:
        where.append("table_name=%s")
        params.append(table)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return int(scalar("SELECT COUNT(*) AS n FROM `player`.`editsql_history`" + clause,
                      params, 0) or 0)


def history_open_groups(txids):
    """{txid: ile niecofnietych dodan/usuniec wierszy} - jedno cofniecie bierze cala grupe."""
    wanted = sorted({decode(t) for t in txids if t})
    if not wanted:
        return {}
    rows = query("SELECT txid AS t, COUNT(*) AS n FROM `player`.`editsql_history` "
                 "WHERE txid IN (%s) AND undone=0 AND operation IN ('insert','delete') "
                 "GROUP BY txid" % ",".join(["%s"] * len(wanted)), tuple(wanted))
    return {decode(row["t"]): int(row["n"]) for row in rows}


def history_get(entry_id):
    ensure_history()
    rows = query("SELECT * FROM `player`.`editsql_history` WHERE id=%s", (int(entry_id),))
    return rows[0] if rows else None


def history_mark_undone(entry_id, new_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE `player`.`editsql_history` SET undone=1 WHERE id=%s",
                        (int(entry_id),))
            conn.commit()
