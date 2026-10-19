-- "Przemiana" (Kiciamol, 16-17 October): a GM takes over a playerbot of the
-- population and plays it as his own character, and goes back to his GM with
-- one button. gm_possess.quest calls login() at every login and request() for
-- the client's input (gmpossess.py); the account changes are this file's.
--
-- Ours over his package (2.0.92 -> 2.2.100), and why:
--
--   * The bot leaves through the ban ledger, never by /bot_despawn. The core
--     keeps every registered identity from its boot and puts a missing one
--     back a minute later (TopUpMissingBots); a GM's own client logging in
--     on the PID in that window found the respawned bot, and a possessed
--     character warping to another core in it was a second copy of one
--     character. account.account_block is what RefreshBannedBots reads, on
--     the same clock just before the top-up, and it takes a banned bot out of
--     the world and out of every queue: a row for the bot's account (status
--     1, so BanManager's FlushBlock never blocks the account for real, and
--     nothing at the login reads it) keeps it out for as long as the GM plays
--     it. The handover waits until the bot is gone from this core AND a
--     whole minute has passed, so every core has read the row.
--   * The GM logs in as pbNNN (the bot's pid), as in his package: the auth
--     core refuses an underscore in a login (input_auth.cpp's
--     FN_IS_VALID_LOGIN_STRING, ENABLE_ACCOUNT_W_SPECIALCHARS off), so
--     playerbot_NNN was "NOID" and the client said "wrong login or password"
--     (b8414f4c, 17 October). The account is renamed only at the handover and
--     back at the possessed character's own login; RefreshBannedBots reads a
--     gm_possess row whatever the login is (playerbot_manager.cpp).
--   * The one-time password is the engine's own hash (input_auth.cpp's
--     _MYSQL_NATIVE_PASSWORD), not PASSWORD(), which a MariaDB may lack.
--   * Only a registered bot of the population (the seed ledger, the login the
--     registry accepts, one character), never a player's companion, and only
--     a GM_IMPLEMENTOR - the level /bot_despawn and the F10 panel ask.
--   * A bot's own login is never asked anything here (pc.is_playerbot).
--   * The texts are the reader's language (playerbot_lang.quest).
--
-- player.gm_possess holds one session: the bot, its account, the GM's
-- account, what the account was, the phase (0 waiting for the bot to leave,
-- 1 the one-time login handed to the GM's client). Any login of the GM's
-- account ends what is there (restore), so a crash leaves nothing behind
-- that the next login does not put right. Secrets never reach a log.

gm_possess_lib = {}
local M = gm_possess_lib

M.GM_LEVEL = 5          -- GM_IMPLEMENTOR, as /bot_despawn
M.SETTLE_SECONDS = 61   -- one RefreshBannedBots round on every core
M.GIVE_UP_SECONDS = 150 -- the bot never left: give the session up
M.REASON = "gm_possess"

function M.t(pl, en)
	if pc.getf("playerbot_lang", "en") == 1 then
		return playerbot_quest_text ~= nil and playerbot_quest_text(en) or en
	end
	return pl
end

function M.query(sql)
	local a, b = mysql_direct_query(sql)
	if type(a) == "table" then return a end
	if type(b) == "table" then return b end
	return nil
end

function M.hex(s)
	return (string.gsub(tostring(s), '.', function(c) return string.format('%02x', string.byte(c)) end))
end

function M.literal(s)
	return "X'" .. M.hex(s) .. "'"
end

-- input_auth.cpp's _MYSQL_NATIVE_PASSWORD, which the auth core compares with.
function M.hash(token)
	return "CONCAT('*',UPPER(SHA1(UNHEX(SHA1(" .. M.literal(token) .. ")))))"
end

function M.login_of(pid)
	return "pb" .. pid
end

-- The account's login back to the bot's own, from pbNNN or as it stands.
function M.logins(row)
	return "BINARY login IN (BINARY " .. M.literal(M.login_of(row.bot_pid)) .. ",BINARY " .. M.literal(row.old_login) .. ")"
end

function M.fail(message)
	if message then syschat(message) end
	cmdchat("GMPossessFail")
	return false
end

function M.is_bot()
	return pc.is_playerbot ~= nil and pc.is_playerbot()
end

function M.mine()
	return M.query("SELECT * FROM player.gm_possess WHERE bot_pid=" .. pc.get_player_id() ..
		" AND bot_account=" .. pc.get_account_id() .. " AND phase=1")
end

-- The bot's name, for find_pc_by_name: whether it stands on this core.
function M.online(pid)
	local rows = M.query("SELECT name FROM player.player WHERE id=" .. pid)
	if not rows or not rows[1] or type(rows[1].name) ~= "string" then return false end
	return find_pc_by_name(rows[1].name) ~= 0
end

-- Put back every session of this GM account. False while one could not be
-- (its row and the block stay for the next login).
function M.restore(account)
	local rows = M.query("SELECT * FROM player.gm_possess WHERE gm_account=" .. account)
	if not rows then return false, 0 end
	local done = 0
	for _, row in ipairs(rows) do
		local pid = tonumber(row.bot_pid)
		local acc = tonumber(row.bot_account)
		if not pid or not acc or row.old_login == "" then return false, done end
		-- The possessed character still in the world here (a second client):
		-- the bot must not come back while it plays.
		if tonumber(row.phase) == 1 and M.online(pid) then return false, done end
		M.query("UPDATE account.account SET login=" .. M.literal(row.old_login) .. ",password=" .. M.literal(row.old_password) ..
			",status=" .. M.literal(row.old_status) .. " WHERE id=" .. acc .. " AND " .. M.logins(row))
		local check = M.query("SELECT login,password,status FROM account.account WHERE id=" .. acc)
		if not check or not check[1] or check[1].login ~= row.old_login or check[1].password ~= row.old_password or
				check[1].status ~= row.old_status then
			return false, done -- keep the recovery data
		end
		M.query("DELETE FROM account.account_block WHERE account_id=" .. acc .. " AND reason='" .. M.REASON .. "'")
		M.query("DELETE FROM player.gm_possess WHERE bot_pid=" .. pid .. " AND gm_account=" .. account)
		done = done + 1
	end
	return true, done
end

-- The summon books of horse_summon, by the horse's grade (horse.get_grade():
-- 1 at horse levels 1-10, 2 at 11-20, 3 from 21); a horse is called only with
-- the book of its own grade.
M.HORSE_BOOKS = { 50051, 50052, 50053 }

-- A possessed character gets the book of the horse it has. No bot needs one -
-- the AI calls its horse without a book - so a bot carried none of its first
-- horse, and a bot granted the military horse before 2.2.109 the armoured
-- horse's 50052, which horse_summon refuses for a horse of grade 3: the GM
-- had a book and no horse (sosen, 022b6e2c, 18 October). A book of another
-- grade is taken for it; the stable keeper would only sell another.
function M.horse_book()
	if type(horse) ~= "table" or type(horse.get_grade) ~= "function" then return end
	local grade = horse.get_grade()
	local want = M.HORSE_BOOKS[grade]
	if not want or pc.countitem(want) > 0 then return end
	for g, vnum in ipairs(M.HORSE_BOOKS) do
		local held = pc.countitem(vnum)
		if g ~= grade and held > 0 then pc.removeitem(vnum, held) end
	end
	pc.give_item2(want, 1)
	syschat(M.t("Przemiana: w plecaku jest ksiega przywolania konia tego bota.",
		"Possession: the bag holds the summon book of this bot's horse."))
end

function M.login()
	if type(mysql_direct_query) ~= "function" or M.is_bot() then return end
	local mine = M.mine()
	if not mine then return end
	if mine[1] then
		local row = mine[1]
		local acc = tonumber(row.bot_account)
		-- Spending the one-time login closes the account again, under the
		-- bot's own login (the session keeps the login it came in with).
		M.query("UPDATE account.account SET login=" .. M.literal(row.old_login) .. ",password=" .. M.literal(row.old_password) ..
			",status=" .. M.literal(row.old_status) .. " WHERE id=" .. acc .. " AND " .. M.logins(row))
		local check = M.query("SELECT login,password,status FROM account.account WHERE id=" .. acc)
		if not check or not check[1] or check[1].login ~= row.old_login or check[1].password ~= row.old_password or
				check[1].status ~= row.old_status then
			M.fail(M.t("Przemiana: nie udalo sie zamknac jednorazowego logowania. Wroc na konto GM.",
				"Possession: the one-time login could not be closed. Go back to the GM account."))
			return
		end
		M.horse_book()
		cmdchat("GMPossessReady " .. q.getcurrentquestindex() .. " bot")
		return
	end
	-- Any character of the GM's account ends what a session left behind.
	local restored, count = M.restore(pc.get_account_id())
	if not restored then
		syschat(M.t("Przemiana: bot jest jeszcze w grze - sprobuje oddac go za chwile.",
			"Possession: the bot is still in the game - trying to give it back in a moment."))
		timer("gm_possess_retry", 10)
		return
	end
	if count > 0 then
		syschat(M.t("Przemiana zakonczona - bot wroci do gry w ciagu minuty.",
			"Possession over - the bot is back in the game within a minute."))
	end
	if pc.is_gm() then cmdchat("GMPossessReady " .. q.getcurrentquestindex() .. " gm") end
end

function M.session(account)
	local rows = M.query("SELECT g.*,TIMESTAMPDIFF(SECOND,g.started_at,NOW()) AS age FROM player.gm_possess g WHERE g.gm_account=" .. account)
	if not rows then return nil end
	return rows[1] or false
end

function M.possess(name)
	local account = pc.get_account_id()
	local busy = M.session(account)
	if busy == nil then return M.fail() end
	if busy then
		return M.fail(M.t("Najpierw wroc z poprzedniej przemiany.", "Come back from the previous possession first."))
	end
	local rows = M.query("SELECT p.id AS pid,a.id AS acc,a.login FROM player.player p " ..
		"JOIN account.account a ON a.id=p.account_id JOIN player.player_index i ON i.id=a.id " ..
		"JOIN common.playerbot_seed_state s ON s.pid=p.id " ..
		"WHERE BINARY p.name=BINARY " .. M.literal(name) .. " AND s.seed_version=1 AND s.state IN ('complete','adopted') " ..
		"AND BINARY a.login=BINARY CONCAT('playerbot_',LPAD(s.pid-3,GREATEST(3,LENGTH(s.pid-3)),'0')) " ..
		"AND i.pid1=p.id AND i.pid2=0 AND i.pid3=0 AND i.pid4=0 " ..
		"AND NOT EXISTS (SELECT 1 FROM player.playerbot_sidekick k WHERE k.sidekick_pid=p.id) LIMIT 1")
	if not rows or not rows[1] then
		return M.fail(M.t("To nie jest bot populacji (towarzysza gracza nie mozna przejac).",
			"That is not a bot of the population (a player's companion cannot be taken over)."))
	end
	local bot = rows[1]
	local pid = tonumber(bot.pid)
	local acc = tonumber(bot.acc)
	if not pid or not acc or acc == account then return M.fail() end
	if find_pc_by_name(name) == 0 then
		return M.fail(M.t("Bot nie jest w grze na tym kanale.", "The bot is not in the game on this channel."))
	end
	local banned = M.query("SELECT account_id FROM account.account_block WHERE account_id=" .. acc .. " LIMIT 1")
	if not banned then return M.fail() end
	if banned[1] then
		return M.fail(M.t("Ten bot jest zablokowany.", "This bot is banned."))
	end
	local random = M.query("SELECT LOWER(HEX(RANDOM_BYTES(8))) AS token")
	if not random or not random[1] or type(random[1].token) ~= "string" or string.len(random[1].token) ~= 16 then
		return M.fail()
	end
	local claim = random[1].token
	-- Both unique keys hold across every core: one session a GM, one a bot.
	M.query("INSERT IGNORE INTO player.gm_possess(bot_pid,bot_account,gm_account,gm_pid,old_password,old_status,old_login,started_at,claim_token,phase) " ..
		"SELECT " .. pid .. "," .. acc .. "," .. account .. "," .. pc.get_player_id() .. ",password,status,login,NOW(),MD5(" .. M.literal(claim) .. "),0 " ..
		"FROM account.account WHERE id=" .. acc .. " AND BINARY login=BINARY " .. M.literal(bot.login))
	local mine = M.query("SELECT bot_pid FROM player.gm_possess WHERE bot_pid=" .. pid .. " AND gm_account=" .. account ..
		" AND claim_token=MD5(" .. M.literal(claim) .. ")")
	if not mine or not mine[1] then
		return M.fail(M.t("Ten bot jest juz przejmowany.", "This bot is already being taken over."))
	end
	M.query("INSERT INTO account.account_block(account_id,ban_duration,pid,who,reason,status,flush_time) VALUES(" ..
		acc .. ",0," .. pid .. "," .. pc.get_player_id() .. ",'" .. M.REASON .. "',1,NOW())")
	local blocked = M.query("SELECT account_id FROM account.account_block WHERE account_id=" .. acc .. " AND reason='" .. M.REASON .. "'")
	if not blocked or not blocked[1] then
		M.restore(account)
		return M.fail(M.t("Nie udalo sie wylaczyc bota.", "The bot could not be taken out."))
	end
	syschat(M.t("Przemiana: bot opuszcza swiat, to potrwa okolo minuty.",
		"Possession: the bot is leaving the world, this takes about a minute."))
	cmdchat("GMPossessWait " .. M.SETTLE_SECONDS)
	return true
end

-- The client asks every few seconds until the bot has gone and every core
-- has read the block; then the one-time login goes to the GM's client.
function M.check()
	local account = pc.get_account_id()
	local row = M.session(account)
	if not row then return M.fail() end
	if tonumber(row.phase) ~= 0 then return M.fail() end
	local pid = tonumber(row.bot_pid)
	local acc = tonumber(row.bot_account)
	local age = tonumber(row.age) or 0
	if age > M.GIVE_UP_SECONDS then
		M.restore(account)
		return M.fail(M.t("Bot nie opuscil swiata - przemiana anulowana.",
			"The bot did not leave the world - possession cancelled."))
	end
	if age < M.SETTLE_SECONDS or M.online(pid) then
		cmdchat("GMPossessWait " .. math.max(1, M.SETTLE_SECONDS - age))
		return true
	end
	local login = M.login_of(pid)
	local taken = M.query("SELECT id FROM account.account WHERE BINARY login=BINARY " .. M.literal(login) .. " AND id<>" .. acc)
	if not taken then return M.fail() end
	if taken[1] then
		M.restore(account)
		return M.fail(M.t("Login " .. login .. " ma juz inne konto - przemiana anulowana.",
			"The login " .. login .. " belongs to another account - possession cancelled."))
	end
	local random = M.query("SELECT LOWER(HEX(RANDOM_BYTES(8))) AS token")
	if not random or not random[1] then return M.fail() end
	local token = random[1].token
	if type(token) ~= "string" or string.len(token) ~= 16 or string.find(token, "[^%da-f]") then return M.fail() end
	M.query("UPDATE account.account a JOIN player.gm_possess g ON g.bot_account=a.id SET a.login=" .. M.literal(login) ..
		",a.status='OK',a.password=" .. M.hash(token) .. " WHERE g.bot_pid=" .. pid .. " AND g.gm_account=" .. account ..
		" AND g.phase=0 AND BINARY a.login=BINARY g.old_login")
	M.query("UPDATE player.gm_possess SET phase=1 WHERE bot_pid=" .. pid .. " AND gm_account=" .. account .. " AND phase=0")
	local check = M.query("SELECT id FROM account.account WHERE id=" .. acc .. " AND BINARY login=BINARY " ..
		M.literal(login) .. " AND status='OK' AND password=" .. M.hash(token))
	if not check or not check[1] then
		M.restore(account)
		return M.fail(M.t("Nie udalo sie przygotowac konta bota.", "The bot's account could not be prepared."))
	end
	-- The registry admits one character an account: slot 0.
	cmdchat("GMPossessGo " .. login .. " " .. token .. " " .. pid .. " 0")
	return true
end

function M.request(request)
	if type(request) ~= "string" or string.len(request) > 40 then return M.fail() end
	local _, _, cmd, arg = string.find(request, "^(%a+)%s*(.*)$")
	if cmd == "release" then
		local rows = M.mine()
		if not rows or not rows[1] then return M.fail() end
		if pc.is_dead() or pc.is_busy() then
			return M.fail(M.t("Najpierw zamknij handel lub sklep.", "Close the trade or the shop first."))
		end
		cmdchat("GMPossessBack")
		return true
	end
	if not pc.is_gm() or pc.get_gm_level() < M.GM_LEVEL then
		return M.fail(M.t("Przemiana jest tylko dla GM z pelnymi uprawnieniami.",
			"Possession is for a GM with full rights only."))
	end
	if cmd == "cancel" then
		M.restore(pc.get_account_id())
		return M.fail()
	end
	if cmd == "check" then return M.check() end
	if cmd ~= "possess" or not arg or string.len(arg) < 2 or string.len(arg) > 24 or string.find(arg, "[%c%s]") then
		return M.fail()
	end
	if pc.is_dead() or pc.is_busy() then
		return M.fail(M.t("Najpierw zamknij handel lub sklep.", "Close the trade or the shop first."))
	end
	return M.possess(arg)
end
