-- Iwakura x Tyrion Patch 19 shared contracts. Run by apply.sh after the
-- Patch 18 ones, on every start; idempotent, older rows kept.
USE player;

-- Point 8, Fun: a world command of the panel (web_admin_queue, player_name='')
-- the first core with bots accepted. Instant commands run once on every core
-- that hosts bots within ten minutes of starts_at; a timed one is in force
-- until ends_at on every core, one that boots in the middle of it included,
-- and its end needs nothing but the clock (NULL: until a newer command of the
-- same kind). web_m2p_fun_run is which core ran an instant command, claimed
-- before it runs: a restart never runs it twice on one core.
CREATE TABLE IF NOT EXISTS web_m2p_fun_event (
 queue_id INT UNSIGNED PRIMARY KEY, cmd VARCHAR(16) NOT NULL,
 arg1 VARCHAR(64) NOT NULL DEFAULT '', arg2 VARCHAR(64) NOT NULL DEFAULT '',
 starts_at DATETIME NOT NULL, ends_at DATETIME NULL,
 KEY active (ends_at), KEY kind (cmd, queue_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS web_m2p_fun_run (
 queue_id INT UNSIGNED NOT NULL, core VARCHAR(32) NOT NULL,
 ran_at DATETIME NOT NULL, bots INT UNSIGNED NOT NULL DEFAULT 0,
 PRIMARY KEY (queue_id, core)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Point 11: which world this database is. initdb (10-import-dumps.sh) writes
-- the row with fresh=1 into a database it has just made; a world from before
-- Patch 19 is adopted here with fresh=0. The migrator resets the GM list once
-- for a fresh one (reset_done), and the spool's world-id is what the game
-- container compares its own state files against.
CREATE TABLE IF NOT EXISTS web_m2p_world (
 singleton TINYINT PRIMARY KEY, world_id CHAR(32) NOT NULL,
 created_at DATETIME NOT NULL, fresh TINYINT NOT NULL DEFAULT 0,
 reset_done DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO web_m2p_world (singleton, world_id, created_at, fresh)
 VALUES (1, REPLACE(UUID(), '-', ''), NOW(), 0);
