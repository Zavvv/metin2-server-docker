"""Persist offline PERSONASET jobs; native cores own online session transitions.

Queue PK is the job identity. Claim/profile/ack share one transaction, so a
reconnect cannot repeat history or leave an acknowledged but missing preference.
No game cache, equipment or quest rows are written by this worker.
"""


def tick(con, engine_mt2009=True):
    if not engine_mt2009:
        return
    with con.cursor() as cur:
        cur.execute("SELECT value FROM player.web_m2p_contract_state WHERE name='persona_contract'")
        if int((cur.fetchone() or {}).get('value') or 0) != 18:
            return
        con.begin()
        try:
            # Repair a lost native acknowledgement from the absolute durable
            # profile; never invoke the transition a second time.
            cur.execute("UPDATE player.web_admin_queue q JOIN player.web_m2p_persona_profile p "
                        "ON p.pid=q.player_id AND p.queue_id=q.id SET q.status='done' "
                        "WHERE q.cmd='PERSONASET' AND q.status LIKE 'w%%'")
            # Do not expire an open session from a stale snapshot. A disconnected
            # core closes its sessions at boot; otherwise its consumer owns jobs.
            cur.execute("""SELECT q.id,q.player_id,q.player_name,q.arg1,p.name,
              (LEFT(a.login,10)='playerbot_' OR p.name LIKE 'bot%%') AS is_bot,
              EXISTS(SELECT 1 FROM player.playerbot_sidekick sk WHERE sk.sidekick_pid=p.id) AS sidekick
              FROM player.web_admin_queue q
              LEFT JOIN player.player p ON p.id=q.player_id
              LEFT JOIN account.account a ON a.id=p.account_id
              WHERE q.cmd='PERSONASET' AND q.status='await'
                AND q.created<NOW()-INTERVAL 10 SECOND
                AND NOT EXISTS(SELECT 1 FROM log.playerbot_session s WHERE s.pid=q.player_id AND s.logout_at IS NULL)
              ORDER BY q.id LIMIT 8 FOR UPDATE""")
            jobs=cur.fetchall()
            cur.execute("SELECT id FROM player.web_m2p_persona_catalog WHERE contract_version=18")
            catalog={int(r['id']) for r in cur.fetchall()}
            for job in jobs:
                status='done'
                value=None
                raw=job['arg1'] or ''
                if not job['player_id'] or not job['name'] or job['name'] != job['player_name']:
                    status='gone'
                elif not job['is_bot'] or job['sidekick']:
                    status='not_allowed'
                elif raw != 'AUTO':
                    if not raw.isascii() or not raw.isdecimal() or int(raw) not in catalog:
                        status='bad_args'
                    else:
                        value=int(raw)
                if status=='done':
                    cur.execute("""INSERT INTO player.web_m2p_persona_profile(pid,persona_id,queue_id,updated_at)
                      VALUES(%s,%s,%s,NOW()) ON DUPLICATE KEY UPDATE
                      persona_id=IF(queue_id<VALUES(queue_id),VALUES(persona_id),persona_id),
                      applied_queue=IF(queue_id<VALUES(queue_id),0,applied_queue),
                      queue_id=GREATEST(queue_id,VALUES(queue_id)),updated_at=NOW()""",
                      (job['player_id'],value,job['id']))
                cur.execute("UPDATE player.web_admin_queue SET status=%s WHERE id=%s AND status='await'",
                            (status,job['id']))
            con.commit()
        except Exception:
            con.rollback()
            raise
