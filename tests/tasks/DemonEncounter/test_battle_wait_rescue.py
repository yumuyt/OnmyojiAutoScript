# -*- coding: utf-8 -*-
"""
逢魔(及通用)战斗 battle_wait 阶段"准备"兜底补点的回归测试

背景(2026-10-01 17:11 oas1 极逢魔):
battle_before 的 5 秒预算被切阵容吃掉 4 秒, 唯一一次点"准备"落在预设面板收起动画里
被游戏吞掉, 之后 battle_wait 只认 胜利/失败/奖励, 5 分 20 秒一次都没点 —— 画面停在
准备界面, 而且加了 BATTLE_STATUS_S(480 秒长卡死), 连报错都没有, 只能人工点。

所以 battle_wait 里加了一小笔独立预算(battle_before 的 6 次用完也能继续),
自己有次数上限, 只在"没有胜利/失败/奖励"且"准备按钮还亮着"时才补点。
"""
from types import SimpleNamespace
from unittest import mock

from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.DemonEncounter import script_task as de


class RescueTimer:
    """"先给游戏 8 秒"的计时器算到达; 120 秒的兜底窗口默认算没到"""

    window_reached = False

    def __init__(self, limit, count=0):
        self.limit = limit

    def start(self):
        return self

    def reached(self):
        if self.limit == 120:
            return RescueTimer.window_reached
        return self.limit == 8


class FakeBattleWaitTask:
    battle_wait = de.ScriptTask.battle_wait
    PREPARE_RESCUE_CLICK_LIMIT = de.ScriptTask.PREPARE_RESCUE_CLICK_LIMIT
    PREPARE_RESCUE_WINDOW = de.ScriptTask.PREPARE_RESCUE_WINDOW

    I_DE_WIN = GeneralBattleAssets.I_DE_WIN
    I_WIN = GeneralBattleAssets.I_WIN
    I_REWARD = GeneralBattleAssets.I_REWARD
    I_FALSE = GeneralBattleAssets.I_FALSE

    def __init__(self, reward_after_iterations=None):
        self.device = SimpleNamespace(
            stuck_record_add=lambda button: None,
            click_record_clear=lambda: None,
            stuck_timer_long=None,
        )
        self.iterations = 0
        self.presses = 0
        self.ignore_budget_flags = []
        self.reward_after_iterations = reward_after_iterations

    def screenshot(self):
        self.iterations += 1

    def appear(self, target, threshold=None, interval=None, **kwargs):
        if target is self.I_REWARD:
            if self.reward_after_iterations is not None:
                return self.iterations >= self.reward_after_iterations
            # 兜底补点点满预算之后才出结算, 保证测的是"补点次数"
            return self.presses >= self.PREPARE_RESCUE_CLICK_LIMIT
        return False

    def appear_then_click(self, *args, **kwargs):
        return False

    def press_prepare(self, ignore_budget=False):
        self.presses += 1
        self.ignore_budget_flags.append(ignore_budget)
        return True

    def ui_click_until_disappear(self, *args, **kwargs):
        pass


def run_battle_wait(task):
    with mock.patch.object(de, 'Timer', RescueTimer):
        return task.battle_wait(False)


def test_battle_wait_rescues_prepare_until_budget_is_used_up():
    """停在准备页时, battle_wait 要用自己的预算继续补点"准备"(突破 battle_before 的 6 次)"""
    RescueTimer.window_reached = False
    task = FakeBattleWaitTask()

    assert run_battle_wait(task) is True  # 最后靠结算退出, 而不是卡到 480 秒
    assert task.presses == task.PREPARE_RESCUE_CLICK_LIMIT
    assert all(task.ignore_budget_flags)  # 全部走 ignore_budget=True


def test_battle_wait_does_not_rescue_after_window():
    """超过兜底窗口(120 秒)就不再补点, 免得长战斗里乱点"""
    RescueTimer.window_reached = True
    task = FakeBattleWaitTask(reward_after_iterations=5)

    assert run_battle_wait(task) is True
    assert task.presses == 0
