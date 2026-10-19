-- The GM's quest skip and "Przemiana" (Kiciamol, 16-17 October; mt2009 only:
-- the quests and their libraries are that image's). Applied by the migrator
-- at every start; nothing here deletes or rewrites what is already there.
--
-- player.web_quest_admin_actions is the queue F9 and the panel write and the
-- character's own timer carries out (gm_quest_admin.lua). active_key stays
-- set after applying/done/uncertain - a crash must never replay a reward; it
-- is released only for a rejection before anything was changed.
CREATE TABLE IF NOT EXISTS player.web_quest_admin_actions (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 request_key VARCHAR(100) CHARACTER SET ascii NOT NULL,
 active_key VARCHAR(100) CHARACTER SET ascii DEFAULT NULL,
 player_id INT UNSIGNED NOT NULL,
 quest_name VARCHAR(64) CHARACTER SET ascii NOT NULL,
 expected_state INT NOT NULL,
 reward_signature VARCHAR(80) CHARACTER SET ascii NOT NULL,
 variant VARCHAR(32) CHARACTER SET ascii NOT NULL DEFAULT '',
 expected_cycle INT NOT NULL DEFAULT -1,
 requester VARCHAR(64) NOT NULL,
 source VARCHAR(8) CHARACTER SET ascii NOT NULL,
 reason VARCHAR(200) NOT NULL,
 status VARCHAR(24) CHARACTER SET ascii NOT NULL DEFAULT 'pending',
 result VARCHAR(200) NOT NULL DEFAULT '',
 claim VARCHAR(64) CHARACTER SET ascii NOT NULL DEFAULT '',
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 expires_at TIMESTAMP NOT NULL,
 finished_at TIMESTAMP NULL DEFAULT NULL,
 UNIQUE KEY request_once(request_key),
 UNIQUE KEY reward_once(active_key),
 KEY pending_work(status,id),
 KEY player_history(player_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- The switch: on in a new world (the panel's "Misje graczy" turns it off and
-- on); a world that already has the row keeps the operator's choice.
CREATE TABLE IF NOT EXISTS player.web_quest_admin_config (
 id INT NOT NULL PRIMARY KEY,
 enabled TINYINT NOT NULL DEFAULT 0
) ENGINE=InnoDB;
INSERT IGNORE INTO player.web_quest_admin_config(id,enabled) VALUES(1,1);

-- One possession at a time a GM account and a bot (gm_possess.lua): what the
-- bot's account was, so any login of the GM's account puts it back.
CREATE TABLE IF NOT EXISTS player.gm_possess (
 bot_pid INT UNSIGNED NOT NULL PRIMARY KEY,
 bot_account INT UNSIGNED NOT NULL,
 gm_account INT UNSIGNED NOT NULL,
 gm_pid INT UNSIGNED NOT NULL DEFAULT 0,
 old_password VARCHAR(64) NOT NULL,
 old_status VARCHAR(16) NOT NULL,
 old_login VARCHAR(30) NOT NULL DEFAULT '',
 started_at DATETIME NOT NULL,
 claim_token CHAR(32) CHARACTER SET ascii NOT NULL DEFAULT '',
 phase TINYINT UNSIGNED NOT NULL DEFAULT 0,
 UNIQUE KEY one_gm_session(gm_account),
 UNIQUE KEY one_bot_account(bot_account)
) ENGINE=InnoDB;

-- The level-19 quest's skill book had no count ('50301'), and the reward
-- reader drops an item without one: the book was never given, by the quest
-- or by a skip. Only that exact value is changed.
UPDATE world.quest_reward_proto SET items = '50301,1'
 WHERE quest_name = 'new_quest_lv19' AND items = '50301';

-- What the migrator's log says.
SELECT CONCAT('gm quest skip: ', (SELECT COUNT(*) FROM player.web_quest_admin_actions), ' actions, ',
              IF((SELECT enabled FROM player.web_quest_admin_config WHERE id = 1) = 1, 'on', 'off'),
              '; possessions open: ', (SELECT COUNT(*) FROM player.gm_possess));
