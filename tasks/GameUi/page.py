from itertools import compress

import random

import traceback
from module.atom.click import RuleClick
from tasks.BondlingFairyland.assets import BondlingFairylandAssets
from tasks.Duel.assets import DuelAssets
from tasks.GlobalGame.assets import GlobalGameAssets as GGA
from tasks.GameUi.assets import GameUiAssets as G
from tasks.KekkaiUtilize.assets import KekkaiUtilizeAssets
from tasks.Restart.assets import RestartAssets
from tasks.base_task import BaseTask as BT
from tasks.RyouToppa.assets import RyouToppaAssets


class PageRegistry:
    _registry = []

    @classmethod
    def register(cls, page):
        cls._registry.append(page)

    @classmethod
    def all(cls):
        return list(cls._registry)


class Page:
    def __init__(self, check_button, links=None):
        if links is None:
            links = {}
        self.check_button = check_button
        self.links = links
        self.additional: list = None  # 附加按钮或者是ocr检测按钮
        (filename, line_number, function_name, text) = traceback.extract_stack()[-2]
        self.name = text[:text.find('=')].strip()
        PageRegistry.register(self)

    def __eq__(self, other):
        # 只和 Page 比较：ui_current 在 ui_goto 失败时会被置为 None，
        # 早先直接取 other.name 会让 `None == page_login` 抛
        # AttributeError: 'NoneType' object has no attribute 'name'（2026-10-01 00:01 两次崩溃）。
        if not isinstance(other, Page):
            return NotImplemented
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name

    def link(self, button, destination):
        self.links[destination] = button


#登录login
page_login = Page(G.I_CHECK_LOGIN_FORM)
# Main Home 主页
page_main = Page(G.I_CHECK_MAIN)
page_main.additional = [G.I_AD_CLOSE_RED, G.I_BACK_FRIENDS, RestartAssets.I_CANCEL_BATTLE,
                            GGA.I_CHAT_CLOSE_BUTTON, G.I_CLOSE_CHAT_WINDOW,
                            [G.I_MAIN_GOTO_SHIKIGAMI_RECORDS, RestartAssets.C_LOGIN_SCROLL_CLOSE_AREA, True]]
# 召唤summon
page_summon = Page(G.I_CHECK_SUMMON)
page_summon.link(button=G.I_SUMMON_GOTO_MAIN, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_SUMMON, destination=page_summon)
# 探索exploration
page_exploration = Page(G.I_CHECK_EXPLORATION)
page_exploration.link(button=G.I_BACK_YOLLOW, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_EXPLORATION, destination=page_exploration)
# 町中town
page_town = Page(G.I_CHECK_TOWN)
page_town.link(button=G.I_TOWN_GOTO_MAIN, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_TOWN, destination=page_town)

# ************************************* 探索部分 *****************************************#
# 觉醒 awake zones
page_awake_zones = Page(G.I_CHECK_AWAKE)
page_awake_zones.link(button=G.I_BACK_YOLLOW, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_AWAKE_ZONE, destination=page_awake_zones)
# 御魂 soul zones
page_soul_zones = Page(G.I_CHECK_SOUL_ZONES)
page_soul_zones.link(button=G.I_BACK_YOLLOW, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_SOUL_ZONE, destination=page_soul_zones)
# 结界突破 realm raid
page_realm_raid = Page(G.I_CHECK_REALM_RAID)
page_realm_raid.link(button=G.I_REALM_RAID_GOTO_EXPLORATION, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_REALM_RAID, destination=page_realm_raid)
# 寮结界突破右上角 kekkai toppa
page_kekkai_toppa = Page(G.I_KEKKAI_TOPPA)
page_kekkai_toppa.link(button=G.I_REALM_RAID_GOTO_EXPLORATION, destination=page_exploration)
page_realm_raid.link(button=RyouToppaAssets.I_RYOU_TOPPA, destination=page_kekkai_toppa)
page_kekkai_toppa.link(button=G.I_RYOUTOPPA_GOTO_REALMRAID, destination=page_realm_raid)
# 御灵 goryou realm
page_goryou_realm = Page(G.I_CHECK_GORYOU)
page_goryou_realm.link(button=G.I_BACK_YOLLOW, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_GORYOU_REALM, destination=page_goryou_realm)
# 委派 delegation
page_delegation = Page(G.I_CHECK_DELEGATION)
page_delegation.link(button=G.I_BACK_YOLLOW, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_DELEGATION, destination=page_delegation)
# 秘闻副本 SECRET zones
page_secret_zones = Page(G.I_CHECK_SECRET_ZONES)
page_secret_zones.link(button=G.I_BACK_YOLLOW, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_SECRET_ZONES, destination=page_secret_zones)
# 地域鬼王 area boss
page_area_boss = Page(G.I_CHECK_AREA_BOSS)
page_area_boss.link(button=G.I_BACK_YOLLOW, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_AREA_BOSS, destination=page_area_boss)
# 平安奇谭 heian kitan
page_heian_kitan = Page(G.I_CHECK_HEIAN_KITAN)
page_heian_kitan.link(button=G.I_CHECK_HEIAN_KITAN, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_HEIAN_KITAN, destination=page_heian_kitan)
# 六道之门 six gates
page_six_gates = Page(G.I_CHECK_SIX_GATES)
page_six_gates.link(button=G.I_SIX_GATES_GOTO_EXPLORATION, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_SIX_GATES, destination=page_six_gates)
# 契灵之境 bondling fairyland
page_bondling_fairyland = Page(BondlingFairylandAssets.I_BALL_AREA)
page_bondling_fairyland.link(button=G.I_BACK_YOLLOW, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_BONDLING_FAIRYLAND, destination=page_bondling_fairyland)
# 英杰试炼 hero test
page_hero_test = Page(G.I_CHECK_HERO_TEST)
page_hero_test.link(button=G.I_BACK_YOLLOW, destination=page_exploration)
page_exploration.link(button=G.I_EXPLORATION_GOTO_HERO_TEST, destination=page_hero_test)

# ************************************* 町中部分 *****************************************#
# 斗技 duel
page_duel = Page(G.I_CHECK_DUEL)
page_duel.additional = [DuelAssets.I_D_TRY]
page_duel.link(button=G.I_BACK_YOLLOW, destination=page_town)
page_town.link(button=G.I_TOWN_GOTO_DUEL, destination=page_duel)
# 逢魔之时 demon_encounter
page_demon_encounter = Page(G.I_CHECK_DEMON_ENCOUNTER)
page_demon_encounter.link(button=G.I_BACK_YOLLOW, destination=page_town)
page_town.link(button=G.I_TOWN_GOTO_DEMON_ENCOUNTER, destination=page_demon_encounter)
# 逢魔之时现世逢魔 demon_encounter_realworld
page_demon_encounter_realworld = Page(G.I_CHECK_DEMON_ENCOUNTER_REALWORLD)
page_demon_encounter_realworld.link(button=G.I_BACK_YOLLOW, destination=page_demon_encounter)
page_demon_encounter.link(button=G.I_DEMON_ENCOUNTER_REALWORLD_GOTO, destination=page_demon_encounter_realworld)
# 狩猎战 hunt
page_hunt = Page(G.I_CHECK_HUNT)
page_hunt.link(button=G.I_BACK_YOLLOW, destination=page_town)
page_town.link(button=G.I_TOWN_GOTO_HUNT, destination=page_hunt)
# 狩猎战麒麟 hunt_kirin
page_hunt_kirin = Page(G.I_CHECK_HUNT_KIRIN)
page_hunt_kirin.link(button=G.I_BACK_YOLLOW, destination=page_town)
page_town.link(button=G.I_TOWN_GOTO_HUNT, destination=page_hunt_kirin)
# 协同斗技 draft_duel
page_draft_duel = Page(G.I_CHECK_DRAFT_DUEL)
page_draft_duel.link(button=G.I_BACK_YOLLOW, destination=page_town)
page_town.link(button=G.I_TOWN_GOTO_DRAFT_DUEL, destination=page_draft_duel)
# 百鬼弈 hyakkisen
page_hyakkisen = Page(G.I_CHECK_HYAKKISEN)
page_hyakkisen.link(button=G.I_BACK_YOLLOW, destination=page_town)
page_town.link(button=G.I_TOWN_GOTO_HYAKKISEN, destination=page_hyakkisen)
# 百鬼夜行
page_hyakkiyakou = Page(G.I_CHECK_KYAKKIYAKOU)
page_hyakkiyakou.link(button=G.I_HYAKKIYAKOU_CLOSE, destination=page_town)
page_town.link(button=G.I_TOWN_GOTO_HYAKKIYAKOU, destination=page_hyakkiyakou)

# ************************************* 庭院部分 *****************************************#
# 式神录 shikigami_records
page_shikigami_records = Page(G.I_CHECK_RECORDS)
page_shikigami_records.additional = [G.I_AD_DISAPPEAR, G.I_RECORDS_CLOSE, GGA.I_UI_CANCEL_SAMLL]
page_shikigami_records.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_SHIKIGAMI_RECORDS, destination=page_shikigami_records)
# 阴阳术 onmyodo
page_onmyodo = Page(G.I_CHECK_ONMYODO)
page_onmyodo.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_ONMYODO, destination=page_onmyodo)
# 好友 friends
page_friends = Page(G.I_CHECK_FRIENDS)
page_friends.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_FRIENDS, destination=page_friends)
# 花合战 daily
page_daily = Page(G.I_CHECK_DAILY)
# page_daily.additional = [G.O_CLICK_CLOSE_1, G.O_CLICK_CLOSE_2]
page_daily.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_DAILY, destination=page_daily)
from tasks.DailyTrifles.assets import DailyTriflesAssets

# 商店 mall
page_mall = Page(check_button=[G.I_CHECK_MALL, DailyTriflesAssets.I_ROOM_GIFT])
# 之前这里还带一个 G.I_BACK_Y，但商店页左上角那个返回箭头同时命中
# I_BACK_Y(0.961)/I_BACK_YOLLOW(0.986)/I_UI_BACK_YELLOW(0.986)——也就是下一页
# link 用的那个按钮本身。additional 是给弹窗用的，把页面自己的返回键放进去，
# 结果是 ui_goto(page_mall) 一到店 run_additional 就点它、商店立刻退回庭院
# （2026-10-01 00:01 oas1/oas2 两次崩溃的触发源：商店签到因此认不出礼包屋）。
page_mall.additional = [G.I_AD_CLOSE_RED, GGA.I_UI_CANCEL_SAMLL]
page_mall.link(button=G.I_BACK_YOLLOW, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_MALL, destination=page_mall)
# 阴阳寮 guild
page_guild = Page(G.I_CHECK_GUILD)
page_guild.additional = [KekkaiUtilizeAssets.I_PLANT_TREE_CLOSE, G.I_CLOSE_CHAT_WINDOW]
page_guild.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_GUILD, destination=page_guild)
# 组队 team
page_team = Page(G.I_CHECK_TEAM)
page_team.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_TEAM, destination=page_team)
# 收集 collection
page_collection = Page(G.I_CHECK_COLLECTION)
page_collection.additional = [GGA.I_UI_CANCEL_SAMLL]
page_collection.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_COLLECTION, destination=page_collection)
# 珍旅居
page_travel = Page(G.I_CHECK_TRAVEL)
page_travel.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=G.I_MAIN_GOTO_TRAVEL, destination=page_travel)

# 道馆
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Dokan.assets import DokanAssets

page_dokan = Page(DokanAssets.I_RYOU_DOKAN_CHECK)
page_dokan.additional = [GeneralBattleAssets.I_EXIT, DokanAssets.I_RYOU_DOKAN_EXIT_ENSURE, G.I_BACK_BLUE]
page_dokan.link(button=G.I_BACK_Y, destination=page_main)

# 摸鱼行动页面
from tasks.WeeklyTrifles.assets import WeeklyTriflesAssets
page_touch_fish = Page(WeeklyTriflesAssets.I_CHECK_TOUCH_FISH)
page_guild.link(button=WeeklyTriflesAssets.I_GUILD_GOTO_TF,destination=page_touch_fish)
page_touch_fish.link(button=WeeklyTriflesAssets.I_WT_TF_GOTO_MAIN,destination=page_main)

# ************************************* 限时活动：为崽而战 *****************************************#
# 这几页必须注册：任务启动时游戏可能正停在里面（上次中断残留 / 手动点进去了），
# 不注册的话 ui_get_current_page() 会判定 Unknown page -> 抛 GamePageUnknownError
# -> script.py 里 task_call('Restart') 强制重启游戏。
from tasks.FightForShikigami.assets import FightForShikigamiAssets as FFS

# 为崽而战 活动主界面（有「八百八狸盛宴」竖排旗的那页）
page_fight_for_shikigami = Page(FFS.I_FFS_BANQUET)
page_fight_for_shikigami.link(button=FFS.I_FFS_BACK, destination=page_main)
# 八百八狸盛宴 六边形地图（高亮格所在页）
page_fight_for_shikigami_map = Page(FFS.I_FFS_MAP_TITLE)
page_fight_for_shikigami_map.link(button=FFS.I_FFS_BACK_MAP, destination=page_fight_for_shikigami)
# 妖怪退治 战斗入口页
page_fight_for_shikigami_battle = Page(FFS.I_FFS_BATTLE_TITLE)
page_fight_for_shikigami_battle.link(button=FFS.I_FFS_BACK, destination=page_fight_for_shikigami_map)


# ************************************* 战斗部分 *****************************************#
# 战斗界面
# page_battle = Page(GeneralBattleAssets.I_BATTLE_INFO)
#
#
def random_click(low: int = None, high: int = None, ltrb: tuple = (True, False, True, False)) -> RuleClick | list[RuleClick]:
    """
    随机生成RuleClick, 不传入参数则返回1个RuleClick, 传入参数则生成范围内的click数组
    :return: RuleClick或者RuleClick的数组
    """
    from tasks.Component.GeneralBattle.assets import GeneralBattleAssets as GBA
    click_area_list = [GBA.C_REWARD_1, GBA.C_REWARD_2, GBA.C_REWARD_3]
    click = random.choice(list(compress(click_area_list, ltrb)))
    click.name = "SAFE_RANDOM_CLICK"
    if low is None or high is None:
        return click
    return [click for _ in range(random.randint(low, high))]
#
#
# # 奖励界面
# page_reward = Page(check_button=[GeneralBattleAssets.I_REWARD_PURPLE_SNAKE_SKIN, GeneralBattleAssets.I_REWARD,
#                                  GeneralBattleAssets.I_REWARD_EXP_SOUL_4, GeneralBattleAssets.I_WIN,
#                                  GeneralBattleAssets.I_REWARD_GOLD, GeneralBattleAssets.I_REWARD_GOLD_SNAKE_SKIN,
#                                  GeneralBattleAssets.I_REWARD_SOUL_5, GeneralBattleAssets.I_REWARD_SOUL_6,
#                                  GGA.I_UI_REWARD, ])
# page_reward.additional = [random_click()]
# # 失败界面
# page_failed = Page(GeneralBattleAssets.I_FALSE)
# page_failed.additional = [random_click()]
