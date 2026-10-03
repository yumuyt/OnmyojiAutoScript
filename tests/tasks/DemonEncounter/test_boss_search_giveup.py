# -*- coding: utf-8 -*-
"""
逢魔boss 搜索失败: 不抛错、不重启游戏, 走"重进地图 -> 最多3轮 -> 放弃本次并稍后重试"

背景(2026-10-03 17:08 oas1):
上游 dev 的 194a3eda 把 find_boss 改成"第一次没匹配上首领按钮就 raise GameStuckError",
但那个文件只 `from module.exception import TaskEnd` —— GameStuckError 根本没导入。
于是 raise 变成 NameError, 一路落到 script.py 的 `except Exception` -> exit(1),
整个 oas1 进程退出(本该只是"任务失败, 稍后重试")。

实机那一帧 I_DE_BOSS 只匹配到 0.7977(阈值 0.8), 所以不是素材坏了, 而是
"贴阈值 + 一次判死"的组合。现在的改法:
  1) 首领按钮没认出来不再判死, 交给每轮"重进逢魔地图清状态"的恢复逻辑;
  2) 3 轮都失败就放弃本次运行, 安排半小时后重试(逢魔 17:00-23:00 内还有机会),
     全程不抛错、不重启游戏;
  3) 素材侧: I_DE_BOSS 加了 ±25px 搜索余量、阈值 0.8 -> 0.75
     (实测崩溃那一帧 0.8468 过线, 19 张历史截图其它帧最高 0.2877)。
"""
from types import SimpleNamespace
from unittest import mock

import pytest

from module.exception import TaskEnd
from tasks.DemonEncounter import script_task as de
from tasks.DemonEncounter.assets import DemonEncounterAssets
from tasks.GlobalGame.assets import GlobalGameAssets


class StopAfterFindBoss(Exception):
    """find_boss 认到首领后, 用它把 execute_boss 从 enter_boss 里拉出来"""


class FakeBossTask:
    """只关心 execute_boss 里的 find_boss 分支"""

    execute_boss = de.ScriptTask.execute_boss
    best_demon_enable = False

    I_DE_BOSS = DemonEncounterAssets.I_DE_BOSS
    I_DE_BOSS_BEST = DemonEncounterAssets.I_DE_BOSS_BEST
    I_BOSS_FIRE = DemonEncounterAssets.I_BOSS_FIRE
    I_BEST_BOSS_FIRE = DemonEncounterAssets.I_BEST_BOSS_FIRE
    I_JADE_50 = DemonEncounterAssets.I_JADE_50
    I_DE_BOX_CENTER = DemonEncounterAssets.I_DE_BOX_CENTER
    I_DE_LOCATION = DemonEncounterAssets.I_DE_LOCATION
    C_DM_BOSS_CLICK = DemonEncounterAssets.C_DM_BOSS_CLICK
    I_UI_BACK_RED = GlobalGameAssets.I_UI_BACK_RED

    def __init__(self, search_hit_at=0):
        """
        :param search_hit_at: 第几次点"首领"按钮才认出来, 0 表示一直认不出来
        """
        self.device = SimpleNamespace(image=None, click_record_clear=lambda: None)
        self.search_hit_at = search_hit_at
        self.search_attempts = 0
        self.search_hits = 0
        self.ui_goto_calls = 0
        self.set_next_run_calls = []
        self.boss_found = False

    # —— find_boss / enter_boss 需要的接口 ——
    def screenshot(self):
        if self.boss_found:
            raise StopAfterFindBoss()  # 已经证明"能认到首领", 后面的流程与本测试无关

    def appear(self, target, threshold=None, interval=None, **kwargs):
        if target is self.I_BOSS_FIRE or target is self.I_BEST_BOSS_FIRE:
            return self.search_hits > 0  # 点中首领之后才算"集结挑战出现"
        return False  # 中央宝箱展示 / 50勾玉 / 返回键 等一律不出现

    def appear_then_click(self, target, interval=None, **kwargs):
        if target is self.I_DE_BOSS or target is self.I_DE_BOSS_BEST:
            self.search_attempts += 1
            if self.search_hit_at and self.search_attempts >= self.search_hit_at:
                self.search_hits += 1
                self.boss_found = True
                return True
            return False  # 这次没认出来 -> 旧代码在这里 raise, 现在应该只是重进地图
        return False

    def click(self, *args, **kwargs):
        return True

    def ui_goto_page(self, *args, **kwargs):
        self.ui_goto_calls += 1
        return True

    def set_next_run(self, **kwargs):
        self.set_next_run_calls.append(kwargs)

    def run_general_battle(self, *args, **kwargs):
        return True


def run_execute_boss(search_hit_at=0):
    task = FakeBossTask(search_hit_at=search_hit_at)
    with mock.patch.object(de.time, 'sleep', lambda *args, **kwargs: None), \
            mock.patch.object(de, 'sleep', lambda *args, **kwargs: None):
        if search_hit_at:
            with pytest.raises(StopAfterFindBoss):
                task.execute_boss()
        else:
            with pytest.raises(TaskEnd):  # 放弃本次: 只 TaskEnd, 不能是 GameStuckError/NameError
                task.execute_boss()
    return task


def test_boss_search_miss_recovers_by_reentering_map():
    """首领按钮第一次没认出来: 不判死, 重进地图再找一轮就认到了"""
    task = run_execute_boss(search_hit_at=2)  # 第 2 次尝试(=第 2 轮)认出来

    assert task.ui_goto_calls == 2  # 只重进了一轮地图
    assert task.set_next_run_calls == []  # 认到了, 不该安排"失败重试"


def test_boss_search_giveup_is_graceful_and_retries_in_30min():
    """3 轮都找不到: 每轮都重进地图, 最后放弃本次并在半小时后重试(不抛错/不重启)"""
    task = run_execute_boss(search_hit_at=0)

    assert task.ui_goto_calls == 6  # 3 轮 × (重进逢魔 + 重进现世逢魔)
    assert len(task.set_next_run_calls) == 1
    call = task.set_next_run_calls[0]
    assert call['success'] is False
    assert call['server'] is False  # 否则会被 server_update 改写成"明天 17:05"
    assert 'target' in call  # +30 分钟重试
