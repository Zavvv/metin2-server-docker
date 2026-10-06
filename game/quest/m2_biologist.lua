-- The stock reward calls, shared by natural hand-ins and companions.
-- Companion item calls are queued by the native scoped reward context.
-- No state changes, level gates, dialogs or yields in the companion path.
m2_biologist = {}
m2_biologist.rewards = {
    ["make_herb_lv4"] = function(companion)
        local weapon_reward_by_job = {
            [JOB_SHAMAN] = {7003},
            [JOB_ASSASSIN] = {1003, 2003},
            [JOB_WARRIOR] = {13, 3003},
            [JOB_SURA] = {13}
        }
        give_reward("herb_lv4", companion and GIVE_REWARD_TYPE_ONLY_GIVE or nil)

        if companion then
            pc.give_item2(weapon_reward_by_job[pc.job][1], 1, 0)
        else
            select_weapon_reward(weapon_reward_by_job[pc.job])
        end
    end,
    ["make_herb_lv7"] = function(companion)
        give_reward("herb_lv7", companion and GIVE_REWARD_TYPE_ONLY_GIVE or nil)
    end,
    ["make_herb_lv10"] = function(companion)
        give_reward("herb_lv10", companion and GIVE_REWARD_TYPE_ONLY_GIVE or nil)
    end,
    ["make_herb_lv15"] = function(companion)
        give_reward("herb_lv15", companion and GIVE_REWARD_TYPE_ONLY_GIVE or nil)
    end,
    ["make_herb_lv20"] = function(companion)
        give_reward("herb_lv20", companion and GIVE_REWARD_TYPE_ONLY_GIVE or nil)
    end,
    ["make_herb_lv25"] = function(companion)
        give_reward("herb_lv25", companion and GIVE_REWARD_TYPE_ONLY_GIVE or nil)
    end,
    ["collect_quest_lv30"] = function(companion)
        affect.add_collect(POINT_MOV_SPEED, 10)
        pc.give_item2(50109)
    end,
    ["collect_quest_lv40"] = function(companion)
        affect.add_collect(POINT_ATT_SPEED, 5)
        pc.give_item2(50110)
    end,
    ["collect_quest_lv50"] = function(companion)
        affect.add_collect(POINT_DEF_GRADE_BONUS, 60)
        pc.give_item2(50111)
    end,
    ["collect_quest_lv60"] = function(companion)
        affect.add_collect(POINT_ATT_GRADE_BONUS, 50)
        pc.give_item2(50112)
    end,
    ["collect_quest_lv70"] = function(companion)
        affect.add_collect(POINT_MOV_SPEED, 11)
        affect.add_collect(POINT_DEF_BONUS, 10)
        pc.give_item2(50113)
    end,
    ["collect_quest_lv80"] = function(companion)
        affect.add_collect(POINT_ATT_SPEED,6,60*60*24*365*60)
        affect.add_collect(POINT_ATT_BONUS,10,60*60*24*365*60)
        pc.give_item2(50114)
    end,
    ["collect_quest_lv85"] = function(companion)
        pc.give_item2(50115)
        affect.add_collect(POINT_RESIST_HUMAN, 10)
    end,
    ["collect_quest_lv90"] = function(companion)
        affect.add_collect(POINT_ATTBONUS_HUMAN,8)
        pc.give_item2(50114)
    end,
}

function m2_biologist.reward(name, companion)
    if companion and pc.getf(name, "sk_reward_paid") ~= 0 then return true end
    local reward = m2_biologist.rewards[name]
    if reward == nil then error("unknown Biologist reward: " .. name) end
    reward(companion)
    if companion then pc.setf(name, "sk_reward_paid", 1) end
    return true
end
