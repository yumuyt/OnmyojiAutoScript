# -*- coding: utf-8 -*-
"""
逢魔boss: "准备按钮 + 集结中 同时可见" 的有界升级测试

背景(2026-10-01 17:09 oas1 极逢魔):
"准备"按钮的 ROI(1128,536,100,100) 和 集结挑战/集结中 按钮的 ROI(1087,562,100,36)
是重叠的, 老代码把"集结中"判定放在"准备页"前面 —— 两个元素同时可见时会一直打
'Boss Gathering...' 而永远不去点准备(人看着就是"卡在准备界面不点准备"), 而且
这个分支每 2 秒 stuck_record_clear 一次, 连 480 秒的长卡死都不会报, 只能人工点。

改法是"有界升级": 正常集结照旧等(实测 oas1 106s / oas2 37s), 只有两个元素同时可见
且持续超过 180 秒才升级去处理准备页 —— 比 480 秒硬卡死早 5 分钟逃出来,
又不会在集结阶段把亮块误当准备页去开一场假战斗。
"""
from types import SimpleNamespace
from unittest import mock

from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.DemonEncounter import script_task as de
from tasks.DemonEncounter.assets import DemonEncounterAssets
from tasks.GlobalGame.assets import GlobalGameAssets


class FakeTimer:
    """替代真 Timer: 只让 180 秒的"集结/准备同时可见"计时器可控, 其余一律不到"""

    escalate_after = None  # None=永不升级; N=第 N 次 reached() 起算到达

    def __init__(self, limit, count=0):
        self.limit = limit
        self.count = count
        self.asks = 0
        self._started = False

    def start(self):
        self._started = True
        return self

    def started(self):
        return self._started

    def clear(self):
        self._started = False
        self.asks = 0
        return self

    def reached(self):
        if self.limit < 180:  # 480/300 的长卡死计时器不参与本测试
            return False
        self.asks += 1
        if FakeTimer.escalate_after is None:
            return False
        return self.asks >= FakeTimer.escalate_after

    def current(self):
        return 180.0


class FakeBossTask:
    """直接跑 execute_boss: find_boss / enter_boss 用最小 stub 过掉"""

    execute_boss = de.ScriptTask.execute_boss
    best_demon_enable = True
    boss_type = 'best_demon_tsuchigumo'

    I_BOSS_FIRE = DemonEncounterAssets.I_BOSS_FIRE
    I_BEST_BOSS_FIRE = DemonEncounterAssets.I_BEST_BOSS_FIRE
    # find_boss 用的素材（194a3eda 那次 boss 搜索重写新增/改用的取用），
    # 这里补齐 stub，否则本文件会以 AttributeError 失败（与本次改动无关的老问题）。
    I_DE_BOSS = DemonEncounterAssets.I_DE_BOSS
    I_DE_BOSS_BEST = DemonEncounterAssets.I_DE_BOSS_BEST
    I_DE_BOX_CENTER = DemonEncounterAssets.I_DE_BOX_CENTER
    I_JADE_50 = DemonEncounterAssets.I_JADE_50
    I_DE_FIND = DemonEncounterAssets.I_DE_FIND
    C_DM_BOSS_CLICK = DemonEncounterAssets.C_DM_BOSS_CLICK
    I_UI_BACK_RED = GlobalGameAssets.I_UI_BACK_RED
    I_BOSS_CONFIRM = DemonEncounterAssets.I_BOSS_CONFIRM
    I_BOSS_GATHER = DemonEncounterAssets.I_BOSS_GATHER
    I_BOSS_WAIT = DemonEncounterAssets.I_BOSS_WAIT
    I_BOSS_DONE_CHECK = DemonEncounterAssets.I_BOSS_DONE_CHECK
    I_BOSS_BACK_WHITE = DemonEncounterAssets.I_BOSS_BACK_WHITE
    I_DE_LOCATION = DemonEncounterAssets.I_DE_LOCATION
    I_PREPARE_HIGHLIGHT = GeneralBattleAssets.I_PREPARE_HIGHLIGHT
    O_DE_BEST_BOSS_PEOPLE = SimpleNamespace(ocr=staticmethod(lambda image: (1, 1, 300)))

    def __init__(self, done_after=3):
        self.device = SimpleNamespace(
            image=None,
            stuck_timer_long=None,
            stuck_record_clear=lambda: None,
            stuck_record_add=lambda button: None,
            click_record_clear=lambda: None,
        )
        self.conf = SimpleNamespace(best_demon_battle_config=SimpleNamespace(
            best_demon_tsuchigumo_enable=False, best_demon_tsuchigumo='1,3'))
        self.current_count = 0
        self.screenshots = 0
        self.gather_seen = 0
        self.done_checks = 0
        self.run_battle_calls = 0
        self.done_after = done_after

    # —— execute_boss 需要的接口 ——
    def screenshot(self):
        self.screenshots += 1

    def appear(self, target, threshold=None, interval=None, **kwargs):
        if target is self.I_BEST_BOSS_FIRE:
            return True  # find_boss / enter_boss 直接过掉
        if target is self.I_PREPARE_HIGHLIGHT:
            return True  # 准备按钮可见(与"集结中"同时可见的现场)
        if target is self.I_BOSS_GATHER:
            self.gather_seen += 1
            return True
        if target is self.I_DE_LOCATION:
            return True  # 收尾循环立刻退出
        if target is self.I_BOSS_DONE_CHECK:
            self.done_checks += 1
            # 升级跑过一次战斗就收尾; 否则等主循环转够 done_after 轮
            return self.run_battle_calls > 0 or self.done_checks > self.done_after
        return False

    def appear_then_click(self, *args, **kwargs):
        return False

    def wait_until_appear(self, target, wait_time=None):
        return True

    def run_general_battle(self, *args, **kwargs):
        self.run_battle_calls += 1
        return True


def run_execute_boss(escalate_after, done_after=3):
    FakeTimer.escalate_after = escalate_after
    task = FakeBossTask(done_after=done_after)
    with mock.patch.object(de, 'Timer', FakeTimer), \
            mock.patch.object(de.time, 'sleep', lambda *args, **kwargs: None), \
            mock.patch.object(de, 'sleep', lambda *args, **kwargs: None):
        task.execute_boss()
    return task


def test_boss_gather_keeps_waiting_normally():
    """正常集结(180 秒内): 照旧等, 不许在集结阶段开战斗"""
    task = run_execute_boss(escalate_after=None)

    assert task.run_battle_calls == 0  # 没有误开"战斗"
    assert task.gather_seen >= 2  # 确实在等集结
    assert task.done_checks > 3  # 主循环转了多轮才被收尾


def test_boss_gather_escalates_to_prepare_page_after_timeout():
    """两个元素同时可见超过 180 秒: 升级去处理准备页(而不是等到 480 秒卡死)"""
    task = run_execute_boss(escalate_after=2)

    assert task.run_battle_calls == 1  # 升级后走了一次通用战斗流程
    assert task.gather_seen >= 1  # 升级前先按老规矩等过一次
