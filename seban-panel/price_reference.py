"""Publish one hourly median from complete native valuations, never from cash."""

# Patch 19, 2B (playerbot_patch19_rules.h's CohortLevel): twenty bots of 40+,
# else twenty of 30+, else no cohort at all.
COHORT_MIN = 20
COHORT_HIGH_LEVEL = 40
COHORT_LOW_LEVEL = 30


def cohort_level(from40, from30):
    if from40 >= COHORT_MIN:
        return COHORT_HIGH_LEVEL
    if from30 >= COHORT_MIN:
        return COHORT_LOW_LEVEL
    return 0


def tick(con, engine_mt2009=True):
    if not engine_mt2009:
        return
    with con.cursor() as cur:
        cur.execute("SELECT value FROM player.web_m2p_contract_state WHERE name='prices_patch18'")
        if int((cur.fetchone() or {}).get('value') or 0) != 18:
            return
        con.begin()
        try:
            cur.execute("SELECT UNIX_TIMESTAMP(updated_at) AS at,UNIX_TIMESTAMP(NOW()) AS now "
                        "FROM player.web_m2p_price_reference WHERE singleton=1 FOR UPDATE")
            clock = cur.fetchone()
            if not clock:
                con.rollback()
                return
            if 0 <= int(clock['now']) - int(clock['at']) < 3600:
                con.commit()
                return
            cur.execute("SELECT MIN(started) AS started FROM ("
                        "SELECT UNIX_TIMESTAMP(MIN(create_time)) AS started FROM account.account WHERE create_time>'1971-01-01' "
                        "UNION ALL SELECT UNIX_TIMESTAMP(MIN(time)) FROM log.loginlog WHERE time>'1971-01-01') ages")
            started = int((cur.fetchone() or {}).get('started') or 0)
            cur.execute("SELECT reference_version FROM player.web_m2p_valuation "
                        "WHERE valued_at>=NOW()-INTERVAL 1 HOUR ORDER BY valued_at DESC,pid DESC LIMIT 1")
            version = int((cur.fetchone() or {}).get('reference_version') or 0)
            # Patch 19, 2B: the bots of 40 and up when there are twenty, else of
            # 30 and up when there are twenty, else no cohort (the world cap off).
            cur.execute("""SELECT v.reference_wealth AS wealth,v.level AS level FROM player.web_m2p_valuation v
              WHERE v.complete=1 AND v.level>=%s AND v.reference_version=%s
                AND v.valued_at BETWEEN NOW()-INTERVAL 1 HOUR AND NOW()
                AND v.cash_at BETWEEN v.valued_at-INTERVAL 120 SECOND AND v.valued_at
                AND EXISTS(SELECT 1 FROM log.playerbot_session s WHERE s.pid=v.pid
                  AND s.login_at<=NOW()
                  AND GREATEST(COALESCE(s.logout_at,s.seen_at,s.login_at),s.login_at)>=NOW()-INTERVAL 24 HOUR)
              ORDER BY v.reference_wealth,v.pid LIMIT 10001""", (COHORT_LOW_LEVEL, version))
            rows = cur.fetchall()
            valid = len(rows) <= 10000 and all(0 < int(row['wealth']) <= 9000000000000000 for row in rows)
            level = cohort_level(sum(1 for row in rows if int(row['level']) >= COHORT_HIGH_LEVEL), len(rows))
            values = [int(row['wealth']) for row in rows if level and int(row['level']) >= level]
            median = (values[(len(values)-1)//2]+values[len(values)//2])//2 if valid and values else 0
            reason = 'price_missing_cohort' if not median else ('price_missing_world_age' if not started else
                                                                 'ready' if level == COHORT_HIGH_LEVEL else 'ready_30')
            cur.execute("UPDATE player.web_m2p_price_reference SET median=%s,cohort=%s,reference_version=%s,"
                        "world_started=%s,reason=%s,updated_at=NOW() WHERE singleton=1",
                        (median, len(values) if valid else 0, version, started, reason))
            con.commit()
        except Exception:
            con.rollback()
            raise
