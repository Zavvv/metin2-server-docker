-- Patch 18 shared contracts. Run before cores/panels; preserve older rows.
USE player;
-- utf8mb4, never the player database's default: on mt2009 that is cp1250, and
-- the cores join player_name to the latin1 player.name (errno 1267, Said,
-- 21 October). apply.sh converts a queue an older start made in cp1250.
CREATE TABLE IF NOT EXISTS web_admin_queue (
 id INT AUTO_INCREMENT PRIMARY KEY, player_name VARCHAR(24) NOT NULL,
 cmd VARCHAR(16) NOT NULL,arg1 VARCHAR(64),arg2 VARCHAR(64),
 status VARCHAR(24) DEFAULT 'pending',created DATETIME DEFAULT CURRENT_TIMESTAMP,
 KEY status_idx(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE web_admin_queue ADD COLUMN IF NOT EXISTS player_id INT UNSIGNED NULL;
ALTER TABLE web_admin_queue ADD INDEX IF NOT EXISTS persona_pid (cmd,player_id,status);
CREATE TABLE IF NOT EXISTS web_m2p_persona_catalog (
 id SMALLINT UNSIGNED PRIMARY KEY, native_name VARCHAR(48) NOT NULL,
 engine VARCHAR(16) NOT NULL, contract_version INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS web_m2p_valuation (
 pid INT UNSIGNED PRIMARY KEY,level SMALLINT UNSIGNED NOT NULL,
 price_version INT UNSIGNED NOT NULL,reference_version INT UNSIGNED NOT NULL,
 equipped BIGINT NOT NULL,other BIGINT NOT NULL,strength BIGINT NOT NULL,
 reference_wealth BIGINT NOT NULL,complete TINYINT NOT NULL,
 valued_at DATETIME NOT NULL,cash_at DATETIME NULL,excluded INT NOT NULL DEFAULT 0,
 KEY cohort (complete,reference_version,level,valued_at)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS web_m2p_price_reference (
 singleton TINYINT PRIMARY KEY,median BIGINT NOT NULL DEFAULT 0,
 cohort INT UNSIGNED NOT NULL DEFAULT 0,reference_version INT UNSIGNED NOT NULL DEFAULT 0,
 world_started BIGINT NOT NULL DEFAULT 0,reason VARCHAR(48) NOT NULL DEFAULT 'price_missing_cohort',
 updated_at DATETIME NOT NULL DEFAULT '1971-01-01'
) ENGINE=InnoDB;
INSERT IGNORE INTO web_m2p_price_reference(singleton) VALUES(1);
CREATE TABLE IF NOT EXISTS web_m2p_population (
 singleton TINYINT PRIMARY KEY,desired INT UNSIGNED NOT NULL,last_env INT UNSIGNED NOT NULL,
 last_env_revision VARCHAR(64) NOT NULL DEFAULT '',source VARCHAR(24) NOT NULL,updated_at DATETIME NOT NULL
) ENGINE=InnoDB;
ALTER TABLE web_m2p_population ADD COLUMN IF NOT EXISTS last_env_revision VARCHAR(64) NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS web_m2p_population_runtime (
 channel SMALLINT UNSIGNED NOT NULL,port INT UNSIGNED NOT NULL,applied INT UNSIGNED NOT NULL,
 boot_at DATETIME NOT NULL,seen_at DATETIME NOT NULL DEFAULT '1971-01-01',PRIMARY KEY(channel,port)
) ENGINE=InnoDB;
ALTER TABLE web_m2p_population_runtime ADD COLUMN IF NOT EXISTS seen_at DATETIME NOT NULL DEFAULT '1971-01-01';
CREATE TABLE IF NOT EXISTS web_m2p_persona_profile (
 pid INT UNSIGNED PRIMARY KEY, persona_id SMALLINT UNSIGNED NULL,
 queue_id INT UNSIGNED NOT NULL, updated_at DATETIME NOT NULL,
 applied_queue INT UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS web_m2p_persona_history (
 id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, pid INT UNSIGNED NOT NULL,
 at DATETIME NOT NULL, old_id SMALLINT NULL, new_id SMALLINT NOT NULL,
 reason VARCHAR(16) NOT NULL, queue_id INT UNSIGNED NULL,
 KEY pid_at (pid,at), UNIQUE KEY job_once (queue_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE web_m2p_persona_history ADD INDEX IF NOT EXISTS job_lookup (queue_id);
-- A legacy panel wrote intended changes as history before the core applied
-- them. Keep these records distinguishable; never present them as execution.
UPDATE web_m2p_persona_history h JOIN web_admin_queue q ON q.id=h.queue_id
 SET h.reason='legacy_request' WHERE h.reason='panel' AND q.status<>'done';
-- Keep duplicate legacy requests for inspection, but detach their job key.
UPDATE web_m2p_persona_history newer JOIN web_m2p_persona_history older
 ON newer.queue_id=older.queue_id AND newer.id>older.id SET newer.queue_id=NULL;
ALTER TABLE web_m2p_persona_history ADD UNIQUE INDEX IF NOT EXISTS job_once (queue_id);
CREATE TABLE IF NOT EXISTS web_m2p_contract_state (
 name VARCHAR(64) PRIMARY KEY, value BIGINT NOT NULL,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
