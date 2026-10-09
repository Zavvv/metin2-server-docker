#!/bin/sh
# Rendered for the mt2009 world by linux-port-mt2009/port/migratorify.py from
# linux-port/docker/mariadb/playerbot/apply.sh. DO NOT EDIT; edit the original.
# Apply the tracked Playerbot seed once per Compose start. The SQL itself is
# idempotent and conflict-safe, so this also handles existing databases.
set -eu

: "${M2_DB_HOST:?M2_DB_HOST is required}"
: "${M2_DB_PORT:?M2_DB_PORT is required}"
: "${M2_DB_USER:?M2_DB_USER is required}"
: "${M2_DB_PASSWORD:?M2_DB_PASSWORD is required}"

strict=${PLAYERBOT_SEED_STRICT:-0}
case "$strict" in
    0|1) ;;
    *)
        echo "[playerbot-migrate] FATAL: PLAYERBOT_SEED_STRICT must be 0 or 1" >&2
        exit 1
        ;;
esac

expected_existing_bots=${PLAYERBOT_EXPECT_MIN_EXISTING_BOTS:-0}
case "$expected_existing_bots" in
    ''|*[!0-9]*)
        echo "[playerbot-migrate] FATAL: PLAYERBOT_EXPECT_MIN_EXISTING_BOTS must be a non-negative integer" >&2
        exit 1
        ;;
esac

seed=/opt/playerbot/playerbots_seed.sql
[ -s "$seed" ] || {
    echo "[playerbot-migrate] FATAL: $seed is missing or empty" >&2
    exit 1
}

db() {
    # mariadb(1) inherits MYSQL_PWD; MARIADB_PWD is not a client variable.
    # Keeping it out of argv avoids exposing the secret in `docker top`/ps.
    MYSQL_PWD="$M2_DB_PASSWORD" mariadb \
        --protocol=tcp \
        --host="$M2_DB_HOST" \
        --port="$M2_DB_PORT" \
        --user="$M2_DB_USER" \
        --default-character-set=latin1 \
        --batch --skip-column-names "$@"
}

# SQL the server gave up on because of another session's locks, run again a
# few times, a little later each time: a deadlock (1213, which rolls its
# transaction back) or a lock waited for too long (1205, which rolls the
# statement back, and the rest of a transaction with the session). The other
# sessions are the containers that start beside this one - the panels and
# Seban's collector read player.item and world.item_proto, and a read that
# feeds a write (INSERT ... SELECT, CREATE ... SELECT) holds shared locks on
# what it reads - and a game whose db core is still up on a start that left it
# running. One start in eight on the operator's test world lost the Dragon
# Stone Shard's stacking that way (1 October: "ERROR 1213 (40001) at line 1:
# Deadlock found when trying to get lock" on UPDATE player.item ... vnum =
# 30270, then "could not make the Dragon Stone Shard stack").
#
# Only for SQL a second run leaves as the first left it: one statement (rolled
# back whole), one transaction, or statements each of which is idempotent -
# every write of this file is one of those, and goes through here. A read
# needs none: a consistent read takes no row lock. The SQL is -e's, or stdin's,
# kept for the next try; what is printed is the last try's, and its exit
# status is db's.
db_retry() {
    db_retry_sql=
    case " $* " in
        *" -e "*|*" --execute"*) ;;
        *)
            db_retry_sql=/tmp/playerbot-retry.sql
            cat >"$db_retry_sql"
            ;;
    esac
    db_retry_try=1
    while :; do
        db_retry_rc=0
        if [ -n "$db_retry_sql" ]; then
            db "$@" <"$db_retry_sql" >/tmp/playerbot-retry.out 2>/tmp/playerbot-retry.err || db_retry_rc=$?
        else
            db "$@" >/tmp/playerbot-retry.out 2>/tmp/playerbot-retry.err || db_retry_rc=$?
        fi
        if [ "$db_retry_rc" -eq 0 ] || [ "$db_retry_try" -ge 5 ] ||
                ! grep -qE '^ERROR (1205|1213) ' /tmp/playerbot-retry.err; then
            cat /tmp/playerbot-retry.out
            cat /tmp/playerbot-retry.err >&2
            return "$db_retry_rc"
        fi
        echo "[playerbot-migrate] $(grep -m 1 -E '^ERROR (1205|1213) ' /tmp/playerbot-retry.err) - another session held the rows; the same SQL again in $db_retry_try s (try $((db_retry_try + 1)) of 5)" >&2
        sleep "$db_retry_try"
        db_retry_try=$((db_retry_try + 1))
    done
}

# When this run began, before it waits for anything: the crash check below
# compares it with the database server's uptime to tell a start that follows
# the server's own (whatever this run then waited for) from one that does not.
migrate_started=$(date +%s)

# The official image can answer its healthcheck while its temporary first-run
# server is still importing dumps. Wait for tables at the end of every shipped
# dump, then require the item prototypes used by the starter rows.
echo "[playerbot-migrate] waiting for the complete mt2009 schema"
attempt=0
# Consecutive probes refused for authentication; see the check inside the
# loop. Reset by any probe that fails for a different reason, so a login
# that starts working is not held against it.
auth_failures=0
while :; do
    attempt=$((attempt + 1))
    # Keep the error instead of discarding it. A refused login looks exactly
    # like a schema that has not finished importing, and silently waiting five
    # minutes for a permissions problem to fix itself helps nobody.
    probe_err=/tmp/playerbot-probe.err
    ready=$(db -e "
        SELECT COUNT(*)
          FROM information_schema.tables
         WHERE (table_schema='account' AND table_name='account')
            OR (table_schema='common'  AND table_name='gmlist')
            OR (table_schema='player'  AND table_name IN
                ('player','player_index','item','item_proto','string'))
            OR (table_schema='log'     AND table_name='hack_log');
    " 2>"$probe_err" || true)
    if [ -s "$probe_err" ] && [ "$attempt" -eq 3 ]; then
        echo "[playerbot-migrate] the database is not answering yet:" >&2
        head -3 "$probe_err" >&2
    fi

    # A refused login is not a slow import, and waiting thirty minutes for it
    # to fix itself tells the operator the wrong thing twice: once by the wait
    # and once by the message at the end, which blames a large world still
    # recovering and suggests starting again. It never recovers - the password
    # in .env and the one the volume was initialised with simply differ.
    #
    # MariaDB error 1045 is "access denied for user" and 1044 is "access denied
    # to database"; both are permanent until somebody changes the credentials.
    # Confirmed over a few attempts rather than on the first, because a server
    # in the middle of starting can refuse a connection once for other reasons,
    # and then given up on with a message about the thing that is actually
    # wrong. Everything else - a refused connection, a missing schema - keeps
    # the long budget, which is what it was for.
    if [ -s "$probe_err" ] && grep -qiE "1045|1044|access denied" "$probe_err"; then
        auth_failures=$((auth_failures + 1))
    else
        auth_failures=0
    fi
    if [ "$auth_failures" -ge 5 ]; then
        echo "[playerbot-migrate] FATAL: the database refuses this login." >&2
        head -1 "$probe_err" >&2
        echo "[playerbot-migrate] This is a credentials problem, not a slow import: the password in" >&2
        echo "[playerbot-migrate] linux-port/docker/.env and the one this database was created with" >&2
        echo "[playerbot-migrate] are not the same. Waiting will not change it." >&2
        echo "[playerbot-migrate] In the launcher: NAPRAW DOSTEP DO BAZY." >&2
        exit 1
    fi
    if [ "$ready" = "8" ]; then
        protos=$(db -e "SELECT COUNT(*) FROM player.item_proto;" 2>/dev/null || true)
        [ -n "$protos" ] && [ "$protos" -gt 0 ] 2>/dev/null && break
    fi
    # A large world that was not shut down cleanly can spend many minutes in
    # InnoDB recovery while the image's healthcheck already answers. Five
    # minutes was not enough for it, and because compose treats this container
    # as a hard dependency, the whole "up" failed and the launcher reported
    # that Docker had not built the server -- while starting it again by hand a
    # minute later worked. Wait far longer, and say what is happening.
    if [ "$attempt" -ge 900 ]; then
        echo "[playerbot-migrate] FATAL: database not ready after 30 minutes" >&2
        echo "[playerbot-migrate] the server is probably still recovering a large world; start it again" >&2
        exit 1
    fi
    if [ $((attempt % 30)) -eq 0 ]; then
        # Three different waits look the same from outside; say which this is.
        # "answering, with none of the eight tables" is not a slow import - it
        # is a MariaDB that initialised without the dumps, and no amount of
        # waiting changes it. One operator watched this for thirty minutes.
        if [ ! -s "$probe_err" ] && [ "${ready:-0}" = "0" ] && [ "$attempt" -ge 90 ]; then
            echo "[playerbot-migrate] MariaDB is answering but holds NONE of the r40250 tables ($((attempt * 2))s)." >&2
            echo "[playerbot-migrate] The database initialised without the SQL dumps: mariadb/initdb.d/dumps" >&2
            echo "[playerbot-migrate] was missing or empty on the very first start, and initdb.d never runs again." >&2
            echo "[playerbot-migrate] Waiting will not fix this. Stage the five dumps (the launcher and the" >&2
            echo "[playerbot-migrate] installer now check for them) and re-create the database volume." >&2
        elif [ ! -s "$probe_err" ] && [ "${ready:-0}" != "0" ]; then
            echo "[playerbot-migrate] still waiting for the schema ($((attempt * 2))s): ${ready}/8 tables so far - the first-run import is in progress"
        else
            echo "[playerbot-migrate] still waiting for the database ($((attempt * 2))s) - a large world can take a while to recover"
        fi
    fi
    sleep 2
done

# Repair anything MyISAM left marked as crashed.
#
# Seventy-three of r40250's seventy-five tables are MyISAM (twelve of mt2009's,
# log.log the big one), and one unclean stop marks a table crashed: every
# reader then fails until somebody repairs it. The server repairs such a table
# itself when it next opens it (`myisam_recover_options = BACKUP,FORCE` in
# 99-metin2.cnf), but not on a database that was already running when that
# option arrived, and never a table whose automatic repair has failed once:
# "marked as crashed and last (automatic?) repair failed" stays so until an
# explicit REPAIR TABLE, which is this step. What the operator sees then is
# not a database error but a blank "Internal Server Error" from the advanced
# panel, which reads everything from these tables while the classic panel,
# which reads files, keeps working (archonek2137, 10 September: log.log marked
# as crashed).
#
# Only the MyISAM tables are checked. FAST is MyISAM's own notion - a table is
# read only when it was not closed properly, and one the running server holds
# open and has written to counts as closed properly - so on a healthy world
# this is a lock and no read per table, under a running game too. InnoDB
# ignores it: CHECK TABLE ... FAST on an InnoDB table walks every index and
# counts every row, REPAIR TABLE cannot mend one anyway, and InnoDB has
# recovered from its own log before the server answers at all. With the four
# databases named whole (mariadb-check --databases), a launcher Start on the
# mt2009 test world (1 October: 2.2 GB of InnoDB through a 128 MB buffer pool)
# spent about 30 seconds here with the game stopped and 13.5 minutes with it
# running; the MyISAM half took a tenth of a second in a world of the same
# shape, idle or written to.
#
# The statements are the ones mariadb-check --auto-repair sends - CHECK TABLE
# ... FAST, then REPAIR TABLE for what the check found broken - one table to a
# statement, which is what lets the step say what it is doing. mariadb-check
# itself first asks SHOW CREATE TABLE of a table named on its command line,
# which a table whose last repair failed refuses, and then it skips that table
# and exits 0: the very table this step is for. ENGINE comes from the .frm
# without opening the table, so a crashed table is still listed as MyISAM;
# one whose engine cannot be read at all is checked too. Nothing here opens a
# table before CHECK TABLE does: an ordinary open of a crashed one is the
# server's own repair, minutes long and silent.
#
# A table left open by a kill is read whole, and a log.log of fifty-four
# million rows took twelve minutes to repair (OCTODAN, 1 October). The step
# said nothing until the end: his first start sat four minutes on "db:
# Healthy", he began the update in the middle of the repair, the table was
# "last (automatic?) repair failed" for it, and the next start repaired it,
# as silently, for twelve minutes more. So it speaks before the long work:
# on a start that follows the database server's own, the only start an
# unclean stop can precede, with the biggest tables' rows as the last check
# measured them (common.playerbot_myisam_size); before each repair; and every
# twenty seconds while one statement runs (crash_check_watch). Failures are
# reported and never fatal: a world that starts with one damaged log table is
# far better than a world that refuses to start at all.
root_db() {
    # This step runs as root; the password stays out of argv, as db()'s does.
    MYSQL_PWD="$M2_DB_ROOT_PASSWORD" mariadb \
        --protocol=tcp --host="$M2_DB_HOST" --port="$M2_DB_PORT" --user=root \
        --batch --skip-column-names "$@"
}
crash_check_watch() {
    # What the longest-running CHECK or REPAIR TABLE is doing, once it has run
    # for fifteen seconds and every twenty after that, until this step kills
    # the watch.
    watch_id=
    watch_said=0
    while :; do
        sleep 5
        watch_row=$(root_db -e "
            SELECT ID, TIME,
                   CONCAT(IF(INFO LIKE 'REPAIR%', 'repairing ', 'checking '),
                          REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(INFO, ' ', 3), ' ', -1), '\`', ''),
                          ' for ', TIME DIV 60, ' min ', TIME MOD 60, ' s (',
                          IFNULL(NULLIF(STATE, ''), 'working'),
                          IF(PROGRESS > 0, CONCAT(', ', ROUND(PROGRESS), '%'), ''), ')')
              FROM information_schema.PROCESSLIST
             WHERE COMMAND = 'Query' AND ID <> CONNECTION_ID()
               AND (INFO LIKE 'CHECK TABLE %' OR INFO LIKE 'REPAIR TABLE %')
             ORDER BY TIME DESC LIMIT 1;" 2>/dev/null </dev/null) || continue
        read -r w_id w_secs w_text <<EOF
$watch_row
EOF
        case "${w_id:-x}${w_secs:-x}" in *[!0-9]*) continue ;; esac
        if [ "$w_id" != "$watch_id" ]; then
            [ "$w_secs" -ge 15 ] || continue
            watch_id=$w_id
        elif [ $((w_secs - watch_said)) -lt 20 ]; then
            continue
        fi
        watch_said=$w_secs
        echo "[playerbot-migrate] crash check: $w_text - do not stop the server or start an update until this step reports"
    done
}
if [ -n "${M2_DB_ROOT_PASSWORD:-}" ]; then
    check_started=$(date +%s)
    check_err=/tmp/playerbot-check.err
    if tables=$(root_db -e "
            SELECT TABLE_SCHEMA, TABLE_NAME, IFNULL(ENGINE, '')
              FROM information_schema.TABLES
             WHERE TABLE_SCHEMA IN ('account', 'common', 'player', 'log')
               AND TABLE_TYPE = 'BASE TABLE';" 2>"$check_err" </dev/null); then
        printf '%s\n' "$tables" | awk -F '\t' 'NF >= 3 && ($3 == "MyISAM" || $3 == "") { print $1 "." $2 }' >/tmp/playerbot-myisam
        myisam_n=$(awk 'NF { n++ } END { print n + 0 }' /tmp/playerbot-myisam)
        innodb_n=$(printf '%s\n' "$tables" | awk -F '\t' 'NF >= 3 && $3 == "InnoDB" { n++ } END { print n + 0 }')
        repaired_n=0
        broken=
        broken_n=0
        check_failed=0
        if [ "$myisam_n" -gt 0 ]; then
            root_db -e "
                CREATE TABLE IF NOT EXISTS common.playerbot_myisam_size (
                    table_schema VARCHAR(64) NOT NULL,
                    table_name VARCHAR(64) NOT NULL,
                    table_rows BIGINT UNSIGNED NOT NULL DEFAULT 0,
                    data_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
                    measured_at DATETIME NOT NULL,
                    PRIMARY KEY (table_schema, table_name)
                ) ENGINE=InnoDB;" 2>/dev/null </dev/null || true
            root_db -e "SELECT CONCAT(table_schema, '.', table_name), table_rows FROM common.playerbot_myisam_size;" \
                >/tmp/playerbot-myisam-size 2>/dev/null </dev/null || : >/tmp/playerbot-myisam-size
            # How long the server had been up when this run began, whatever
            # the run then waited for (the schema, a large world's recovery):
            # under ten minutes is a start that follows the server's own, the
            # only start an unclean stop can come before. An uptime nobody can
            # read is taken for one.
            uptime=$(root_db -e "SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'UPTIME';" 2>/dev/null </dev/null || true)
            case "$uptime" in
                ''|*[!0-9]*) up_before=0 up_text="its uptime could not be read" ;;
                *)
                    up_before=$((uptime - (check_started - ${migrate_started:-$check_started})))
                    if [ "$up_before" -le 0 ]; then up_text="the database came up while this start waited for it"
                    else up_text="the database had been up $up_before s when this start began"; fi
                    ;;
            esac
            if [ "$up_before" -lt 600 ]; then
                big=$(awk -F '\t' 'NR == FNR { rows[$1] = $2; next } ($0 in rows) && rows[$0] >= 100000 { print rows[$0] "\t" $0 }' \
                        /tmp/playerbot-myisam-size /tmp/playerbot-myisam |
                    sort -rn | head -3 | awk -F '\t' '{ printf "%s%s: %s rows", (NR > 1 ? ", " : ""), $2, $1 }')
                echo "[playerbot-migrate] crash check: $up_text, so its $myisam_n MyISAM table(s) are checked for what an unclean stop may have left${big:+ ($big at the last check)} - a table left open is read whole and repaired if broken, minutes for millions of rows: do not stop the server or start an update until this step reports"
            fi
            crash_check_watch &
            watch_pid=$!
            awk -F '.' 'NF == 2 { printf "CHECK TABLE `%s`.`%s` FAST;\n", $1, $2 }' /tmp/playerbot-myisam >/tmp/playerbot-check.sql
            if ! root_db --force </tmp/playerbot-check.sql >/tmp/playerbot-check.out 2>"$check_err"; then
                check_failed=1
            fi
            # A table is repaired when its check said anything but a note and
            # did not end in OK - mariadb-check --auto-repair's own rule; what
            # the check said of it is printed either way.
            awk -F '\t' '
                NF >= 4 {
                    t = $1; kind = tolower($3); text = $4
                    for (i = 5; i <= NF; i++) text = text " " $i
                    if (!(t in seen)) { seen[t] = 1; order[++n] = t }
                    if (kind == "status") { status[t] = text; next }
                    said[t] = (t in said) ? said[t] "; " text : text
                    if (kind != "note" && kind != "info") bad[t] = 1
                }
                END {
                    for (i = 1; i <= n; i++) {
                        t = order[i]
                        if (t in said) print "said\t" t "\t" said[t] ((t in status) ? "; " status[t] : "")
                        if ((t in bad) && status[t] != "OK") print "repair\t" t
                    }
                }' /tmp/playerbot-check.out >/tmp/playerbot-check.verdicts
            awk -F '\t' '$1 == "said" && ++n <= 20 { print "[playerbot-migrate] crash check: " $2 ": " $3 }
                         END { if (n > 20) print "[playerbot-migrate] crash check: and " (n - 20) " more table(s) the check had words for" }' \
                /tmp/playerbot-check.verdicts
            awk -F '\t' '$1 == "repair" { print $2 }' /tmp/playerbot-check.verdicts >/tmp/playerbot-repairs
            while IFS= read -r table; do
                rows=$(awk -F '\t' -v t="$table" '$1 == t { print $2; exit }' /tmp/playerbot-myisam-size)
                if [ -n "$rows" ]; then size_text="$rows rows at the last check"; else size_text="never measured"; fi
                echo "[playerbot-migrate] crash check: repairing $table ($size_text) - the check found it broken; minutes for millions of rows: do not stop the server or start an update until this step reports"
                repair_started=$(date +%s)
                if repair_out=$(root_db -e "REPAIR TABLE \`${table%%.*}\`.\`${table#*.}\`;" 2>&1 </dev/null); then
                    repair_said=$(printf '%s\n' "$repair_out" | awk -F '\t' 'NF >= 4 && $3 != "status" { s = s (s == "" ? "" : "; ") $4 } END { print s }')
                    repair_status=$(printf '%s\n' "$repair_out" | awk -F '\t' 'NF >= 4 && $3 == "status" { s = $4 } END { print s }')
                else
                    repair_said=$(printf '%s\n' "$repair_out" | grep -v 'ssl-verify-server-cert' | head -2 | tr '\n' ' ')
                    repair_status=
                fi
                if [ "$repair_status" = OK ]; then
                    repaired_n=$((repaired_n + 1))
                    echo "[playerbot-migrate] crash check: $table repaired in $(($(date +%s) - repair_started)) s${repair_said:+: $repair_said}"
                else
                    broken="$broken $table"
                    broken_n=$((broken_n + 1))
                    echo "[playerbot-migrate] WARNING: crash check: $table could not be repaired: ${repair_said:-no answer}${repair_status:+; $repair_status}" >&2
                fi
            done </tmp/playerbot-repairs
            kill "$watch_pid" 2>/dev/null || true
            wait "$watch_pid" 2>/dev/null || true
            # What the tables measure now, for the next start's warning. Only
            # the tables this step left sound are opened: a table still broken
            # would be repaired again by the open itself.
            keep=$(awk -v broken="$broken " 'BEGIN { q = sprintf("%c", 39) }
                     NF && index(broken " ", " " $0 " ") == 0 { printf "%s%s%s%s", (n++ ? ", " : ""), q, $0, q }' /tmp/playerbot-myisam)
            if [ -n "$keep" ]; then
                root_db -e "
                    REPLACE INTO common.playerbot_myisam_size (table_schema, table_name, table_rows, data_bytes, measured_at)
                    SELECT TABLE_SCHEMA, TABLE_NAME, IFNULL(TABLE_ROWS, 0), IFNULL(DATA_LENGTH, 0) + IFNULL(INDEX_LENGTH, 0), NOW()
                      FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA IN ('account', 'common', 'player', 'log')
                       AND CONCAT(TABLE_SCHEMA, '.', TABLE_NAME) IN ($keep)
                       AND ENGINE = 'MyISAM';" 2>/dev/null </dev/null || true
            fi
        fi
        check_more=
        [ "$repaired_n" -eq 0 ] || check_more=", $repaired_n repaired"
        [ "$broken_n" -eq 0 ] || check_more="$check_more, $broken_n not repaired"
        echo "[playerbot-migrate] crash check: $myisam_n MyISAM table(s) in $(($(date +%s) - check_started)) s$check_more; $innodb_n InnoDB table(s) not checked - InnoDB recovers from its own log, and CHECK TABLE would walk all of it while the game waits"
        if [ "$check_failed" -ne 0 ]; then
            echo "[playerbot-migrate] WARNING: table check failed; continuing" >&2
            grep -v 'ssl-verify-server-cert' "$check_err" | head -5 >&2 || true
        fi
    else
        echo "[playerbot-migrate] WARNING: could not list the tables to check; continuing" >&2
        grep -v 'ssl-verify-server-cert' "$check_err" | head -3 >&2 || true
    fi
fi

# The ItemShop's own database, and the item_award table its purchases are
# delivered through. Created as root because the metin2 user cannot create a
# database, and only when the root password is in the environment (it is,
# from .env, on every install the launcher made); a world without it keeps
# running - the shop then answers with an empty page, not the game with an
# error. Idempotent: CREATE IF NOT EXISTS, and the seed only fills an empty
# shop, so an operator's own catalogue survives every restart.
social_len=$(db -e "
    SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.columns
     WHERE table_schema='account' AND table_name='account' AND column_name='social_id';
")
if [ -n "$social_len" ] && [ "$social_len" -lt 18 ] 2>/dev/null; then
    echo "[playerbot-migrate] widening account.social_id from $social_len to 18 characters"
    db_retry -e "ALTER TABLE account.account MODIFY social_id VARCHAR(18) NOT NULL DEFAULT '';"
fi
# The ItemShop reads mileage and jackpot off the account; this schema has
# cash alone. IF NOT EXISTS keeps it a no-op after the first time.
db_retry -e "ALTER TABLE account.account ADD COLUMN IF NOT EXISTS mileage INT NOT NULL DEFAULT 0;"
db_retry -e "ALTER TABLE account.account ADD COLUMN IF NOT EXISTS jackpot INT NOT NULL DEFAULT 0;"
# Fishing from thirty, which is what the wiki says and what the operator
# asked for. This line shipped fifty in three places and moving two was not
# enough: CHARACTER::fishing() (playerbotify.py lowers it), the AI gate, and
# the rod LIMIT_LEVEL - the one that refuses the equip, so a bot of thirty
# could neither wear a rod nor be drawn as an angler. item_proto is read out
# of world.item_proto here (PROTO_FROM_DB = 1), which is why this sticks;
# idempotent, and it touches only rods still carrying the old fifty.
db_retry -e "UPDATE world.item_proto SET limitvalue0 = 30 WHERE type = 13 AND limittype0 = 1 AND limitvalue0 = 50;"
# Cape 70138 from thirty instead of fifty (Tieru, 4 October, variant a).
# 70038, 70057 and 76007 keep no level limit, as in the package.
# PROTO_FROM_DB reads world.item_proto at boot; preserve custom limits.
# The client needs the same gamedata/item_proto edit (port/protoify.py).
db_retry -e "UPDATE world.item_proto SET limitvalue0 = 30 WHERE vnum = 70138 AND type = 3 AND subtype = 10 AND limittype0 = 1 AND limitvalue0 = 50 AND limittype1 = 0 AND limitvalue1 = 0;"
# The ItemShop has its own purchase gate, independent of the use limit.
# Lower its stock fifty only when this world actually has the approved
# level-thirty cape; preserve custom shop and proto limits.
db_retry -e "UPDATE common.itemshop_items SET minLevel = 30 WHERE vnum = 70138 AND minLevel = 50 AND EXISTS (SELECT 1 FROM world.item_proto WHERE vnum = 70138 AND type = 3 AND subtype = 10 AND limittype0 = 1 AND limitvalue0 = 30 AND limittype1 = 0 AND limitvalue1 = 0);"
# And the pass the rod needs. Karta Wedkarska (27620), which CHARACTER::fishing()
# wants worn, is sold in one place, the Fisherman's special shop (9009, opened
# by fishing_pass_shop.quest), and the package asks level fifty for it - so a
# player of thirty to forty-nine could wear the rod the line above allows and
# never fish (Tieru, 17 September). The db core reads shop_special_proto at
# boot, so this is live on the next start; idempotent, and only a fifty moves.
db_retry -e "UPDATE world.shop_special_proto SET limitvalue0 = 30 WHERE item_vnum = 27620 AND limittype0 = 'LEVEL' AND limitvalue0 = 50; UPDATE world.shop_special_proto SET limitvalue1 = 30 WHERE item_vnum = 27620 AND limittype1 = 'LEVEL' AND limitvalue1 = 50;"
# Pierscien Teleportacji (70058) carries ITEM_FLAG_APPLICABLE (8192) in this
# package, and under ENABLE_QUEST_DND_EVENT that flag makes UseItemEx treat an
# ITEM_QUEST as "drop it onto another item": a plain use finds no target cell
# and returns before the quest is asked, so teleport_ring.quest never ran for
# a player ("caly czas nie dziala pierscien teleportu", Tieru, 16 September).
# The ring is dragged onto nothing; the flag comes off. Idempotent.
db_retry -e "UPDATE world.item_proto SET flag = flag & ~8192 WHERE vnum = 70058 AND (flag & 8192) <> 0;"
# The Grotto of Exile's warp in Orc Valley's bottom-left corner (10077,
# commented again since 2.2.21, when Koe-Pung took the way in; kept right for a
# GM who puts it back) reads its target out of its own locale_name
# (FuncCheckWarp), and the package's pointed at cell (9,46) of map 72 - a
# blocked cell six kilometres from any open ground. The target is the
# grotto's Town point (100,46), where the engine also stands up whoever dies
# in there, 1.3 km from the way out (10078). The db core reads mob_proto at
# boot (PROTO_FROM_DB); idempotent.
db_retry -e "UPDATE world.mob_proto SET name = '????1? 100 12078', locale_name = '????1? 100 12078' WHERE vnum = 10077 AND locale_name <> '????1? 100 12078';" || echo "[playerbot-migrate] WARNING: could not point the Grotto of Exile warp at its Town" >&2
# Three doors of the Devil's Catacomb's fourth-floor maze (10814, 10817,
# 10818) carry a locale_name with no space after the dot - ".233 780" - which
# FuncCheckWarp's ' %s %ld %ld' cannot read, so the engine moved nobody
# through them; their name column is whole, and its targets stand on the
# maze's open ground (checked on map 216's server_attr, 26 September). The
# stake at the end is reachable in every wiring without them. Idempotent.
db_retry -e "UPDATE world.mob_proto SET locale_name = name WHERE vnum IN (10814, 10817, 10818) AND locale_name <> name;" || echo "[playerbot-migrate] WARNING: could not mend the Catacomb maze doors" >&2
# Three ItemShop lines stood behind time auctions the package's server ran
# in December 2024 - 906 the Metin stone detector, 907 Kamien Duchowy, 908 -
# and an ended auction is a line nobody sees and BuyItem refuses, a player
# as much as a bot. Their auction rows go and the lines are ordinary ones;
# an auction the operator makes is not touched. The db core reads both
# tables at boot; idempotent. Until 2.2.21 the second DELETE was a
# multi-table one, which MariaDB refuses with no default database, so the
# players' buy counts of the three stayed and this warned at every start.
db_retry -e "DELETE FROM common.itemshop_time_auctions WHERE item_index IN (906, 907, 908) AND end_time < '2025-01-01'; DELETE FROM player.itemshop_time_auction WHERE item_index IN (906, 907, 908) AND item_index NOT IN (SELECT item_index FROM common.itemshop_time_auctions);" || echo "[playerbot-migrate] WARNING: could not end the ItemShop old time auctions" >&2
# Pirate Tanaka (5001), the Tanaka event's treasure goblin
# (playerbot_world_events.h): the package gives him 560 yang, which his fall
# splits into thirty piles of twenty, and a flat thousand at each fifth of his
# health (playerbotify apply_tanaka_goblin scales that to a fifth of a roll of
# these). A world whose operator set his yang by hand keeps it: only the
# stock 560 moves. The db core reads mob_proto at boot; idempotent.
db_retry -e "UPDATE world.mob_proto SET gold_min = 15000, gold_max = 25000 WHERE vnum = 5001 AND gold_min = 560 AND gold_max = 560;" || echo "[playerbot-migrate] WARNING: could not give Pirate Tanaka his yang" >&2
# His ear (30202), which Yonah takes for a Purple Ebony Chest
# (tanaka_ears.quest), stacks to the 200 its row already says: the package
# left ITEM_FLAG_STACKABLE off, so every ear took a cell. Idempotent.
db_retry -e "UPDATE world.item_proto SET flag = flag | 4 WHERE vnum = 30202 AND (flag & 4) = 0;" || echo "[playerbot-migrate] WARNING: could not make Tanaka's ear stack" >&2
# The skill books (type 17), the Forgetting Book (22) and Kamien Duchowy
# (50513) stacked to the package's ten; the operator's two hundred (DUDU,
# 26 September). PROTO_FROM_DB: the db core reads it at boot, and books of
# two skills never merge, their socket differs. Never lowered again: the
# engine would cut every stack above the new ceiling at the next load.
# Leadership 50301..50303 is ITEM_USE/USE_SPECIAL, not ITEM_SKILLBOOK
# (Edi, 4 October). Raise its stock ten too; custom limits stay unchanged.
db_retry -e "UPDATE world.item_proto SET stack = 200 WHERE (type IN (17, 22) OR vnum = 50513 OR (vnum BETWEEN 50301 AND 50303 AND type = 3 AND subtype = 10 AND (flag & 4) <> 0)) AND stack = 10;" || echo "[playerbot-migrate] WARNING: could not raise the books' stack" >&2
# Every kind of arrow (ITEM_WEAPON 1, WEAPON_ARROW 6: 8000-8009) stacked to
# the package's thousand; five thousand, the operator's (ren3kun7 and Tieru,
# 30 September). The engine merges by the proto's own ceiling (GetMaxStack)
# and counts in a DWORD. Tieru also approved raising legacy 200 for standard
# arrows 8000-8009 (Drip, 5 October); this includes a manually set 200.
# Nonstandard arrows at 200 and all other custom ceilings stay unchanged.
# Mirror this predicate in protoify.py's shared gamedata table. Never lower
# a ceiling: the engine would cut larger stacks at the next load.
# PROTO_FROM_DB: the db core reads it at boot; idempotent.
db_retry -e "UPDATE world.item_proto SET stack = 5000 WHERE type = 1 AND subtype = 6 AND (stack = 1000 OR (vnum BETWEEN 8000 AND 8009 AND stack = 200));" || echo "[playerbot-migrate] WARNING: could not raise the arrows' stack" >&2
# Fire Arrow (48) back to the formula before the package's rework, which
# its world.sql keeps as skill_proto_copy_przed_zmianami_barabasza: the
# rework's 2*atk, dex*2*k and *1.35 made it about 1.55 times as strong, the
# biggest single blow of any class, and the Ninja archers took the whole
# top of the skill damage ranking (Matthaeus; the operator, 30 September).
# The rework's third point, ATT_SPECIAL against stones and bosses, stays.
# Only the package's own text moves - an operator's own formula stays.
# The db core reads skill_proto from world at boot. Idempotent.
db_retry -e "UPDATE world.skill_proto SET szPointPoly = '-(1.5*atk + (2.8*atk + number(100, 300))*k)', szMasterBonusPoly = '-(1.5*atk + (2.6*atk + number(100, 300))*k)' WHERE dwVnum = 48 AND szPointPoly = '-(2*atk + (2.8*atk + number(100, 300))*k + dex*2*k)*1.35';" || echo "[playerbot-migrate] WARNING: could not put Fire Arrow back to its formula" >&2
# The ItemShop's Auto Lowy ticket and anti-experience ring (the operator,
# 27 September): two quest items the package defines and nothing uses -
# "Opaska Posz. Zlota" (31073) and "Pierscien Levi" (40002) - renamed
# and bound (no sale, trade, drop or counter; the ticket stacks), their uses
# answered by autohunt_time.quest and antiexp_ring.quest; and the shop's
# first page gains them with the Teleport Ring (70058), which is never used
# up. ASCII names: db() speaks latin1 into the cp1250 columns. A line the
# operator changed by hand is kept (INSERT IGNORE), and one deleted in the
# database editor stays deleted (common.m2_itemshop_removed). Idempotent.
db_retry -e "UPDATE world.item_proto SET locale_name = 'Auto Lowy (8h)', flag = flag | 4, antiflag = 74112 WHERE vnum = 31073 AND locale_name <> 'Auto Lowy (8h)'; UPDATE world.item_proto SET locale_name = 'Pierscien Anty-Exp', flag = 0, antiflag = 41344 WHERE vnum = 40002 AND locale_name <> 'Pierscien Anty-Exp'; CREATE TABLE IF NOT EXISTS common.m2_itemshop_removed (\`index\` INT NOT NULL PRIMARY KEY, removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB; INSERT IGNORE INTO common.itemshop_items (\`index\`, vnum, count, price, currency, minLevel) SELECT s.i, s.v, s.c, s.p, s.cur, s.lv FROM (SELECT 6 AS i, 31073 AS v, 1 AS c, 29 AS p, 'DRAGON_COIN' AS cur, 0 AS lv UNION ALL SELECT 7, 40002, 1, 99, 'DRAGON_COIN', 0 UNION ALL SELECT 8, 70058, 1, 149, 'DRAGON_COIN', 30) AS s WHERE s.i NOT IN (SELECT \`index\` FROM common.m2_itemshop_removed);" || echo "[playerbot-migrate] WARNING: could not add the ItemShop's Auto Lowy ticket and rings" >&2
# Maska Sabaha left the world with the Hwang curse (playerbotify
# apply_hwang_curse_removed, the share step of the game Dockerfile): the shop
# that sold one sells it no more. The db core reads the shops at boot, so this
# is live on the next start; idempotent.
db_retry -e "DELETE FROM world.shop_item WHERE item_vnum IN (72731, 72735);"
# And nobody keeps one: every Maska Sabaha still in a bag, on a character, in a
# safebox or on a counter is removed (Tieru, 15 September, "usun" to the masks
# players already held). On every start, so a mask an old core still held while
# an update ran this beside it goes on the next one.
masks=$(db_retry -e "DELETE FROM player.item WHERE vnum IN (72731, 72735); SELECT ROW_COUNT();" || echo x)
masks=$(printf '%s' "$masks" | tr -d '[:space:]')
if [ "$masks" = "x" ]; then
    echo "[playerbot-migrate] WARNING: could not remove the Maska Sabaha items" >&2
elif [ -n "$masks" ] && [ "$masks" != "0" ]; then
    echo "[playerbot-migrate] removed $masks Maska Sabaha item(s)"
fi
# The market of Shinsoo's and Jinno's villages moved onto the kingdom's guard
# in 2.0.52 (GetTownPitch, playerbot_empire_rules.h), and nothing would ever
# have moved the shops standing round the old pitch: an offline shop stands
# where its keeper stood when it was opened (OpenOfflineShop takes the
# character's position, a reopen included) and a keeper walks to its shop to
# serve it. So each bot's shop of the old ring is carried across by the
# distance between the two pitches, which keeps the ring's shape and spacing,
# and pulled in to 1650 of the guard where it stood further out - the ring of
# 400 to 1700 round each guard is open ground inside the safe zone on
# server_attr. A shop already inside the new ring and outside the old one
# belongs to the new pitch and stays. Once, marked in
# player.playerbot_migrations in the same transaction as the move; on every
# start after that only a bot's shop still within 2000 of an old pitch and more
# than 2000 from the new one moves - a keeper that reopened on the old spot
# while an update ran this beside the old game container (update.sh does not
# stop the game first). The db core writes a position only when a shop is
# opened or moved, so an old core cannot write the moved ones back. A player's
# own shop is left where its owner put it. Before the game container starts,
# because the db core reads the shops at boot.
db_retry -e "CREATE TABLE IF NOT EXISTS player.playerbot_migrations (name VARCHAR(64) NOT NULL PRIMARY KEY, done_at DATETIME NOT NULL) ENGINE=InnoDB;"
# The bot guilds' tiers (playerbot_guild.h): a guild outlives every core
# restart, so its tier and kingdom live here; the core reads the table once
# and writes a row when it founds or adopts a guild.
db_retry -e "CREATE TABLE IF NOT EXISTS player.playerbot_guild (guild_id INT UNSIGNED NOT NULL PRIMARY KEY, tier TINYINT UNSIGNED NOT NULL DEFAULT 3, empire TINYINT UNSIGNED NOT NULL DEFAULT 0, founder_pid INT UNSIGNED NOT NULL DEFAULT 0, founded_at DATETIME NOT NULL) ENGINE=InnoDB;"
# And when each last went to war (playerbot_guild_war.h), in unix seconds, so
# the pick that keeps a kingdom's last pair out of its next war survives the
# restart every update makes.
db_retry -e "ALTER TABLE player.playerbot_guild ADD COLUMN IF NOT EXISTS last_war_at INT UNSIGNED NOT NULL DEFAULT 0;" \
    || echo "playerbot-migrate: could not add last_war_at to player.playerbot_guild" >&2
# The second channel's pins (playerbot_channel_rules.h): every bot that has
# ever kept an offline shop lives on the first channel for good, because the
# shops are the first channel's. The table only grows - each core adds the
# owners it sees before it reads it - and this adds them before any core has
# started, so the start that switches the second channel on finds every keeper
# of the last session already pinned. Written whatever the switch says.
db_retry -e "CREATE TABLE IF NOT EXISTS player.playerbot_channel_pin (pid INT UNSIGNED NOT NULL PRIMARY KEY, pinned_at DATETIME NOT NULL) ENGINE=InnoDB;"
db_retry -e "INSERT IGNORE INTO player.playerbot_channel_pin (pid, pinned_at) SELECT owner, NOW() FROM player.ikashop_offlineshop;" 2>/dev/null \
    || echo "playerbot-migrate: could not pin the shop keepers to the first channel" >&2
pitch_done=$(db -e "SELECT COUNT(*) FROM player.playerbot_migrations WHERE name = 'pitch_on_guard_2052';" 2>/dev/null || echo x)
case "$pitch_done" in
    0) pitch_near=1700; pitch_far=1700 ;;
    1) pitch_near=-1; pitch_far=2000 ;;
    *) pitch_near= ;;
esac
if [ -n "$pitch_near" ]; then
    if pitch_moved=$(db_retry -e "
        CREATE TEMPORARY TABLE player.tmp_pitch_moves AS
        SELECT d.owner,
               d.nx + ROUND(d.dx * LEAST(1, 1650 / GREATEST(1, d.d_old))) AS tx,
               d.ny + ROUND(d.dy * LEAST(1, 1650 / GREATEST(1, d.d_old))) AS ty
          FROM (SELECT s.owner, m.nx, m.ny,
                       CAST(s.x AS SIGNED) - m.ox AS dx,
                       CAST(s.y AS SIGNED) - m.oy AS dy,
                       SQRT(POW(CAST(s.x AS SIGNED) - m.ox, 2) + POW(CAST(s.y AS SIGNED) - m.oy, 2)) AS d_old,
                       SQRT(POW(CAST(s.x AS SIGNED) - m.nx, 2) + POW(CAST(s.y AS SIGNED) - m.ny, 2)) AS d_new
                  FROM player.ikashop_offlineshop AS s
                  JOIN player.player AS p ON p.id = s.owner
                  JOIN account.account AS a ON a.id = p.account_id
                  JOIN (SELECT 1 AS map, 473625 AS ox, 954925 AS oy, 474325 AS nx, 954225 AS ny
                        UNION ALL SELECT 3, 353987, 880012, 353025, 882325
                        UNION ALL SELECT 41, 961212, 270162, 959925, 268825
                        UNION ALL SELECT 43, 865500, 244975, 863425, 246025) AS m ON m.map = s.map
                 WHERE a.login LIKE 'playerbot%') AS d
         WHERE d.d_old <= 2000 AND (d.d_old <= $pitch_near OR d.d_new > $pitch_far);
        START TRANSACTION;
        UPDATE player.ikashop_offlineshop AS s
          JOIN player.tmp_pitch_moves AS t ON t.owner = s.owner
           SET s.x = t.tx, s.y = t.ty;
        SELECT ROW_COUNT();
        INSERT IGNORE INTO player.playerbot_migrations (name, done_at) VALUES ('pitch_on_guard_2052', NOW());
        COMMIT;
        DROP TEMPORARY TABLE player.tmp_pitch_moves;
    "); then
        pitch_moved=$(printf '%s' "$pitch_moved" | tr -d '[:space:]')
        if [ "${pitch_moved:-0}" != "0" ]; then
            echo "[playerbot-migrate] $pitch_moved bot offline shop(s) in Yongan, Jayang, Pyongmoo and Bakra carried onto the guard's square"
        fi
    else
        echo "[playerbot-migrate] WARNING: could not move the bots' offline shops onto the new pitches" >&2
    fi
fi
# The package's player dump carries the guild lands and buildings of the
# server it was taken from - 28 player.guild_land rows and 62 player.object
# rows - and none of the guilds they belong to. The engine stands its land
# agent (NPC 20040) only on a land nobody owns (building::CManager, at boot),
# so those lands could never be bought and their buildings stood on ground
# nobody held, while a bot guild founded later under one of those numbers
# (2, 3, 5, ...) held a land and buildings it never paid for ("stoja juz
# budynki, pomimo ze teren nie jest zajety", Mat, 19 September; NerrVoVy
# cleared his by hand). Once, and the dump's own rows exactly: a land a
# player's guild has bought and the buildings it put up since (ids past the
# dump's last) are left alone. Before the game container starts, because the
# db core reads both at boot.
lands_done=$(db -e "SELECT COUNT(*) FROM player.playerbot_migrations WHERE name = 'package_guild_lands_2081';" 2>/dev/null || echo x)
if [ "$lands_done" = "0" ]; then
    if lands_out=$(db_retry -e "
        START TRANSACTION;
        DELETE FROM player.object WHERE (id, land_id, vnum) IN (
            (1, 14, 14100), (2, 214, 14120), (3, 214, 14014), (4, 14, 14013), (5, 215, 14120), (6, 215, 14013), (7, 218, 14120), (8, 218, 14043),
            (9, 16, 14100), (10, 16, 14014), (11, 16, 14043), (12, 108, 14100), (13, 108, 14014), (14, 214, 14050), (15, 14, 14051), (16, 215, 14051),
            (17, 217, 14100), (18, 218, 14014), (19, 217, 14015), (20, 109, 14100), (21, 109, 14051), (22, 17, 14100), (23, 17, 14015), (24, 207, 14110),
            (25, 207, 14014), (26, 15, 14100), (27, 15, 14015), (28, 217, 14051), (29, 18, 14110), (30, 18, 14055), (31, 115, 14120), (32, 115, 14014),
            (33, 108, 14043), (34, 18, 14015), (35, 116, 14120), (36, 116, 14013), (37, 216, 14110), (38, 109, 14015), (39, 8, 14120), (40, 216, 14013),
            (41, 212, 14100), (42, 117, 14110), (43, 216, 14055), (44, 117, 14055), (45, 117, 14014), (46, 205, 14120), (47, 205, 14055), (48, 15, 14055),
            (49, 216, 14200), (50, 216, 14300), (51, 216, 14300), (52, 205, 14015), (53, 212, 14015), (54, 206, 14100), (55, 206, 14015), (56, 8, 14015),
            (57, 115, 14050), (58, 212, 14055), (59, 207, 14055), (60, 8, 14055), (61, 208, 14110), (62, 201, 14100));
        SELECT ROW_COUNT();
        DELETE FROM player.guild_land WHERE (land_id, guild_id) IN (
            (2, 408), (8, 78), (9, 108), (10, 69), (14, 3), (15, 395), (16, 2), (17, 52),
            (18, 18), (108, 5), (109, 6), (115, 92), (116, 93), (117, 20), (118, 13), (201, 212),
            (204, 712), (205, 57), (206, 9), (207, 58), (208, 25), (212, 19), (213, 14), (214, 15),
            (215, 344), (216, 47), (217, 33), (218, 7));
        SELECT ROW_COUNT();
        INSERT IGNORE INTO player.playerbot_migrations (name, done_at) VALUES ('package_guild_lands_2081', NOW());
        COMMIT;
    "); then
        lands_objects=$(printf '%s\n' "$lands_out" | awk 'NR == 1')
        lands_rows=$(printf '%s\n' "$lands_out" | awk 'NR == 2')
        echo "[playerbot-migrate] the package's guild lands cleared: ${lands_rows:-0} land(s), ${lands_objects:-0} building(s)"
    else
        echo "[playerbot-migrate] WARNING: could not clear the package's guild lands" >&2
    fi
fi
# 2.2.20 opened the Grotto of Exile (72, 73) and the Devil's Catacomb (216)
# and no client of that time could stand on any of them: the grotto's maps
# stood in the season2 pack without the maps/ the client looks under, and the
# Catacomb's map was in no pack at all (client 2.0.38 carries all three, see
# port/season2ify.py). Entering one closed the client, and a character saved
# there could not log in again ("postac jest zbugowana", Iwakura, 26
# September). Once: every character of a person saved on one of them or in an
# instance of one is put where the way out leads - by Koe-Pung in Orc Valley
# (284200, 810600, the target of the grotto's exit 10078) or before the
# Catacomb's Guardian in Hwang Temple (591400, 99200, the quest's own exit).
# A bot has no client and stays where it is. Before the game container starts
# (a character left there minutes before an update may still be written back
# by the old db core's cache; the new client can stand there anyway).
rescue_done=$(db -e "SELECT COUNT(*) FROM player.playerbot_migrations WHERE name = 'grotto_catacomb_client_2221';" 2>/dev/null || echo x)
if [ "$rescue_done" = "0" ]; then
    if rescue_out=$(db_retry -e "
        START TRANSACTION;
        UPDATE player.player AS p JOIN account.account AS a ON a.id = p.account_id
           SET p.map_index = 64, p.x = 284200, p.y = 810600,
               p.exit_map_index = 64, p.exit_x = 284200, p.exit_y = 810600
         WHERE a.login NOT LIKE 'playerbot%'
           AND (p.map_index IN (72, 73) OR p.map_index BETWEEN 720000 AND 739999);
        SELECT ROW_COUNT();
        UPDATE player.player AS p JOIN account.account AS a ON a.id = p.account_id
           SET p.map_index = 65, p.x = 591400, p.y = 99200,
               p.exit_map_index = 65, p.exit_x = 591400, p.exit_y = 99200
         WHERE a.login NOT LIKE 'playerbot%'
           AND (p.map_index = 216 OR p.map_index BETWEEN 2160000 AND 2169999);
        SELECT ROW_COUNT();
        INSERT IGNORE INTO player.playerbot_migrations (name, done_at) VALUES ('grotto_catacomb_client_2221', NOW());
        COMMIT;
    "); then
        rescue_grotto=$(printf '%s\n' "$rescue_out" | awk 'NR == 1')
        rescue_catacomb=$(printf '%s\n' "$rescue_out" | awk 'NR == 2')
        echo "[playerbot-migrate] characters moved out of maps no old client could load: ${rescue_grotto:-0} from the Grotto of Exile, ${rescue_catacomb:-0} from the Devil's Catacomb"
    else
        echo "[playerbot-migrate] WARNING: could not move the characters out of the Grotto and the Catacomb" >&2
    fi
fi
# The bonus table as the global server has it (sosen's list, 27 September):
# Max HP to 2000, Max SP to 80 (200 on a necklace), regeneration to 30, no
# stamina, skill-duration, arrow-reflection or flat-experience lines, and fire,
# lightning and wind resistance, the double-experience and the item-drop
# chances added. Once, and only over the package's own values.
attr_done=$(db -e "SELECT COUNT(*) FROM player.playerbot_migrations WHERE name = 'item_attr_global_2231';" 2>/dev/null || echo x)
if [ "$attr_done" = "0" ]; then
    if attr_out=$(db_retry -e "
        START TRANSACTION;
        UPDATE world.item_attr SET prob = 35, lv1 = 500, lv2 = 500, lv3 = 1000, lv4 = 1500, lv5 = 2000
         WHERE apply = 'POINT_MAX_HP' AND lv1 = 300 AND lv2 = 500 AND lv3 = 800 AND lv4 = 1000 AND lv5 = 1500;
        UPDATE world.item_attr SET lv1 = 10, lv2 = 20, lv3 = 30, lv4 = 80, lv5 = 200, wrist = 4, foots = 4, neck = 5
         WHERE apply = 'POINT_MAX_SP' AND lv1 = 20 AND lv2 = 50 AND lv3 = 90 AND lv4 = 140 AND lv5 = 250;
        UPDATE world.item_attr SET lv1 = 4, lv2 = 8, lv3 = 12, lv4 = 20, lv5 = 30
         WHERE apply IN ('POINT_HP_REGEN', 'POINT_SP_REGEN') AND lv1 = 2 AND lv2 = 4 AND lv3 = 6 AND lv4 = 8 AND lv5 = 12;
        UPDATE world.item_attr SET weapon = 0, body = 0, wrist = 0, foots = 0, neck = 0, head = 0, shield = 0, ear = 0
         WHERE apply IN ('POINT_MAX_STAMINA', 'POINT_ST_REGEN', 'POINT_SKILL_DURATION', 'POINT_REFLECT_ARROW', 'POINT_MALL_EXPBONUS');
        INSERT INTO world.item_attr (apply, prob, lv1, lv2, lv3, lv4, lv5, weapon, body, wrist, foots, neck, head, shield, ear)
        SELECT n.a, n.p, n.l1, n.l2, n.l3, n.l4, n.l5, n.w, n.b, n.wr, n.f, n.ne, n.h, n.s, n.e FROM (
            SELECT 'POINT_RESIST_FIRE' AS a, 18 AS p, 2 AS l1, 4 AS l2, 6 AS l3, 10 AS l4, 15 AS l5, 0 AS w, 5 AS b, 5 AS wr, 0 AS f, 0 AS ne, 5 AS h, 0 AS s, 0 AS e
            UNION ALL SELECT 'POINT_RESIST_ELEC', 18, 2, 4, 6, 10, 15, 0, 5, 5, 0, 0, 5, 0, 0
            UNION ALL SELECT 'POINT_RESIST_WIND', 18, 2, 4, 6, 10, 15, 0, 5, 5, 0, 0, 5, 0, 0
            UNION ALL SELECT 'POINT_EXP_DOUBLE_BONUS', 10, 2, 4, 6, 8, 20, 0, 0, 0, 5, 5, 0, 5, 0
            UNION ALL SELECT 'POINT_ITEM_DROP_BONUS', 7, 2, 4, 6, 8, 20, 0, 0, 5, 0, 0, 0, 0, 5) AS n
         WHERE NOT EXISTS (SELECT 1 FROM world.item_attr AS x WHERE x.apply = n.a);
        SELECT ROW_COUNT();
        INSERT IGNORE INTO player.playerbot_migrations (name, done_at) VALUES ('item_attr_global_2231', NOW());
        COMMIT;
    "); then
        echo "[playerbot-migrate] bonus table as the global server has it: $(printf '%s' "$attr_out" | tr -d ' \r\n') line(s) added"
    else
        echo "[playerbot-migrate] WARNING: could not change the bonus table" >&2
    fi
fi
# r40250's monster elements: lightning (bit 11) and wind (bit 14) back on the
# monsters the official data gives them (47 and 63), off the ones the package
# put the bits on. A resistance line works against a monster's element
# (apply_elemental_resistances). Once.
elem_done=$(db -e "SELECT COUNT(*) FROM player.playerbot_migrations WHERE name = 'mob_elements_r40250_2231';" 2>/dev/null || echo x)
if [ "$elem_done" = "0" ]; then
    if elem_out=$(db_retry -e "
        START TRANSACTION;
        UPDATE world.mob_proto SET setRaceFlag = (setRaceFlag + 0) & ~2048
         WHERE ((setRaceFlag + 0) & 2048) <> 0 AND vnum NOT IN (1306, 1307, 1308, 1309, 1310, 1334, 1401, 1402, 1403, 1601, 1602, 1603, 2401, 2402, 2403, 2404, 2411, 2412, 2413, 2414, 2431, 2432, 2433, 2434, 2451, 2452, 2453, 2454, 2491, 2492, 2493, 2494, 2495, 3101, 3102, 3103, 3104, 3105, 3190, 3191, 3551, 3552, 3553, 3554, 3555, 3595, 3596);
        UPDATE world.mob_proto SET setRaceFlag = (setRaceFlag + 0) | 2048
         WHERE vnum IN (1306, 1307, 1308, 1309, 1310, 1334, 1401, 1402, 1403, 1601, 1602, 1603, 2401, 2402, 2403, 2404, 2411, 2412, 2413, 2414, 2431, 2432, 2433, 2434, 2451, 2452, 2453, 2454, 2491, 2492, 2493, 2494, 2495, 3101, 3102, 3103, 3104, 3105, 3190, 3191, 3551, 3552, 3553, 3554, 3555, 3595, 3596);
        UPDATE world.mob_proto SET setRaceFlag = (setRaceFlag + 0) & ~16384
         WHERE ((setRaceFlag + 0) & 16384) <> 0 AND vnum NOT IN (701, 702, 703, 704, 705, 706, 707, 731, 732, 733, 734, 735, 736, 737, 751, 752, 753, 754, 755, 756, 757, 771, 772, 773, 774, 775, 776, 777, 791, 792, 793, 794, 795, 796, 1301, 1302, 1303, 1304, 1305, 1331, 1332, 1333, 1335, 2091, 2092, 2093, 2094, 2095, 2191, 2192, 3201, 3202, 3203, 3204, 3205, 3290, 3291, 3301, 3302, 3303, 3304, 3305, 3390);
        UPDATE world.mob_proto SET setRaceFlag = (setRaceFlag + 0) | 16384
         WHERE vnum IN (701, 702, 703, 704, 705, 706, 707, 731, 732, 733, 734, 735, 736, 737, 751, 752, 753, 754, 755, 756, 757, 771, 772, 773, 774, 775, 776, 777, 791, 792, 793, 794, 795, 796, 1301, 1302, 1303, 1304, 1305, 1331, 1332, 1333, 1335, 2091, 2092, 2093, 2094, 2095, 2191, 2192, 3201, 3202, 3203, 3204, 3205, 3290, 3291, 3301, 3302, 3303, 3304, 3305, 3390);
        SELECT SUM(((setRaceFlag + 0) & 2048) <> 0), SUM(((setRaceFlag + 0) & 16384) <> 0) FROM world.mob_proto;
        INSERT IGNORE INTO player.playerbot_migrations (name, done_at) VALUES ('mob_elements_r40250_2231', NOW());
        COMMIT;
    "); then
        echo "[playerbot-migrate] monster elements as r40250 has them (lightning, wind): $(printf '%s' "$elem_out" | tr '\t\r\n' '   ')"
    else
        echo "[playerbot-migrate] WARNING: could not set the monster elements" >&2
    fi
fi
# The bonus table back to the package's (the operator, 27 September), with
# Max HP at 500, 1000, 1500 and 2000: what item_attr_global_2231 changed goes
# back to world.sql's rows and its five added lines come out (an item that
# rolled one keeps it). Only over what 2231 or the package wrote. Once.
attr_back=$(db -e "SELECT COUNT(*) FROM player.playerbot_migrations WHERE name = 'item_attr_mt2009_2232';" 2>/dev/null || echo x)
if [ "$attr_back" = "0" ]; then
    if attr_back_out=$(db_retry -e "
        START TRANSACTION;
        UPDATE world.item_attr SET prob = 28, lv1 = 500, lv2 = 500, lv3 = 1000, lv4 = 1500, lv5 = 2000
         WHERE apply = 'POINT_MAX_HP' AND ((prob = 35 AND lv1 = 500 AND lv2 = 500 AND lv3 = 1000 AND lv4 = 1500 AND lv5 = 2000)
            OR (lv1 = 300 AND lv2 = 500 AND lv3 = 800 AND lv4 = 1000 AND lv5 = 1500));
        UPDATE world.item_attr SET lv1 = 20, lv2 = 50, lv3 = 90, lv4 = 140, lv5 = 250, wrist = 5, foots = 5, neck = 5
         WHERE apply = 'POINT_MAX_SP' AND lv1 = 10 AND lv2 = 20 AND lv3 = 30 AND lv4 = 80 AND lv5 = 200;
        UPDATE world.item_attr SET lv1 = 2, lv2 = 4, lv3 = 6, lv4 = 8, lv5 = 12
         WHERE apply IN ('POINT_HP_REGEN', 'POINT_SP_REGEN') AND lv1 = 4 AND lv2 = 8 AND lv3 = 12 AND lv4 = 20 AND lv5 = 30;
        UPDATE world.item_attr SET body = 5, wrist = 5, head = 5
         WHERE apply IN ('POINT_MAX_STAMINA', 'POINT_ST_REGEN', 'POINT_SKILL_DURATION')
           AND weapon = 0 AND body = 0 AND wrist = 0 AND foots = 0 AND neck = 0 AND head = 0 AND shield = 0 AND ear = 0;
        UPDATE world.item_attr SET wrist = 5, ear = 5
         WHERE apply = 'POINT_REFLECT_ARROW'
           AND weapon = 0 AND body = 0 AND wrist = 0 AND foots = 0 AND neck = 0 AND head = 0 AND shield = 0 AND ear = 0;
        UPDATE world.item_attr SET foots = 5, neck = 5, shield = 5
         WHERE apply = 'POINT_MALL_EXPBONUS'
           AND weapon = 0 AND body = 0 AND wrist = 0 AND foots = 0 AND neck = 0 AND head = 0 AND shield = 0 AND ear = 0;
        DELETE FROM world.item_attr WHERE apply IN ('POINT_RESIST_FIRE', 'POINT_RESIST_ELEC', 'POINT_RESIST_WIND',
            'POINT_EXP_DOUBLE_BONUS', 'POINT_ITEM_DROP_BONUS');
        SELECT ROW_COUNT();
        INSERT IGNORE INTO player.playerbot_migrations (name, done_at) VALUES ('item_attr_mt2009_2232', NOW());
        COMMIT;
    "); then
        echo "[playerbot-migrate] bonus table as the package has it, Max HP 500-2000: $(printf '%s' "$attr_back_out" | tr -d ' \r\n') added line(s) taken out"
    else
        echo "[playerbot-migrate] WARNING: could not put the bonus table back" >&2
    fi
fi
# Broszura Szermierki (70031), Seon-Pyeong's recipe material, stacks to the
# 200 its row already says: the package left ITEM_FLAG_STACKABLE off, so
# every brochure took a cell (NerrVoVy, 27 September), as Tanaka's ear did.
# PROTO_FROM_DB: the db core reads it at boot. Idempotent.
db_retry -e "UPDATE world.item_proto SET flag = flag | 4 WHERE vnum = 70031 AND (flag & 4) = 0;" || echo "[playerbot-migrate] WARNING: could not make Broszura Szermierki stack" >&2
# The ItemShop's marriage page (indexes 201-299, which the client's
# ITEMSHOP_CATEGORY_MARRIAGE lists and client 2.0.47 shows) had no line at
# all: the engagement ring (the Old Lady's ring quest gives one too), the
# tuxedo, the wedding dress and the bouquet (the travelling peddler of a
# second village sells the three for yang too), and the Love Bird's Feather
# with the six harmony and love jewels that work on love points (xXxDaronxXx,
# 27 September). From level 25, the wedding's own level. A line the operator
# changed by hand is kept (INSERT IGNORE), and one deleted in the database
# editor stays deleted (common.m2_itemshop_removed). Idempotent.
db_retry -e "CREATE TABLE IF NOT EXISTS common.m2_itemshop_removed (\`index\` INT NOT NULL PRIMARY KEY, removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB; INSERT IGNORE INTO common.itemshop_items (\`index\`, vnum, count, price, currency, minLevel) SELECT s.i, s.v, s.c, s.p, s.cur, s.lv FROM (SELECT 201 AS i, 70301 AS v, 1 AS c, 19 AS p, 'DRAGON_COIN' AS cur, 25 AS lv UNION ALL SELECT 202, 11901, 1, 49, 'DRAGON_COIN', 25 UNION ALL SELECT 203, 11903, 1, 49, 'DRAGON_COIN', 25 UNION ALL SELECT 204, 50201, 1, 9, 'DRAGON_COIN', 25 UNION ALL SELECT 205, 71068, 1, 29, 'DRAGON_COIN', 25 UNION ALL SELECT 206, 71069, 1, 39, 'DRAGON_COIN', 25 UNION ALL SELECT 207, 71070, 1, 39, 'DRAGON_COIN', 25 UNION ALL SELECT 208, 71071, 1, 39, 'DRAGON_COIN', 25 UNION ALL SELECT 209, 71072, 1, 39, 'DRAGON_COIN', 25 UNION ALL SELECT 210, 71073, 1, 39, 'DRAGON_COIN', 25 UNION ALL SELECT 211, 71074, 1, 39, 'DRAGON_COIN', 25) AS s WHERE s.i NOT IN (SELECT \`index\` FROM common.m2_itemshop_removed);" || echo "[playerbot-migrate] WARNING: could not fill the ItemShop's marriage page" >&2
# Twenty change stones (Zaczarowanie Przedmiotu, 71084) for 1035 Dragon
# Coins - the four-pack's price a stone (608: four for 207) - on the
# scrolls and books page (601-699): the line blasty's bonus switcher buys
# ten at a time, 200 stones, when its player has switched the purchase on
# and the bag holds fewer than 200 (client-root/uiswitchbot.py, 7 October).
# The bots never buy it: a need for change stones is four at most
# (playerbot_itemshop_rules.h). The price step below prices it like every
# line. A line the operator changed by hand is kept (INSERT IGNORE), one
# deleted in the database editor stays deleted (common.m2_itemshop_removed),
# and the switcher buys nothing at an index that sells anything else.
# Idempotent.
db_retry -e "CREATE TABLE IF NOT EXISTS common.m2_itemshop_removed (\`index\` INT NOT NULL PRIMARY KEY, removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB; INSERT IGNORE INTO common.itemshop_items (\`index\`, vnum, count, price, currency, minLevel) SELECT s.i, s.v, s.c, s.p, s.cur, s.lv FROM (SELECT 617 AS i, 71084 AS v, 20 AS c, 1035 AS p, 'DRAGON_COIN' AS cur, 0 AS lv) AS s WHERE s.i NOT IN (SELECT \`index\` FROM common.m2_itemshop_removed);" || echo "[playerbot-migrate] WARNING: could not add the ItemShop's twenty change stones" >&2
# BEGIN collector schema
# The collector's warehouse (Magazyn kolekcjonera, playerbot_collector_rules.h):
# a player's storage entry is the item's own row of player.item in the window
# COLLECTOR. The db core writes a window as its number - COLLECTOR is 11, after
# the package's ten - and a row written with an index the ENUM lacks loses its
# window, so the value is appended once, and only to the package's exact ten. A
# COLLECTOR anywhere else, or anything else, is somebody's own schema: left
# alone with a warning, and both cores keep the warehouse shut (they ask for
# exactly these eleven at boot). The warehouse's statements are all or nothing
# only on InnoDB, so a player.item of another engine is left alone too: on
# InnoDB a value appended to an ENUM is a change of the table's definition and
# of no row, where another engine would copy the table, and converting one is
# the operator's, with a backup, never this script's. The bots never use the
# window.
coll_type=$(db -e "SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='player' AND TABLE_NAME='item' AND COLUMN_NAME='window';" 2>/dev/null || echo x)
coll_item_engine=$(db -e "SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='player' AND TABLE_NAME='item';" 2>/dev/null || echo x)
case "$coll_type" in
    "enum('INVENTORY','EQUIPMENT','SAFEBOX','MALL','DRAGON_SOUL_INVENTORY','BELT_INVENTORY','GROUND','IKASHOP_OFFLINESHOP','IKASHOP_SAFEBOX','IKASHOP_AUCTION','COLLECTOR')")
        ;;
    "enum('INVENTORY','EQUIPMENT','SAFEBOX','MALL','DRAGON_SOUL_INVENTORY','BELT_INVENTORY','GROUND','IKASHOP_OFFLINESHOP','IKASHOP_SAFEBOX','IKASHOP_AUCTION')")
        if [ "$coll_item_engine" != "InnoDB" ]; then
            echo "[playerbot-migrate] WARNING: player.item is $coll_item_engine, not InnoDB; COLLECTOR is not added and the collector's warehouse stays shut" >&2
        elif db_retry -e "ALTER TABLE player.item MODIFY \`window\` ENUM('INVENTORY','EQUIPMENT','SAFEBOX','MALL','DRAGON_SOUL_INVENTORY','BELT_INVENTORY','GROUND','IKASHOP_OFFLINESHOP','IKASHOP_SAFEBOX','IKASHOP_AUCTION','COLLECTOR') NOT NULL;"; then
            echo "[playerbot-migrate] player.item.window takes COLLECTOR (the collector's warehouse)"
        else
            echo "[playerbot-migrate] WARNING: could not add COLLECTOR to player.item.window; the collector's warehouse stays shut" >&2
        fi
        ;;
    *)
        echo "[playerbot-migrate] WARNING: player.item.window is not the package's ($coll_type); the collector's warehouse stays shut" >&2
        ;;
esac
# The account's tier, revision, migration and the op that bought its step
# (collector_account), and an entry's favourite, lock and the time it was
# last stored into (collector_entry). The db core makes neither; they are made
# here, and a collector_account made before the step's op is given it.
db_retry -e "CREATE TABLE IF NOT EXISTS player.collector_account (account_id INT UNSIGNED NOT NULL PRIMARY KEY, tier TINYINT UNSIGNED NOT NULL DEFAULT 0, revision INT UNSIGNED NOT NULL DEFAULT 0, layout TINYINT UNSIGNED NOT NULL DEFAULT 1, migrated_items INT UNSIGNED NOT NULL DEFAULT 0, migrated_units BIGINT UNSIGNED NOT NULL DEFAULT 0, migrated_at DATETIME NULL, tier_paid_pid INT UNSIGNED NOT NULL DEFAULT 0, tier_paid_at DATETIME NULL, tier_op BIGINT UNSIGNED NOT NULL DEFAULT 0, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=latin1;" || echo "[playerbot-migrate] WARNING: could not create player.collector_account" >&2
db_retry -e "ALTER TABLE player.collector_account ADD COLUMN IF NOT EXISTS tier_op BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER tier_paid_at;" || echo "[playerbot-migrate] WARNING: could not add tier_op to player.collector_account" >&2
db_retry -e "CREATE TABLE IF NOT EXISTS player.collector_entry (item_id INT UNSIGNED NOT NULL PRIMARY KEY, account_id INT UNSIGNED NOT NULL, flags TINYINT UNSIGNED NOT NULL DEFAULT 0, stored_at INT UNSIGNED NOT NULL DEFAULT 0, KEY account_idx (account_id)) ENGINE=InnoDB DEFAULT CHARSET=latin1;" || echo "[playerbot-migrate] WARNING: could not create player.collector_entry" >&2
coll_innodb=$(db -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='player' AND TABLE_NAME IN ('item','player','collector_account','collector_entry') AND ENGINE='InnoDB';" 2>/dev/null || echo x)
coll_innodb=$(printf '%s' "$coll_innodb" | tr -d '[:space:]')
if [ "$coll_innodb" != "4" ]; then
    echo "[playerbot-migrate] WARNING: $coll_innodb of player.item, player.player, collector_account and collector_entry are InnoDB; the collector's warehouse stays shut until all four are" >&2
fi
# A tombstone - a row one of the warehouse's statements used up, count 0 - is
# never loaded; the db core deletes an account's at its next open, and every
# one goes here, while no core runs.
coll_tombs=$(db_retry -e "DELETE FROM player.item WHERE \`window\`='COLLECTOR' AND count=0; SELECT ROW_COUNT();" 2>/dev/null || echo x)
coll_tombs=$(printf '%s' "$coll_tombs" | tr -d '[:space:]')
if [ "$coll_tombs" = "x" ]; then
    echo "[playerbot-migrate] WARNING: could not clear the collector's warehouse tombstones" >&2
elif [ -n "$coll_tombs" ] && [ "$coll_tombs" != "0" ]; then
    echo "[playerbot-migrate] collector's warehouse: $coll_tombs tombstone row(s) cleared"
fi
# END collector schema
# fish_log came from r40250's dump and has that engine's eight columns,
# while this one writes six - so every catch failed with errno 1136 and the
# table is empty on every 2.x world that ever ran. CREATE IF NOT EXISTS
# cannot repair a table that already exists with the wrong shape, so the
# old one is dropped here, before log_schema.sql below recreates it.
# Recognised by a column this engine never writes; a table already in the
# right shape, and whatever history it holds, is left alone.
fish_old=$(db -e "
    SELECT COUNT(*) FROM information_schema.columns
     WHERE table_schema='log' AND table_name='fish_log' AND column_name='map_index';
" 2>/dev/null || echo 0)
if [ "$fish_old" = "1" ]; then
    echo "[playerbot-migrate] fish_log has the r40250 shape and cannot be written; rebuilding it"
    db_retry -e "DROP TABLE IF EXISTS log.fish_log;"
fi
# The log tables the engine writes and the package dump lacks (port/logschemify.py).
if [ -s /opt/playerbot/log_schema.sql ]; then
    if db_retry < /opt/playerbot/log_schema.sql 2>/tmp/logschema.err; then
        echo "[playerbot-migrate] log schema checked"
    else
        echo "[playerbot-migrate] WARNING: log schema failed:" >&2
        head -3 /tmp/logschema.err >&2
    fi
fi

itemshop_schema=/opt/playerbot/itemshop_schema.sql
if [ -s "$itemshop_schema" ]; then
    if [ -n "${M2_DB_ROOT_PASSWORD:-}" ]; then
        if MYSQL_PWD="$M2_DB_ROOT_PASSWORD" mariadb --protocol=tcp --host="$M2_DB_HOST" \
                --port="$M2_DB_PORT" --user=root --default-character-set=utf8mb4 \
                < "$itemshop_schema" 2>/tmp/itemshop.err; then
            echo "[playerbot-migrate] itemshop schema applied"
        else
            echo "[playerbot-migrate] WARNING: itemshop schema failed:" >&2
            head -3 /tmp/itemshop.err >&2
        fi
    else
        echo "[playerbot-migrate] WARNING: M2_DB_ROOT_PASSWORD not set; itemshop schema skipped" >&2
    fi
fi

# A developer may keep more persistent bots than the public 350-row seed. When
# that world matters, make its minimum size explicit in .env. This catches the
# easy-to-miss case where Docker is pointed at another daemon or a fresh volume:
# fail before the canonical seed can make the empty world look legitimate.
existing_bot_count=$(db -e "
    SELECT COUNT(*)
      FROM player.player
     WHERE name LIKE 'bot%';
")
if [ "$expected_existing_bots" -gt 0 ] && [ "$existing_bot_count" -lt "$expected_existing_bots" ]; then
    echo "[playerbot-migrate] FATAL: persistent-world guard expected at least $expected_existing_bots bots, found $existing_bot_count" >&2
    echo "[playerbot-migrate] FATAL: check the Docker context/daemon and the db-data volume before starting the game" >&2
    exit 1
fi
if [ "$expected_existing_bots" -gt 0 ]; then
    echo "[playerbot-migrate] persistent-world guard satisfied: $existing_bot_count bots present (minimum $expected_existing_bots)"
fi

# A bot whose saved map is not one this server hosts can never be spawned: the
# character load asks the sectree manager for the position, gets nothing, and
# gives up - the same two bots failed on all seventeen starts of one day, with
# no way to recover because the AI tick only ever sees bots that did spawn.
# Put them back on Bokjung's arrival point before the game core starts.
echo "[playerbot-migrate] checking for bots parked on maps this server does not host"
stranded=$(db -e "
    SELECT COUNT(*)
      FROM player.player p
      JOIN account.account a ON a.id = p.account_id
     WHERE LEFT(a.login, 10) = 'playerbot_'
       AND p.map_index NOT IN (1, 3, 4, 5, 6, 107, 81, 110, 111, 112, 113, 181, 182, 183, 200, 250, 302, 304,
                               21, 23, 24, 25, 26, 61, 63, 64, 65, 69, 70, 71, 104, 108, 109, 79, 216, 73,
                               41, 43, 44, 45, 46, 62, 66, 67, 68, 72, 90, 208, 301, 303, 351);
")
if [ -n "$stranded" ] && [ "$stranded" -gt 0 ] 2>/dev/null; then
    # Back to its OWN kingdom's second map, not always Chunjo's: a Jinno bot
    # dropped on Bokjung's arrival point is a bot in a foreign town with none
    # of its services in reach. The three points are the arrivals of each
    # kingdom's M1->M2 gate, read out of npc.txt (tools/dump_world_catalog.py);
    # Chunjo keeps the exact point this step has always used.
    db_retry -e "
        UPDATE player.player p
          JOIN account.account a ON a.id = p.account_id
          LEFT JOIN player.player_index pi ON pi.id = a.id
           SET p.map_index = CASE pi.empire WHEN 1 THEN 3 WHEN 3 THEN 43 ELSE 23 END,
               p.x = CASE pi.empire WHEN 1 THEN 400200 WHEN 3 THEN 906400 ELSE 145500 END,
               p.y = CASE pi.empire WHEN 1 THEN 899500 WHEN 3 THEN 221400 ELSE 240000 END
         WHERE LEFT(a.login, 10) = 'playerbot_'
           AND p.map_index NOT IN (1, 3, 4, 5, 6, 107, 81, 110, 111, 112, 113, 181, 182, 183, 200, 250, 302, 304,
                               21, 23, 24, 25, 26, 61, 63, 64, 65, 69, 70, 71, 104, 108, 109, 79, 216, 73,
                               41, 43, 44, 45, 46, 62, 66, 67, 68, 72, 90, 208, 301, 303, 351);
    "
    echo "[playerbot-migrate] moved $stranded bot(s) back to their own kingdom"
fi

# A negative alignment on a bot is a bug's footprint, not a history: a bot has
# no quarrel with its own kingdom. From 2.0.39 a duellist's blow went through
# CHARACTER::Damage without asking whether the engine would allow it, so a
# challenger struck before the other side had agreed and a winner went on
# striking the respawned loser. The engine counted each such kill as a murder -
# minus twenty thousand, shared over the killer's party - and bots of level
# nine walked about as "Zlosliwy" (98 on our own world, the lowest at -151002).
# Cleared here, before any core holds the bots in memory: a running core writes
# its cached alignment back over an UPDATE.
negative=$(db -e "
    SELECT COUNT(*)
      FROM player.player p
      JOIN account.account a ON a.id = p.account_id
     WHERE LEFT(a.login, 10) = 'playerbot_'
       AND p.alignment < 0;
")
if [ -n "$negative" ] && [ "$negative" -gt 0 ] 2>/dev/null; then
    db_retry -e "
        UPDATE player.player p
          JOIN account.account a ON a.id = p.account_id
           SET p.alignment = 0
         WHERE LEFT(a.login, 10) = 'playerbot_'
           AND p.alignment < 0;
    "
    echo "[playerbot-migrate] cleared the negative alignment of $negative bot(s)"
fi

# There used to be a step here that pulled every bot outside Orc Valley's
# central island back onto it, from the days when the navigation refused
# water and the island was all a bot could reach. The bridges are crossings
# now and the hubs span the whole valley - the Fanatic islands in the north,
# the Black Orc camps in the south - so that step moved 207 bots off their
# hunting grounds at every start. Gone on purpose.

# The registry's own size is written into the seed, so the wrapper never has to
# be edited in step with it. Hardcoding 350 here survived the move to a
# 1000-character cohort only because the old range happened to be a prefix of
# the new one.
pid_range=$(grep -o 'registry is not exactly PID [0-9]*\.\.[0-9]*' "$seed" | head -1 | sed 's/.*PID //')
first_pid=${pid_range%%..*}
last_pid=${pid_range##*..}
case "${first_pid:-}${last_pid:-}" in
    ''|*[!0-9]*)
        echo "[playerbot-migrate] FATAL: cannot read the PID range from $seed" >&2
        exit 1
        ;;
esac

before=$(db -e "
    SELECT COUNT(*)
      FROM player.player
     WHERE id BETWEEN $first_pid AND $last_pid;
")

# The rates of a world that has never had any, before the cores start. On this
# engine a rate is not a rewritten table but three event flags (player.quest,
# dwPID 0) that CQuestManager::SetEventFlag maps onto CHARACTER_MANAGER's
# multipliers, and until somebody presses "Zastosuj" in the panel those rows do
# not exist - so a fresh world ran at 100% whatever the panel's own table said.
# It said 650% experience, seeded into web_admin_rates by the panel's schema
# for a test cycle long ago, and that number reached every player as a promise
# the game never kept: the panel showed it, the bots levelled at 100%, and the
# first press of the button - even without touching a field - was what made it
# real (NerrVoVy and Tieru, 20 September).
#
# So the numbers the launcher asked for are written here, into both places at
# once, and only while the flags are absent: a world that has been set from the
# panel is never touched again, whatever this file says. That is also why the
# panel's schema no longer seeds the table.
rate_ok() {
    # A newline, because awk reads no record from an empty input and
    # the substitution would then be empty - not a number, so the SQL
    # below would be a syntax error rather than a default.
    printf '%s\n' "$1" | tr -d ' \r' | awk -v d="$2" '{ v = $1 + 0; if (v < 1 || v > 10000) v = d; printf "%d", v }'
}
r_exp=$(rate_ok "${M2_RATE_EXP:-100}" 100)
r_drop=$(rate_ok "${M2_RATE_DROP:-100}" 100)
r_yang=$(rate_ok "${M2_RATE_YANG:-100}" 100)
# Yang drops no higher than 1000% in any world (Iwakura, 2 October): ten
# thousand made every price of his sheet meaningless. A number over it is
# that ceiling, here and, below, in a world the panel already set.
YANG_RATE_MAX=1000
[ "$r_yang" -gt "$YANG_RATE_MAX" ] && r_yang=$YANG_RATE_MAX
db_retry -e "CREATE TABLE IF NOT EXISTS player.web_admin_rates (
        name VARCHAR(24) PRIMARY KEY, value INT NOT NULL DEFAULT 100);" >/dev/null 2>&1 \
    || echo "[playerbot-migrate] WARNING: could not make player.web_admin_rates" >&2
rates_set=$(db -e "SELECT COUNT(*) FROM player.quest WHERE dwPID = 0 AND szName = 'mob_exp';" 2>/dev/null || echo x)
if [ "$rates_set" = "x" ]; then
    echo "[playerbot-migrate] WARNING: could not read the rate flags; leaving them alone" >&2
elif [ "$rates_set" = "0" ]; then
    if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
            (0, 'mob_exp', '', $r_exp),   (0, 'mob_exp_buyer', '', $r_exp),
            (0, 'mob_item', '', $r_drop), (0, 'mob_item_buyer', '', $r_drop),
            (0, 'mob_gold', '', $r_yang), (0, 'mob_gold_buyer', '', $r_yang);
        REPLACE INTO player.web_admin_rates (name, value) VALUES
            ('exp', $r_exp), ('drop', $r_drop), ('yang', $r_yang);"; then
        echo "[playerbot-migrate] fresh world: experience ${r_exp}%, item drops ${r_drop}%, yang ${r_yang}%"
    else
        echo "[playerbot-migrate] WARNING: could not write the fresh world's rates" >&2
    fi
    # And whether that world's bots wait at the door. The core reads this file
    # on the weights clock and, the first time it is asked, before its own
    # first tick - the bootstrap spawns a cohort before any tick runs, so a
    # file written afterwards would hold a door the crowd had already walked
    # through. Written only for a fresh world, because on any other one it is
    # the panel's button that owns it.
    if [ -d /opt/m2spool ]; then
        if [ "$(printf '%s' "${M2_PLAYERBOT_START_HELD:-0}" | tr -d ' \r')" = "1" ]; then
            printf '1\n' > /opt/m2spool/playerbot_hold 2>/dev/null \
                && echo "[playerbot-migrate] the bots will wait at the door until you let them in" \
                || echo "[playerbot-migrate] WARNING: could not hold the bots (/opt/m2spool not writable)" >&2
        else
            printf '0\n' > /opt/m2spool/playerbot_hold 2>/dev/null || true
        fi
        chmod 0664 /opt/m2spool/playerbot_hold 2>/dev/null || true
    fi
fi
# A world the panel set over the yang ceiling is brought down to it (its
# own block, after the fresh world's: tests/playerbot_migrate_rates_test.sh
# reads that one up to its first fi).
yang_over=$(db -e "SELECT COUNT(*) FROM player.quest WHERE dwPID = 0
        AND szName IN ('mob_gold', 'mob_gold_buyer') AND lValue > $YANG_RATE_MAX;" 2>/dev/null || echo x)
if [ "$yang_over" != "x" ] && [ "$yang_over" != "0" ]; then
    if db_retry -e "UPDATE player.quest SET lValue = $YANG_RATE_MAX WHERE dwPID = 0
            AND szName IN ('mob_gold', 'mob_gold_buyer') AND lValue > $YANG_RATE_MAX;
        UPDATE player.web_admin_rates SET value = $YANG_RATE_MAX WHERE name = 'yang' AND value > $YANG_RATE_MAX;"; then
        echo "[playerbot-migrate] yang drops: the world's rate was over ${YANG_RATE_MAX}% - it is ${YANG_RATE_MAX}% now"
    else
        echo "[playerbot-migrate] WARNING: could not bring the yang rate down to ${YANG_RATE_MAX}%" >&2
    fi
fi

# The world's difficulty, as event flags in seconds (player.quest, dwPID 0 -
# what the db core loads at boot and pushes to every game core, the package's
# own idiom for a world-wide switch). quest/m2_difficulty.lua reads them: the
# Biologist's wait between two hand-ins and the stable keeper's four waits
# (the pony, each Horse Book, the medal trainings of 1-10 and of 11-19). The
# presets scale the package's own numbers - hard is what it shipped with,
# medium a third of it, easy none (what 2.0.55 and 2.0.56 gave everybody) -
# and custom takes the hour counts from .env, the horse's for every wait.
# The wait between two skill books is the engine's (m2_book_wait, playerbotify
# apply_book_wait) and the bots' own (m2_bot_book_wait), the package's 21 hours
# on hard (drip9660, 23 September).
# Written before the seed, which may leave early on a foreign cohort.
#
# The classic panel's difficulty card sets the same flags live, so .env is
# applied only when it changed since the last start (m2_difficulty_env holds
# what it said): a change made in the panel survives a restart until the
# launcher's difficulty is changed, and the one changed last is the one kept.
difficulty=$(printf '%s' "${M2_DIFFICULTY:-easy}" | tr 'A-Z' 'a-z' | tr -d ' \r')
hours_to_seconds() {
    printf '%s\n' "$1" | tr -d ' \r' | awk '{ h = $1 + 0; if (h < 0) h = 0; if (h > 8760) h = 8760; printf "%d", h * 3600 }'
}
case "$difficulty" in
    medium) dlevel=1; bio=28800; hbuy=14400; hup=14400; htr=21600; htr2=25200; book=25200; botbook=25200 ;;
    hard)   dlevel=2; bio=86400; hbuy=43200; hup=43200; htr=64800; htr2=75600; book=75600; botbook=75600 ;;
    custom)
        dlevel=3
        bio=$(hours_to_seconds "${M2_BIOLOGIST_WAIT_HOURS:-0}")
        hbuy=$(hours_to_seconds "${M2_HORSE_WAIT_HOURS:-0}")
        hup=$hbuy; htr=$hbuy; htr2=$hbuy
        book=$(hours_to_seconds "${M2_BOOK_WAIT_HOURS:-0}")
        botbook=$(hours_to_seconds "${M2_BOT_BOOK_WAIT_HOURS:-0}") ;;
    *)      difficulty=easy; dlevel=0; bio=0; hbuy=0; hup=0; htr=0; htr2=0; book=0; botbook=0 ;;
esac
dsig=$(printf '%s|%s|%s|%s|%s|%s|%s|%s|%s' "$difficulty" "$bio" "$hbuy" "$hup" "$htr" "$htr2" "$book" "$botbook" 1 | cksum | awk '{ print $1 % 2000000000 }')
dprev=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_difficulty_env' LIMIT 1" 2>/dev/null | tr -d ' \r')
if [ -n "$dprev" ] && [ "$dprev" = "$dsig" ]; then
    echo "[playerbot-migrate] difficulty: .env unchanged since the last start - the flags stay as the panel or the last start left them"
elif db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
        (0, 'm2_difficulty', '', $dlevel),
        (0, 'm2_biologist_wait', '', $bio),
        (0, 'm2_horse_buy_wait', '', $hbuy),
        (0, 'm2_horse_upgrade_wait', '', $hup),
        (0, 'm2_horse_train_wait', '', $htr),
        (0, 'm2_horse_train2_wait', '', $htr2),
        (0, 'm2_book_wait', '', $book),
        (0, 'm2_bot_book_wait', '', $botbook),
        (0, 'm2_difficulty_env', '', $dsig);"; then
    echo "[playerbot-migrate] difficulty: $difficulty (Biologist wait ${bio}s, horse: buy ${hbuy}s upgrade ${hup}s train ${htr}s/${htr2}s, books: players ${book}s bots ${botbook}s)"
else
    echo "[playerbot-migrate] WARNING: could not write the difficulty flags; the quests keep the last ones" >&2
fi

# The item exchange's chances for a custom difficulty (quest/m2_difficulty.lua
# and the bots' dust, GetPlayerBotExchangeChance): .env's
# M2_EXCHANGE_DUST_CHANCE, _PARCHMENT_ and _MATERIAL_, a percent, and 0 or
# nothing for the package's own (100, 100 and 55). The presets follow the
# level flag alone, and the panel writes no such flag, so these are applied
# at every start (Tieru, 30 September, "Procenty na wytwarzanie").
exchange_percent() {
    printf '%s\n' "$1" | tr -d ' \r%' | awk '{ p = int($1 + 0); if (p < 0) p = 0; if (p > 100) p = 100; printf "%d", p }'
}
xdust=$(exchange_percent "${M2_EXCHANGE_DUST_CHANCE:-0}")
xparch=$(exchange_percent "${M2_EXCHANGE_PARCHMENT_CHANCE:-0}")
xmat=$(exchange_percent "${M2_EXCHANGE_MATERIAL_CHANCE:-0}")
if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
        (0, 'm2_exchange_dust_chance', '', $xdust),
        (0, 'm2_exchange_parchment_chance', '', $xparch),
        (0, 'm2_exchange_material_chance', '', $xmat);"; then
    echo "[playerbot-migrate] exchange chances for a custom difficulty: dust $xdust parchment $xparch materials $xmat (0 = the package's)"
else
    echo "[playerbot-migrate] WARNING: could not write the exchange chances; the quests keep the last ones" >&2
fi

# The apprentice chest (Skrzynia Ucznia) is the world's choice, one switch
# for people and bots alike: the event flag m2_starter_chest_off, which
# starter_chest.quest asks at a person's first login, the seed below asks
# for every bot it creates, and the cores ask for the bots in the world
# (off, a bot keeps and opens no chest of the chain: playerbot_gear.h).
# .env's M2_STARTER_CHEST (the launcher's difficulty window and new-world
# dialog, seban latino's idea of 22 September; on unless it says 0) - or
# M2_PLAYERBOT_DISABLE_STUDENT_CHEST=1, the name Seban's own integration
# gives the same choice - is applied only when it changed since the last
# start (m2_starter_chest_env holds what it said): both panels set the flag
# live (web_admin.quest STARTER_CHEST), and a choice made there outlives a
# restart until the launcher's is changed, the difficulty's rule. Until 28
# September the flag was written from .env at every start and the seed
# gave every bot its chest whatever it said.
starter_off=0
case "$(printf '%s' "${M2_STARTER_CHEST:-1}" | tr 'A-Z' 'a-z' | tr -d ' \r')" in
    0|off|no|false) starter_off=1 ;;
esac
case "$(printf '%s' "${M2_PLAYERBOT_DISABLE_STUDENT_CHEST:-0}" | tr 'A-Z' 'a-z' | tr -d ' \r')" in
    1|on|yes|true) starter_off=1 ;;
esac
starter_env=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_starter_chest_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$starter_env" != "$((starter_off + 1))" ]; then
    if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
            (0, 'm2_starter_chest_off', '', $starter_off),
            (0, 'm2_starter_chest_env', '', $((starter_off + 1)));"; then
        echo "[playerbot-migrate] apprentice chest: $([ "$starter_off" = 1 ] && echo off || echo on) (from .env)"
    else
        echo "[playerbot-migrate] WARNING: could not write the apprentice chest flag; the quest keeps the last one" >&2
    fi
fi
# What the world says now: .env's, or a panel's made since.
case "$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_starter_chest_off' LIMIT 1;" 2>/dev/null | tr -d ' \r')" in
    0) starter_off=0 ;;
    [1-9]*) starter_off=1 ;;
esac
echo "[playerbot-migrate] apprentice chest for people and bots: $([ "$starter_off" = 1 ] && echo off || echo on)"
# A bot's apprentice chest is the seed's - Skrzynia Ucznia I lies in its
# bag from the start - and the quest cannot tell a bot from a person, so a
# bot still at level five or under at its first login got a second one: on
# a new world, the whole cohort (Iwakura, 26 September). The seed marks the
# bots it creates; this marks the ones seeded before it did, and changes
# nothing on a start that finds them marked. A companion is one of these
# identities, so a player gets no chest by making one either. (The quest
# asks pc.is_playerbot() as well since 28 September.)
if [ "$(db -e "SELECT COUNT(*) FROM information_schema.tables
              WHERE table_schema='common' AND table_name='playerbot_seed_state';" 2>/dev/null)" = 1 ]; then
    if db_retry -e "INSERT INTO player.quest (dwPID, szName, szState, lValue)
            SELECT l.pid, 'starter_chest', 'given', 1
              FROM common.playerbot_seed_state AS l
             WHERE l.state IN ('complete','adopted')
            ON DUPLICATE KEY UPDATE lValue = GREATEST(lValue, 1);"; then
        echo "[playerbot-migrate] apprentice chest: a bot's is the one the seed gave it"
    else
        echo "[playerbot-migrate] WARNING: could not mark the bots' apprentice chest as given" >&2
    fi
    # Off, no bot keeps a chest of the chain: every one in a registered
    # bot's bag goes before the cores start - the chest the seed gave each
    # identity that has never been in the world (1 955 on m2zip, every one of
    # them a bot that had never played: the rest had opened theirs), and the
    # chain the others carry. A core still running beside an update may
    # write back the few its online bots hold, and the cores take those out
    # themselves, through the engine (ManagePlayerBotProgressionChests): a
    # DELETE alone on a running world comes back from the db core's cache.
    # Never a person's, and never a companion's, whose bag is its owner's too.
    if [ "$starter_off" = 1 ]; then
        starter_keep=""
        if [ "$(db -e "SELECT COUNT(*) FROM information_schema.tables
                      WHERE table_schema='player' AND table_name='playerbot_sidekick';" 2>/dev/null)" = 1 ]; then
            starter_keep="AND l.pid NOT IN (SELECT k.sidekick_pid FROM player.playerbot_sidekick AS k)"
        fi
        if starter_gone=$(db_retry -e "DELETE FROM player.item
                 WHERE window = 'INVENTORY'
                   AND (vnum BETWEEN 50187 AND 50196 OR vnum IN (50212, 50213))
                   AND owner_id IN (SELECT l.pid
                                      FROM common.playerbot_seed_state AS l
                                      JOIN player.player AS p ON p.id = l.pid
                                      JOIN account.account AS a ON a.id = p.account_id
                                     WHERE l.state IN ('complete', 'adopted')
                                       AND a.login LIKE 'playerbot%' $starter_keep);
                SELECT ROW_COUNT();"); then
            starter_gone=$(printf '%s' "$starter_gone" | tr -d '[:space:]')
            if [ -n "$starter_gone" ] && [ "$starter_gone" != 0 ]; then
                echo "[playerbot-migrate] apprentice chest off: $starter_gone chest(s) taken out of the bots' bags"
            fi
        else
            echo "[playerbot-migrate] WARNING: could not take the apprentice chests out of the bots' bags; the cores take them out as the bots come in" >&2
        fi
    fi
fi

# Whether the world is played with Auto Lowy and with the companion
# (Towarzysz): the launcher's difficulty window writes M2_AUTOHUNT and
# M2_SIDEKICK, both on unless .env says 0 (Tieru, 25 September, for Drip's
# COOP without the auto hunt). Off, the server refuses the hunt's target
# and drop (m2_autohunt_off, playerbotify apply_auto_hunt_switch) and
# sends no Towarzysz letter, refuses its command and keeps companions out
# of the world (m2_sidekick_off). Event flags like the difficulty, so a
# change reaches the cores at the next start. The Dom Towarowy (M2_FLEA_MARKET,
# the same window, 27 September) is a third: off, flea_market.quest offers
# nothing at the merchant and every /flea_ command refuses
# (m2_flea_market_off, playerbotify apply_flea_market).
feature_off() {
    case "$(printf '%s' "$1" | tr 'A-Z' 'a-z' | tr -d ' \r')" in
        0|off|no|false) echo 1 ;;
        *)              echo 0 ;;
    esac
}
autohunt_off=$(feature_off "${M2_AUTOHUNT:-1}")
sidekick_off=$(feature_off "${M2_SIDEKICK:-1}")
flea_off=$(feature_off "${M2_FLEA_MARKET:-1}")
if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
        (0, 'm2_autohunt_off', '', $autohunt_off),
        (0, 'm2_sidekick_off', '', $sidekick_off),
        (0, 'm2_flea_market_off', '', $flea_off);"; then
    echo "[playerbot-migrate] Auto Lowy: $([ "$autohunt_off" = 1 ] && echo off || echo on), companions: $([ "$sidekick_off" = 1 ] && echo off || echo on), Dom Towarowy: $([ "$flea_off" = 1 ] && echo off || echo on)"
else
    echo "[playerbot-migrate] WARNING: could not write the Auto Lowy, companion and Dom Towarowy flags; the cores keep the last ones" >&2
fi
# The Dragon Stone Alchemy (M2_DRAGON_SOUL, the same window, 1 October):
# off, the package's dragon_soul quests send no letter, drop no shard and
# leave the Alchemist's two options out, the bots stand back, and every
# person's client hides the Alchemy (m2_dragon_soul_off;
# dragon_soul_switch.quest tells it). The classic panel's card sets the flag
# live (web_admin.quest DRAGON_SOUL), so .env is applied only when it
# changed since the last start (m2_dragon_soul_env holds what it said), the
# apprentice chest's rule: a choice made in the panel outlives a restart
# until the launcher's is changed. Written at every start until then, which
# the panel's choice would not have survived.
dragon_soul_off=$(feature_off "${M2_DRAGON_SOUL:-1}")
dragon_soul_env=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_dragon_soul_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$dragon_soul_env" != "$((dragon_soul_off + 1))" ]; then
    if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
            (0, 'm2_dragon_soul_off', '', $dragon_soul_off),
            (0, 'm2_dragon_soul_env', '', $((dragon_soul_off + 1)));"; then
        echo "[playerbot-migrate] Dragon Stone Alchemy: $([ "$dragon_soul_off" = 1 ] && echo off || echo on) (from .env)"
    else
        echo "[playerbot-migrate] WARNING: could not write the Dragon Stone Alchemy flag; the cores keep the last one" >&2
    fi
fi
# What the world says now: .env's, or the panel's made since.
case "$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_dragon_soul_off' LIMIT 1;" 2>/dev/null | tr -d ' \r')" in
    0) dragon_soul_off=0 ;;
    [1-9]*) dragon_soul_off=1 ;;
esac
echo "[playerbot-migrate] Dragon Stone Alchemy: $([ "$dragon_soul_off" = 1 ] && echo off || echo on)"
# The Alchemy's shard: every kill a Dragon Stone Shard at ds_drop percent
# (questlib.lua's drop_gamble_with_flag reads 1 to 100 and takes anything
# else for 10). The package's 10 is written where the world has no flag yet,
# so the chance is a number the database says rather than a fallback inside
# questlib; a game master's own (/e ds_drop N) stays through every start.
if db_retry -e "INSERT IGNORE INTO player.quest (dwPID, szName, szState, lValue) VALUES (0, 'ds_drop', '', 10);"; then
    ds_drop=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'ds_drop' AND szState = '' LIMIT 1;" 2>/dev/null | tr -d ' \r')
    echo "[playerbot-migrate] Dragon Stone Shard: ${ds_drop:-10}% a kill (ds_drop)"
else
    echo "[playerbot-migrate] WARNING: could not write the Dragon Stone Shard's ds_drop; the quest takes 10%" >&2
fi
# The shard stacks whatever hour it dropped (Kiciamol and the operator,
# 1 October): its row gave it a real-time limit of a day, so every shard
# carried its own end in socket0, and the engine merges equal sockets only -
# ten shards were ten cells. The quest keeps a bag under ten shards for each
# eye left (dragon_soul.quest converts ten on the pickup), so the day kept
# nothing in check. Only the package's own limit moves; while the row has
# none, the shards a bag already holds lose their end too, before any core
# loads them. PROTO_FROM_DB: the db core reads the row at boot. Idempotent.
db_retry -e "UPDATE world.item_proto SET limittype0 = 0, limitvalue0 = 0 WHERE vnum = 30270 AND limittype0 = 7 AND limitvalue0 = 86400; UPDATE player.item SET socket0 = 0 WHERE vnum = 30270 AND socket0 <> 0 AND (SELECT limittype0 FROM world.item_proto WHERE vnum = 30270) = 0;" || echo "[playerbot-migrate] WARNING: could not make the Dragon Stone Shard stack" >&2
# The Cor Draconis trades (Kuszaa and the operator, 1 October: "Cory
# powinny byc do handlu" - ten a character a day, and a player of one
# character had no other way to more). The package's boxes (50255-50260)
# carried ANTI_GIVE and ANTI_MYSHOP besides ANTI_DROP, ANTI_SELL and
# ANTI_STACK: a trade and any counter take them now, a resource trader's
# own included (playerbot_dragon_soul.h), and the merchant, the ground
# and a stack still do not. Only the package's own value moves, so an
# operator's flags stay; the client reads the same bits from its own
# table (port/protoify.py). PROTO_FROM_DB: the db core reads the rows at
# boot. Idempotent.
db_retry -e "UPDATE world.item_proto SET antiflag = 33152 WHERE vnum BETWEEN 50255 AND 50260 AND antiflag = 106880;" || echo "[playerbot-migrate] WARNING: could not make the Cor Draconis tradeable" >&2
# Auto Lowy for everybody (0) or only with the ItemShop's ticket (1): .env
# M2_AUTOHUNT_ITEM, which the launcher's difficulty window writes; the
# classic panel sets the flag live (web_admin.quest AUTOHUNT). The .env value
# is applied only when it changed since the last start (m2_autohunt_item_env),
# so a choice made in the panel outlives a restart.
case "$(printf '%s' "${M2_AUTOHUNT_ITEM:-0}" | tr 'A-Z' 'a-z' | tr -d ' \r')" in 1|on|yes|true) autohunt_item=1 ;; *) autohunt_item=0 ;; esac
autohunt_item_env=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_autohunt_item_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$autohunt_item_env" != "$((autohunt_item + 1))" ]; then
    if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES (0, 'm2_autohunt_item', '', $autohunt_item), (0, 'm2_autohunt_item_env', '', $((autohunt_item + 1)));"; then
        echo "[playerbot-migrate] Auto Lowy: $([ "$autohunt_item" = 1 ] && echo 'only with the ItemShop ticket' || echo 'for everybody') (from .env)"
    else
        echo "[playerbot-migrate] WARNING: could not write the Auto Lowy ticket flag" >&2
    fi
fi
# A new level-70 weapon alone gets the intrinsic sixth roll (Piciu713, 4 October).
# Apply .env only when changed, so a live panel choice survives a start.
unique70_bonus_off=$(feature_off "${M2_UNIQUE70_BONUS:-1}")
unique70_bonus_env=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_unique70_bonus_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$unique70_bonus_env" != "$((unique70_bonus_off + 1))" ]; then
    if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
            (0, 'm2_unique70_bonus_off', '', $unique70_bonus_off),
            (0, 'm2_unique70_bonus_env', '', $((unique70_bonus_off + 1)));"; then
        echo "[playerbot-migrate] Level-70 weapon sixth bonus: $([ "$unique70_bonus_off" = 1 ] && echo off || echo on) (from .env)"
    else
        echo "[playerbot-migrate] WARNING: could not write the Level-70 weapon sixth bonus flag; the cores keep the last one" >&2
    fi
fi
# A person's yang into the purse (1, patch 0010 as it always was) or on the
# ground as in the original game (0); a bot's and a companion's go to the
# purse either way (Nannato and Tieru, 7 October). The cores read
# m2_yang_ground at every kill. Apply .env only when changed, so a live
# panel choice survives a start.
yang_ground=$(feature_off "${M2_YANG_TO_PURSE:-1}")
yang_ground_env=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_yang_ground_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$yang_ground_env" != "$((yang_ground + 1))" ]; then
    if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
            (0, 'm2_yang_ground', '', $yang_ground),
            (0, 'm2_yang_ground_env', '', $((yang_ground + 1)));"; then
        echo "[playerbot-migrate] A person's yang: $([ "$yang_ground" = 1 ] && echo 'on the ground' || echo 'into the purse') (from .env)"
    else
        echo "[playerbot-migrate] WARNING: could not write the yang drop flag; the cores keep the last one" >&2
    fi
fi

# The world's monster health (the operator, 30 September, for Frelik's
# proposal): a percent of the max_hp of every monster, boss and Metin
# stone, which the cores apply at a spawn and to every one standing when
# the flag moves (m2_mob_hp; playerbotify apply_monster_health, the
# arithmetic in playerbot_mob_health_rules.h). .env's M2_MONSTER_HP -
# default (100, the game as it was made), easy (80) or a percent from 10
# to 300 - is applied only when it changed since the last start
# (m2_mob_hp_env holds what it said): the classic panel's card sets the
# flag live (web_admin.quest MOB_HP), and a choice made there outlives a
# restart until the launcher's is changed, the difficulty's rule.
mobhp=$(printf '%s' "${M2_MONSTER_HP:-default}" | tr 'A-Z' 'a-z' | tr -d ' \r%')
case "$mobhp" in
    ''|0|default|normal) mobhp=100 ;;
    easy) mobhp=80 ;;
    *[!0-9]*)
        echo "[playerbot-migrate] WARNING: M2_MONSTER_HP=$mobhp is not default, easy or a percent; the monsters keep the game's health" >&2
        mobhp=100 ;;
    *) mobhp=$(printf '%s\n' "$mobhp" | awk '{ p = int($1 + 0); if (p < 10) p = 10; if (p > 300) p = 300; printf "%d", p }') ;;
esac
mobhp_env=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_mob_hp_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$mobhp_env" = "$mobhp" ]; then
    echo "[playerbot-migrate] monster health: .env unchanged since the last start - the flag stays as the panel or the last start left it"
elif db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
        (0, 'm2_mob_hp', '', $mobhp),
        (0, 'm2_mob_hp_env', '', $mobhp);"; then
    echo "[playerbot-migrate] monster health: ${mobhp}% of max_hp for monsters, bosses and Metin stones (from .env)"
else
    echo "[playerbot-migrate] WARNING: could not write the monster health flag; the cores keep the last one" >&2
fi

# Metins apart from bosses (Iwakura's Patch 12, point 2): the /rates page's
# "Metiny i bossowie" respawn time (fastBossSpawn, and a map's own
# fastBossSpawn<map>) and count (m2_boss_count) are the bosses' alone now, and
# the Metin stones read fastMetinSpawn / fastMetinSpawn<map> and
# m2_metin_count (playerbotify apply_regen_metin_split). Once, at the first
# start after the update, every boss row is copied into its Metin row - a row
# the operator already wrote is kept (INSERT IGNORE) - so the world respawns
# as it did until the operator moves one of them; m2_regen_metin_split says
# it is done. Nothing written means both stay as the game has them.
regen_split=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_regen_metin_split' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$regen_split" != "1" ]; then
    if db_retry -e "INSERT IGNORE INTO player.quest (dwPID, szName, szState, lValue)
                SELECT 0, CONCAT('fastMetinSpawn', SUBSTRING(szName, 14)), szState, lValue FROM player.quest
                 WHERE dwPID = 0 AND szName LIKE 'fastBossSpawn%';
            INSERT IGNORE INTO player.quest (dwPID, szName, szState, lValue)
                SELECT 0, 'm2_metin_count', szState, lValue FROM player.quest
                 WHERE dwPID = 0 AND szName = 'm2_boss_count';
            REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES (0, 'm2_regen_metin_split', '', 1);"; then
        echo "[playerbot-migrate] Metins and bosses: the respawn time and count of 'Metiny i bossowie' copied to the Metins' own rows"
    else
        echo "[playerbot-migrate] WARNING: could not copy the respawn settings to the Metins' rows; they respawn as the game has them until the panel sets them" >&2
    fi
fi

# The world's chance of bonus lines on a dropped weapon or piece of armour
# (Tysiek and the operator, 7 October): a percent of the game's own chance,
# which the cores read at every such drop (m2_drop_bonus_pct; playerbotify
# apply_drop_bonus_chance, the arithmetic in playerbot_drop_bonus_rules.h).
# .env's M2_DROP_BONUS_PCT - default (100, the game as it was made) or a
# percent from 10 to 1000 - is applied only when it changed since the last
# start (m2_drop_bonus_pct_env holds what it said): the classic panel's card
# sets the flag live (web_admin.quest DROP_BONUS), and a choice made there
# outlives a restart until the launcher's is changed, the difficulty's rule.
dropbonus=$(printf '%s' "${M2_DROP_BONUS_PCT:-100}" | tr 'A-Z' 'a-z' | tr -d ' \r%')
case "$dropbonus" in
    ''|0|default|normal) dropbonus=100 ;;
    *[!0-9]*)
        echo "[playerbot-migrate] WARNING: M2_DROP_BONUS_PCT=$dropbonus is not default or a percent; drops keep the game's chance of bonuses" >&2
        dropbonus=100 ;;
    *) dropbonus=$(printf '%s\n' "$dropbonus" | awk '{ p = int($1 + 0); if (p < 10) p = 10; if (p > 1000) p = 1000; printf "%d", p }') ;;
esac
dropbonus_env=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_drop_bonus_pct_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$dropbonus_env" = "$dropbonus" ]; then
    echo "[playerbot-migrate] drop bonus chance: .env unchanged since the last start - the flag stays as the panel or the last start left it"
elif db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
        (0, 'm2_drop_bonus_pct', '', $dropbonus),
        (0, 'm2_drop_bonus_pct_env', '', $dropbonus);"; then
    echo "[playerbot-migrate] drop bonus chance: ${dropbonus}% of the game's chance of bonus lines on dropped weapons and armour (from .env)"
else
    echo "[playerbot-migrate] WARNING: could not write the drop bonus flag; the cores keep the last one" >&2
fi

# How fast the world's characters move (RapLow and the operator, 8 October,
# the bots too since the same evening): a percent of the game's own movement
# speed, which the cores put on every player's character - a person's, a
# bot's and a companion's - and on no monster (m2_move_speed_pct;
# playerbotify apply_move_speed_percent, the arithmetic in
# playerbot_move_speed_rules.h). .env's M2_MOVE_SPEED_PCT - default (100, the
# game as it was made) or a percent from 50 to 200 - is applied only when it
# changed since the last start (m2_move_speed_pct_env holds what it said):
# the classic panel's card sets the flag live (web_admin.quest MOVE_SPEED),
# and a choice made there outlives a restart until the launcher's is
# changed, the difficulty's rule.
movespeed=$(printf '%s' "${M2_MOVE_SPEED_PCT:-100}" | tr 'A-Z' 'a-z' | tr -d ' \r%')
case "$movespeed" in
    ''|0|default|normal) movespeed=100 ;;
    *[!0-9]*)
        echo "[playerbot-migrate] WARNING: M2_MOVE_SPEED_PCT=$movespeed is not default or a percent; players and bots keep the game's movement speed" >&2
        movespeed=100 ;;
    *) movespeed=$(printf '%s\n' "$movespeed" | awk '{ p = int($1 + 0); if (p == 0) p = 100; if (p < 50) p = 50; if (p > 200) p = 200; printf "%d", p }') ;;
esac
movespeed_env=$(db -N -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_move_speed_pct_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$movespeed_env" = "$movespeed" ]; then
    echo "[playerbot-migrate] movement speed of players and bots: .env unchanged since the last start - the flag stays as the panel or the last start left it"
elif db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
        (0, 'm2_move_speed_pct', '', $movespeed),
        (0, 'm2_move_speed_pct_env', '', $movespeed);"; then
    echo "[playerbot-migrate] movement speed of players and bots: ${movespeed}% of the game's (from .env)"
else
    echo "[playerbot-migrate] WARNING: could not write the movement speed flag; the cores keep the last one" >&2
fi

# The starter kit (the operator, 30 September, on Iwakura's proposal):
# what a player's new character and a bot the seed makes from now on start
# wearing - default nothing past what the game gives, medium the class's
# level-1 weapon and body armour at +5, easy the whole level-1 set at +9.
# .env's M2_STARTER_KIT, which the launcher's new-world window writes, is
# the event flag m2_starter_kit (starter_kit.quest, a person's character at
# level one) and the seed's @playerbot_seed_starter_kit below; the bots
# already made are never pending again and keep what they have.
kit_word=$(printf '%s' "${M2_STARTER_KIT:-default}" | tr 'A-Z' 'a-z' | tr -d ' \r')
case "$kit_word" in
    ''|0|default|none) starter_kit=0 ;;
    1|medium) starter_kit=1 ;;
    2|easy) starter_kit=2 ;;
    *)
        echo "[playerbot-migrate] WARNING: M2_STARTER_KIT=$kit_word is not default, medium or easy; no starter kit" >&2
        starter_kit=0 ;;
esac
case "$starter_kit" in
    1) kit_label='medium (the weapon and the body armour at +5)' ;;
    2) kit_label='easy (the whole level-1 set at +9)' ;;
    *) kit_label='none' ;;
esac
if db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES (0, 'm2_starter_kit', '', $starter_kit);"; then
    echo "[playerbot-migrate] starter kit: $kit_label, for new characters and the bots made from now on"
else
    echo "[playerbot-migrate] WARNING: could not write the starter kit flag; the cores keep the last one" >&2
fi

# The Cor Draconis a day at the Alchemist (Kuszaa and the operator, 1 October):
# the Power of the Dragon Eye a new day's talk gives, and one fewer on the day
# of the first hand-in, whose own box is the first. .env's M2_DS_EYES_PER_DAY,
# 1 to 100 - anything else is the package's 10, the way questlib reads
# ds_drop - is the event flag m2_ds_eyes_per_day, which dragon_soul.quest asks
# through m2_difficulty.lua and the bots' talks read the same way
# (playerbot_dragon_soul_rules.h). Written only when .env changed since the
# last start (m2_ds_eyes_per_day_env), so the classic panel's choice outlives a
# restart until the launcher's is changed, the difficulty's rule.
ds_eyes_in=$(printf '%s' "${M2_DS_EYES_PER_DAY:-10}" | tr -d ' \r')
ds_eyes=$(printf '%s\n' "$ds_eyes_in" | awk '/^[0-9]+$/ { n = $1 + 0; if (n >= 1 && n <= 100) { printf "%d", n; exit } } { printf "x"; exit }')
if [ "$ds_eyes" = x ]; then
    echo "[playerbot-migrate] WARNING: M2_DS_EYES_PER_DAY=$ds_eyes_in is not a number from 1 to 100; the Alchemist gives the package's 10 a day" >&2
    ds_eyes=10
fi
ds_eyes_env=$(db -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_ds_eyes_per_day_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
if [ "$ds_eyes_env" = "$ds_eyes" ]; then
    echo "[playerbot-migrate] Cor Draconis a day: .env unchanged since the last start - the flag stays as the panel or the last start left it"
elif db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
        (0, 'm2_ds_eyes_per_day', '', $ds_eyes),
        (0, 'm2_ds_eyes_per_day_env', '', $ds_eyes);"; then
    echo "[playerbot-migrate] Cor Draconis a day at the Alchemist: $ds_eyes (from .env)"
else
    echo "[playerbot-migrate] WARNING: could not write the Cor Draconis a day; the quest keeps the last count" >&2
fi

# The Alchemist's Time Elixirs (Kiciamol, 7 October): dragon_soul_shop.quest's
# "Eliksiry Czasu" opens the special shop 20001, which sells the small, the
# medium and the large (100000-100002) for three, five and eight raw Cor
# Draconis (50255) and no yang - nothing else in this world sells or drops
# one. The db core reads world.shop_special and shop_special_proto at boot,
# so they are live at the next start. 20001 and 20101-20103 are free in the
# package's dump; a row the operator changed or made under those numbers is
# kept (INSERT IGNORE), and the shop lists only the rows that sell an
# elixir. The small one's row charged nothing (value0 0, "Cannot charge"):
# it charges a quarter of a stone's wear now, the medium half as the package
# has it, and the large - the package's fixed 30000 seconds, less than the
# medium's half of a day's wear - the whole of it (Kiciamol, 7 October: "Niech
# (D) daje 100% S 50 a M 25"): USE_TIME_CHARGE_FIX becomes
# USE_TIME_CHARGE_PER at 100. Only the package's values move, and the
# client's table says the same (port/protoify.py). Idempotent.
db_retry -e "INSERT IGNORE INTO world.shop_special_proto
        (vnum, item_vnum, count, rare_pct, price_type, price, items, random_item_count, random_item_group,
         limittype0, limitvalue0, limittype1, limitvalue1) VALUES
        (20101, 100000, 1, 0, 'GOLD', 0, '50255,3', 0, 0, 'NONE', 0, 'NONE', 0),
        (20102, 100001, 1, 0, 'GOLD', 0, '50255,5', 0, 0, 'NONE', 0, 'NONE', 0),
        (20103, 100002, 1, 0, 'GOLD', 0, '50255,8', 0, 0, 'NONE', 0, 'NONE', 0);
    INSERT IGNORE INTO world.shop_special (vnum, item_vnum)
        SELECT 20001, vnum FROM world.shop_special_proto
         WHERE vnum IN (20101, 20102, 20103) AND item_vnum IN (100000, 100001, 100002);
    UPDATE world.item_proto SET value0 = 25 WHERE vnum = 100000 AND type = 3 AND subtype = 27 AND value0 = 0;
    UPDATE world.item_proto SET subtype = 27, value0 = 100 WHERE vnum = 100002 AND type = 3 AND subtype = 28 AND value0 = 30000;" \
    || echo "[playerbot-migrate] WARNING: could not give the Alchemist his Time Elixirs" >&2

# Every grade of Dragon Stone wears a day (Kiciamol, 7 October). The package
# gives a rough stone 24 hours of wear and a cut, rare, antique and legendary
# one 12, 8, 6 and 4 (limit 0, LIMIT_TIMER_BASED_ON_WEAR), and an elixir
# charges a stone only up to its own (CItem::GiveMoreTime_Per/_Fix ask
# GetDuration), so a legendary stone held four hours at most. A stone made
# from now on and a stone charged take the day; one already made keeps the
# time it has until it is charged. Only the package's hours move, by the
# grade in the vnum's thousands; an operator's own value stays. PROTO_FROM_DB:
# the db core reads the rows at boot. Idempotent.
db_retry -e "UPDATE world.item_proto SET limitvalue0 = 86400
     WHERE type = 29 AND limittype0 = 9 AND (
           (vnum % 10000 BETWEEN 1000 AND 1999 AND limitvalue0 = 43200)
        OR (vnum % 10000 BETWEEN 2000 AND 2999 AND limitvalue0 = 28800)
        OR (vnum % 10000 BETWEEN 3000 AND 3999 AND limitvalue0 = 21600)
        OR (vnum % 10000 BETWEEN 4000 AND 4999 AND limitvalue0 = 14400));" \
    || echo "[playerbot-migrate] WARNING: could not give the Dragon Stones a day of wear" >&2

# Extra drops of the Metin stones and the bosses (Jeremus-Sama, 1 October:
# "quantity and quality depends on metin level and boss difficulty"): .env's
# M2_EXTRA_DS_DROP and M2_EXTRA_COUPON_DROP, the percent a person's kill of a
# stone or a boss rolls at for the Dragon Stone Alchemy's material (shards
# from a stone, a Cor Draconis from a boss) and for a Kupon SM by the victim's
# level and rank - 0, the default, is off; what drops and for whom is
# m2_difficulty.lua's, rolled by world_drops.quest. The event flags
# m2_extra_ds_drop and m2_extra_coupon_drop are written only when .env changed
# since the last start (their _env rows), so the classic panel's choice
# outlives a restart until the launcher's is changed. The world's own Kupon SM
# roll from every stone and boss (M2_DRAGON_COIN_*_PERMILLE, CONFIG) is apart
# from these and stays as it is.
drop_percent() {
    printf '%s\n' "$1" | tr -d ' \r%' | awk 'NR == 1 { p = int($1 + 0); if (p < 0) p = 0; if (p > 100) p = 100; printf "%d", p }'
}
for drop_kind in ds coupon; do
    case "$drop_kind" in
        ds) drop_value=$(drop_percent "${M2_EXTRA_DS_DROP:-0}") ;;
        *)  drop_value=$(drop_percent "${M2_EXTRA_COUPON_DROP:-0}") ;;
    esac
    drop_env=$(db -e "SELECT lValue FROM player.quest WHERE dwPID = 0 AND szName = 'm2_extra_${drop_kind}_drop_env' LIMIT 1;" 2>/dev/null | tr -d ' \r')
    if [ "$drop_env" = "$drop_value" ]; then
        echo "[playerbot-migrate] extra $drop_kind drop: .env unchanged since the last start - the flag stays as the panel or the last start left it"
    elif db_retry -e "REPLACE INTO player.quest (dwPID, szName, szState, lValue) VALUES
            (0, 'm2_extra_${drop_kind}_drop', '', $drop_value),
            (0, 'm2_extra_${drop_kind}_drop_env', '', $drop_value);"; then
        echo "[playerbot-migrate] extra $drop_kind drop of Metin stones and bosses: ${drop_value}% a person's kill (from .env)"
    else
        echo "[playerbot-migrate] WARNING: could not write the extra $drop_kind drop flag; the quest keeps the last one" >&2
    fi
done

# The miscellaneous merchant sells more (Jeremus-Sama, 1 October: "NPC QoL
# settings - general shop sells green/purple potions ... for people who just
# want casual gameplay"): .env's M2_CASUAL_SHOP, 0 by default. On, the
# merchant of every village (9003; the shop whose npc_vnum she is, 3 in the
# package) also sells the green and the purple potion of each size, one and
# twenty at a time, at their item_proto price (1 000, 2 000 and 3 000 yang a
# potion). Off, exactly those 12 lines come out again and nothing else of her
# shop is touched. The db core reads the shops at boot, so a change is live at
# the next start, and it fills a shop's 40 places with no bound of its own
# (InitializeShopTable writes past the array), so the lines go in only while
# her shop keeps to the 40 places of its 5 x 8 grid. The bots buy their
# potions by vnum and never read her shop (ManagePlayerBotMiscMerchant).
casual_shop=0
case "$(printf '%s' "${M2_CASUAL_SHOP:-0}" | tr 'A-Z' 'a-z' | tr -d ' \r')" in
    1|on|yes|true) casual_shop=1 ;;
esac
casual_vnum=$(db -e "SELECT vnum FROM world.shop WHERE npc_vnum = 9003 ORDER BY vnum LIMIT 1;" 2>/dev/null | tr -d ' \r')
case "$casual_vnum" in
    ''|*[!0-9]*)
        echo "[playerbot-migrate] WARNING: the miscellaneous merchant (9003) has no shop; the casual shop is left out" >&2 ;;
    *)
        if [ "$casual_shop" = 1 ]; then
            casual_cells=$(db -e "SELECT COALESCE(SUM(GREATEST(1, COALESCE(p.size, 1))), 0)
                  FROM world.shop_item AS s LEFT JOIN world.item_proto AS p ON p.vnum = s.item_vnum
                 WHERE s.shop_vnum = $casual_vnum AND (s.item_vnum, s.count) NOT IN ((27100, 1), (27100, 20), (27101, 1), (27101, 20), (27102, 1), (27102, 20), (27103, 1), (27103, 20), (27104, 1), (27104, 20), (27105, 1), (27105, 20));" 2>/dev/null | tr -d ' \r')
            case "$casual_cells" in ''|*[!0-9]*) casual_cells=999 ;; esac
            if [ "$casual_cells" -gt $((40 - 12)) ]; then
                echo "[playerbot-migrate] WARNING: the miscellaneous merchant's shop has $casual_cells of its 40 places taken by other lines; the casual shop's 12 are left out" >&2
            elif db_retry -e "INSERT IGNORE INTO world.shop_item (shop_vnum, item_vnum, count)
                        SELECT $casual_vnum, n.v, n.c FROM (SELECT 27100 AS v, 1 AS c UNION ALL SELECT 27100, 20 UNION ALL SELECT 27101, 1 UNION ALL SELECT 27101, 20 UNION ALL SELECT 27102, 1 UNION ALL SELECT 27102, 20 UNION ALL SELECT 27103, 1 UNION ALL SELECT 27103, 20 UNION ALL SELECT 27104, 1 UNION ALL SELECT 27104, 20 UNION ALL SELECT 27105, 1 UNION ALL SELECT 27105, 20) AS n;"; then
                echo "[playerbot-migrate] casual shop: the miscellaneous merchant sells the green and purple potions"
            else
                echo "[playerbot-migrate] WARNING: could not add the casual shop's lines" >&2
            fi
        elif casual_gone=$(db_retry -e "DELETE FROM world.shop_item WHERE shop_vnum = $casual_vnum AND (item_vnum, count) IN ((27100, 1), (27100, 20), (27101, 1), (27101, 20), (27102, 1), (27102, 20), (27103, 1), (27103, 20), (27104, 1), (27104, 20), (27105, 1), (27105, 20));
                SELECT ROW_COUNT();"); then
            casual_gone=$(printf '%s' "$casual_gone" | tr -d '[:space:]')
            if [ -n "$casual_gone" ] && [ "$casual_gone" != 0 ]; then
                echo "[playerbot-migrate] casual shop off: $casual_gone line(s) taken out of the miscellaneous merchant's shop"
            fi
        else
            echo "[playerbot-migrate] WARNING: could not take the casual shop's lines out" >&2
        fi ;;
esac

# The ItemShop's prices as a percent (Jeremus-Sama, 1 October: "ItemShop -
# control over prices"): .env's M2_ITEMSHOP_PRICE_PCT, 10 to 1000, 100 by
# default - the catalogue as it is. The in-game ItemShop prices its lines by
# common.itemshop_items.price, which the db core reads at boot, so a change is
# live at the next start. The price each line had before any percent is kept
# beside it (common.m2_itemshop_price_base) and every line is that times the
# percent - Dragon Coins and Dragon Marks alike, never under 1, a free line
# free. A line somebody priced by hand since (neither what this step wrote nor
# its base) is that person's from then on and never touched again (own = 1;
# deleting its row there gives it back), a new line's price is its base, a line
# taken out is forgotten, and a promotion (common.itemshop_promotions) keeps the
# price it was given. 100 puts every line back. The bots read the prices the
# catalogue shows, as a player does.
itemshop_pct=$(printf '%s' "${M2_ITEMSHOP_PRICE_PCT:-100}" | tr -d ' \r%')
case "$itemshop_pct" in
    ''|*[!0-9]*)
        echo "[playerbot-migrate] WARNING: M2_ITEMSHOP_PRICE_PCT=$itemshop_pct is not a percent; the ItemShop keeps its own prices" >&2
        itemshop_pct=100 ;;
    *) itemshop_pct=$(printf '%s\n' "$itemshop_pct" | awk '{ p = int($1 + 0); if (p < 10) p = 10; if (p > 1000) p = 1000; printf "%d", p }') ;;
esac
if itemshop_out=$(db_retry -e "
        CREATE TABLE IF NOT EXISTS common.m2_itemshop_price_base (
            \`index\` INT NOT NULL PRIMARY KEY,
            base INT NOT NULL,
            applied INT NOT NULL,
            own TINYINT NOT NULL DEFAULT 0) ENGINE=InnoDB;
        START TRANSACTION;
        UPDATE common.m2_itemshop_price_base AS b JOIN common.itemshop_items AS i ON i.\`index\` = b.\`index\`
           SET b.own = 1
         WHERE b.own = 0 AND i.price <> b.applied AND i.price <> b.base;
        DELETE FROM common.m2_itemshop_price_base
         WHERE \`index\` NOT IN (SELECT \`index\` FROM common.itemshop_items);
        INSERT IGNORE INTO common.m2_itemshop_price_base (\`index\`, base, applied)
        SELECT \`index\`, price, price FROM common.itemshop_items;
        UPDATE common.itemshop_items AS i JOIN common.m2_itemshop_price_base AS b ON b.\`index\` = i.\`index\`
           SET i.price = IF(b.base <= 0, b.base, GREATEST(1, ROUND(b.base * $itemshop_pct / 100))),
               b.applied = IF(b.base <= 0, b.base, GREATEST(1, ROUND(b.base * $itemshop_pct / 100)))
         WHERE b.own = 0;
        SELECT COUNT(*), COALESCE(SUM(own), 0) FROM common.m2_itemshop_price_base;
        COMMIT;"); then
    itemshop_lines=$(printf '%s\n' "$itemshop_out" | awk 'NF { print $1; exit }')
    itemshop_own=$(printf '%s\n' "$itemshop_out" | awk 'NF { print $2; exit }')
    echo "[playerbot-migrate] ItemShop prices: ${itemshop_pct}% of the catalogue's (${itemshop_lines:-0} line(s), ${itemshop_own:-0} priced by hand and left alone)"
else
    echo "[playerbot-migrate] WARNING: could not set the ItemShop's prices; they stay as the last start left them" >&2
fi

echo "[playerbot-migrate] applying deterministic Playerbot seed (PID $first_pid..$last_pid)"
result=/tmp/playerbot-seed.out
trap 'rm -f "$result"' EXIT HUP INT TERM
# Shinsoo and Jinno are opt-in: M2_PLAYERBOT_KINGDOMS=1 lets the seed create
# their cohorts, anything else keeps the file to the Chunjo cohort it has
# always been. The variable goes in ahead of the file, in the same session,
# because a SET is per-connection.
kingdoms=0
case "${M2_PLAYERBOT_KINGDOMS:-0}" in
    1|true|TRUE|yes|YES) kingdoms=1 ;;
esac
echo "[playerbot-migrate] kingdoms (Shinsoo/Jinno) cohorts: $kingdoms"
# The fresh cohort of game channels 3 and 4 (playerbot_channel_rules.h):
# its identities are created only while those channels are on - .env's
# M2_PLAYERBOT_FRESH_CHANNELS, or the web panel's wish (channels.wanted,
# FRESH= and SET_AT=) when that is newer, as the game container decides it.
fresh_channels="${M2_PLAYERBOT_FRESH_CHANNELS:-0}"
fresh_env_at="${M2_PLAYERBOT_CH2_SET_AT:-0}"
case "$fresh_env_at" in ''|*[!0-9]*) fresh_env_at=0 ;; esac
if [ -f /opt/m2spool/channels.wanted ]; then
    wish_on=$(sed -n 's/^CH2=\([01]\)\r\{0,1\}$/\1/p' /opt/m2spool/channels.wanted | head -n 1)
    wish_fresh=$(sed -n 's/^FRESH=\([0-9]\)\r\{0,1\}$/\1/p' /opt/m2spool/channels.wanted | head -n 1)
    wish_at=$(sed -n 's/^SET_AT=\([0-9]\{1,12\}\)\r\{0,1\}$/\1/p' /opt/m2spool/channels.wanted | head -n 1)
    if [ -n "$wish_on" ] && [ -n "$wish_fresh" ] && [ -n "$wish_at" ] && [ "$wish_at" -gt "$fresh_env_at" ]; then
        fresh_channels="$wish_fresh"
    fi
fi
# The first channel alone (M2_ONLY_CH1) makes no fresh cohort either.
if [ "${M2_ONLY_CH1:-0}" = 1 ]; then
    fresh_channels=0
fi
fresh=0
case "$fresh_channels" in
    1|2) fresh=1 ;;
esac
fresh_range=$(grep -o 'the fresh cohort is not exactly PID [0-9]*\.\.[0-9]*' "$seed" | head -1 | sed 's/.*PID //')
fresh_first=${fresh_range%%..*}
fresh_last=${fresh_range##*..}
case "${fresh_first:-}${fresh_last:-}" in
    ''|*[!0-9]*) fresh=0 ;;
esac
echo "[playerbot-migrate] fresh cohort (channels 3-4): $fresh"
# And whether a bot the seed makes now starts with its apprentice chest: the
# world's switch as the step above left it (off gives none); and in which
# starter kit (STARTER_KIT above: 0 none, 1 medium, 2 easy). The companion
# pool always: the companion is this line's, and its identities are
# nobody's but a companion's (playerbot_channel_rules.h).
if { printf 'SET @playerbot_seed_kingdoms = %s;
SET @playerbot_seed_fresh = %s;
SET @playerbot_seed_starter_chest = %s;
SET @playerbot_seed_starter_kit = %s;
SET @playerbot_seed_sidekicks = 1;
' "$kingdoms" "$fresh" "$((1 - ${starter_off:-0}))" "${starter_kit:-0}"; cat "$seed"; } |
        db_retry --show-warnings >"$result" 2>&1; then
    [ ! -s "$result" ] || cat "$result"
else
    rc=$?
    cat "$result" >&2
    if grep -Fq 'playerbot seed conflict:' "$result"; then
        if [ "$strict" = "1" ]; then
            echo "[playerbot-migrate] FATAL: canonical cohort conflict (strict mode)" >&2
            exit "$rc"
        fi
        echo "[playerbot-migrate] WARNING: existing non-canonical Playerbot cohort detected" >&2
        echo "[playerbot-migrate] WARNING: preserving it unchanged; canonical seed skipped" >&2
        echo "[playerbot-migrate] WARNING: set PLAYERBOT_SEED_STRICT=1 to make this fatal" >&2
        exit 0
    fi
    echo "[playerbot-migrate] FATAL: seed failed for a non-conflict reason" >&2
    exit "$rc"
fi

count=$(db -e "
    SELECT COUNT(*)
      FROM player.player
     WHERE id BETWEEN $first_pid AND $last_pid;
")
if [ -z "$count" ] || [ "$count" -eq 0 ] 2>/dev/null; then
    echo "[playerbot-migrate] FATAL: post-check found no bot characters at all" >&2
    exit 1
fi
added=$((count - before))
if [ "$added" -gt 0 ]; then
    echo "[playerbot-migrate] created $added new bot character(s)"
fi
echo "[playerbot-migrate] seed complete: $count bot character(s) in PID $first_pid..$last_pid"
if [ "$fresh" = 1 ]; then
    fresh_count=$(db -e "
        SELECT COUNT(*)
          FROM common.playerbot_seed_state
         WHERE pid BETWEEN $fresh_first AND $fresh_last AND state IN ('complete', 'adopted');
" 2>/dev/null || echo "?")
    echo "[playerbot-migrate] fresh cohort: $fresh_count identities in PID $fresh_first..$fresh_last (channels 3-4)"
fi
# The companion pool (playerbot_channel_rules.h): how many identities the
# seed holds and how many no companion has used. The table a core claims one
# in is the core's too (EnsurePlayerBotSidekickTable); made here as well, so
# the count reads before any core has started.
pool_range=$(grep -o 'the companion pool is not exactly PID [0-9]*\.\.[0-9]*' "$seed" | head -1 | sed 's/.*PID //')
pool_first=${pool_range%%..*}
pool_last=${pool_range##*..}
case "${pool_first:-}${pool_last:-}" in
    ''|*[!0-9]*)
        echo "[playerbot-migrate] WARNING: cannot read the companion pool's range from $seed" >&2
        ;;
    *)
        db_retry -e "CREATE TABLE IF NOT EXISTS player.playerbot_sidekick_used (sidekick_pid INT UNSIGNED NOT NULL PRIMARY KEY, owner_pid INT UNSIGNED NOT NULL, used_at DATETIME NOT NULL) ENGINE=InnoDB;" 2>/dev/null \
            || echo "[playerbot-migrate] WARNING: could not make player.playerbot_sidekick_used" >&2
        pool_count=$(db -e "
            SELECT COUNT(*)
              FROM common.playerbot_seed_state
             WHERE pid BETWEEN $pool_first AND $pool_last AND state IN ('complete', 'adopted');
        " 2>/dev/null || echo "?")
        pool_free=$(db -e "
            SELECT COUNT(*)
              FROM common.playerbot_seed_state AS l
              JOIN player.player AS p ON p.id = l.pid
             WHERE l.pid BETWEEN $pool_first AND $pool_last AND l.state IN ('complete', 'adopted')
               AND p.playtime = 0
               AND l.pid NOT IN (SELECT sidekick_pid FROM player.playerbot_sidekick_used);
        " 2>/dev/null || echo "?")
        echo "[playerbot-migrate] companion pool: $pool_count identities in PID $pool_first..$pool_last, $pool_free never used"
        ;;
esac

# ---------------------------------------------------------------------------
# Human nicknames.
#
# "Pozdrawiam pana botarek7 jest kotem ale brzmi jak bot" - a world of botX7
# reads as a world of bots however well they behave. The pool and the rules are
# in playerbot_names.sql; this only chooses which of its three modes to run and
# reports what it did.
#
# It runs after the seed on purpose: a bot created a minute ago is renamed on
# the same start, and a bot the seed decided to preserve is left with whatever
# name it has, because the SQL only touches characters still called bot*.
#
# A failure here is not fatal. Names are the one part of a bot's identity
# nothing depends on - the core matches on the account login - so a server that
# could not rename its bots is a server that works with the old names.
# ---------------------------------------------------------------------------
names=/opt/playerbot/playerbot_names.sql
if [ -s "$names" ]; then
    human=1
    case "${M2_PLAYERBOT_HUMAN_NAMES:-1}" in
        0|false|FALSE|no|NO) human=0 ;;
        restore|RESTORE) human=restore ;;
    esac
    echo "[playerbot-migrate] human nicknames: $human"
    names_out=/tmp/playerbot-names.out
    if { printf 'SET @playerbot_human_names = %s;
' "'$human'"; cat "$names"; } |
            db_retry --show-warnings >"$names_out" 2>&1; then
        [ ! -s "$names_out" ] || cat "$names_out"
    else
        cat "$names_out" >&2
        echo "[playerbot-migrate] WARNING: nicknames not applied; bots keep their seed names" >&2
    fi
    rm -f "$names_out"
else
    echo "[playerbot-migrate] no playerbot_names.sql; bots keep their seed names"
fi

# The tester account's own game masters, mt2009 only (see the file).
if [ -s /opt/playerbot/gm_characters.sql ]; then
    if gm_out=$(db_retry < /opt/playerbot/gm_characters.sql 2>&1); then
        echo "[playerbot-migrate] $gm_out"
    else
        echo "[playerbot-migrate] WARNING: gm_characters.sql failed:" >&2
        echo "$gm_out" | head -3 >&2
    fi
fi

# ---------------------------------------------------------------------------
# A game master for the tester account.
#
# GM rights are one row in common.gmlist naming an account AND a character,
# and the mt2009 package ships neither a row nor a character on `admin' - so
# a world initialised before initdb created one (2.0.0, 2.0.1) has an admin
# who can log in and command nothing, and the first report was exactly that:
# "loguje sie admin admin, a tam nie ma postaci gm". The character the player
# made in the meantime is the one they want the rights on, so this grants
# IMPLEMENTOR to the tester account's oldest character, once, and only while
# the list is empty: a world that has ever named a GM is left as it is, and a
# world whose tester account was removed (M2_KEEP_DEMO_ACCOUNTS=0) has nothing
# to grant to. A world that has no character on the account yet gets the row
# on the first start after one is created. The db core reads the list at
# boot, and this runs before the game container starts.
# ---------------------------------------------------------------------------
gm_rows=$(db -e "SELECT COUNT(*) FROM common.gmlist;" 2>/dev/null || echo x)
if [ "$gm_rows" = "0" ]; then
    gm_name=$(db -e "
        SELECT p.name
          FROM player.player AS p
          JOIN account.account AS a ON a.id = p.account_id
         WHERE a.login = 'admin'
         ORDER BY p.id
         LIMIT 1;
    " 2>/dev/null || true)
    if [ -n "$gm_name" ]; then
        if db_retry -e "
            INSERT INTO common.gmlist (mAccount, mName, mContactIP, mServerIP, mAuthority)
            VALUES ('admin', '$gm_name', '', 'ALL', 'IMPLEMENTOR');
        "; then
            echo "[playerbot-migrate] gmlist was empty: '$gm_name' on the admin account is IMPLEMENTOR now"
        else
            echo "[playerbot-migrate] WARNING: could not grant GM rights to '$gm_name'" >&2
        fi
    else
        echo "[playerbot-migrate] gmlist is empty and the admin account has no character yet; the first one it gets becomes GM on the next start"
    fi
fi
