"""Patch 18 population target; saving never recreates a game container."""
def read(db, online=None):
    result = {"available": False, "desired": None, "pool": None,
              "online": online, "pending_restart": None, "source": None,
              "applied": [], "includes_extra_cohorts": False}
    with db() as con, con.cursor() as cur:
        cur.execute("SELECT desired,source,updated_at FROM player.web_m2p_population WHERE singleton=1")
        row = cur.fetchone()
        if not row:
            return result
        result.update(available=True, desired=int(row["desired"]), source=row["source"],
                      updated_at=str(row["updated_at"]))
        cur.execute("SELECT COUNT(DISTINCT s.pid) AS n FROM common.playerbot_seed_state s "
                    "JOIN player.player p ON p.id=s.pid WHERE s.seed_version=1 AND s.state IN ('complete','adopted')")
        result["pool"] = int(cur.fetchone()["n"])
        cur.execute("SELECT channel,port,applied,boot_at FROM player.web_m2p_population_runtime "
                    "WHERE seen_at>=NOW()-INTERVAL 120 SECOND ORDER BY channel,port")
        result["applied"] = [{**r, "boot_at": str(r["boot_at"])} for r in cur.fetchall()]
        result["pending_restart"] = (not result["applied"] or any(
            int(r["applied"]) != result["desired"] for r in result["applied"]))
    return result


def save(db, desired):
    if isinstance(desired, bool) or not isinstance(desired, int) or not 0 <= desired <= 2500:
        raise ValueError("population target must be an integer from 0 to 2500")
    with db() as con, con.cursor() as cur:
        # A missing row means an old/uninitialised engine, not permission to
        # seed it from a panel's guessed environment or the online count.
        cur.execute("UPDATE player.web_m2p_population SET desired=%s,source='panel',updated_at=NOW() "
                    "WHERE singleton=1", (desired,))
        cur.execute("SELECT desired FROM player.web_m2p_population WHERE singleton=1")
        row = cur.fetchone()
        if not row or int(row["desired"]) != desired:
            raise RuntimeError("the running engine has not initialised the population contract")
    return desired
