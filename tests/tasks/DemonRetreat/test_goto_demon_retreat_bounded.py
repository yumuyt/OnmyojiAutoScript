# -*- coding: utf-8 -*-
"""
B 修复: goto_demon_retreat 的循环必须有界

背景(2026-10-03 19:20~20:15, oas1/oas2 各两次 GameStuckError):
首领退治的"伤害排名"面板关不掉(关面板素材 I_DEMON_BACK_CHECK 只有 0.6969/阈值 0.7),
于是每轮都判"Enter demon_retreat false"; 而循环守卫 goto_demon_retreat_num 只在
I_HUNT 出现时才 +1, 面板一挡住 I_HUNT 就再也不出现 -> 计数器永远是 1 -> 无限循环:
58~83 轮 × (sleep3+sleep20) = 22~32 分钟, 全程零点击, 最后被 device 的
"60 秒 + 60 张截图无点击"卡死检测打断。

现在: 轮次(>5) + 限时(90s) 双重兜底, 到点 return False -> run() 走
plan_after_failure() 正常排期, 不会再靠卡死检测兜底。
另外关面板改走 back_from_rank_panel(): 优先通用返回键 I_BACK_Y(实测 0.9670)。
"""
from types import SimpleNamespace
from unittest import mock

from tasks.DemonRetreat import script_task as de
from tasks.DemonRetreat.assets import DemonRetreatAssets
from tasks.GameUi.assets import GameUiAssets


class FakeRetreatTask:
    """只跑 goto_demon_retreat 的循环, 停在"伤害排名面板"上"""

    goto_demon_retreat = de.ScriptTask.goto_demon_retreat
    back_from_rank_panel = de.ScriptTask.back_from_rank_panel

    I_SHRINE = DemonRetreatAssets.I_SHRINE
    I_HUNT = DemonRetreatAssets.I_HUNT
    I_HUNT_CHECK = DemonRetreatAssets.I_HUNT_CHECK
    I_QUIT_BACK = DemonRetreatAssets.I_QUIT_BACK
    I_REWARD_ALL = DemonRetreatAssets.I_REWARD_ALL
    I_RANK_LSIT = DemonRetreatAssets.I_RANK_LSIT
    I_DEMON_GATHER = DemonRetreatAssets.I_DEMON_GATHER
    I_DEMON_BACK_CHECK = DemonRetreatAssets.I_DEMON_BACK_CHECK
    I_BACK_Y = GameUiAssets.I_BACK_Y

    def __init__(self):
        self.rounds = 0          # I_RANK_LSIT 被看到的次数 = 循环轮数
        self.targets = []        # 记录尝试点击过的素材对象

    def ui_get_current_page(self):
        return True

    def ui_goto(self, *args, **kwargs):
        return True

    def screenshot(self):
        pass

    def is_in_prepare(self, *args, **kwargs):
        return False

    def appear(self, target, threshold=None, interval=None, **kwargs):
        if target is self.I_RANK_LSIT:
            self.rounds += 1
            return True          # 面板一直在, 一直关不掉(旧代码就在这里无限循环)
        return False

    def appear_then_click(self, target, interval=None, **kwargs):
        self.targets.append(target)
        return target is self.I_BACK_Y   # 只有通用返回键认得出来


def run_goto_demon_retreat():
    task = FakeRetreatTask()
    # NOTE 本模块里 `time` 是 datetime.time(`from datetime import ... time`),
    #      所以只能 patch 它 `from time import sleep` 进来的那个 sleep。
    with mock.patch.object(de, 'sleep', lambda *a, **k: None):
        result = task.goto_demon_retreat()
    return task, result


def test_goto_demon_retreat_is_bounded():
    """面板一直关不掉: 循环必须有界(<=5 轮)并返回 False, 不能无限转"""
    task, result = run_goto_demon_retreat()

    assert result is False
    assert task.rounds <= 5, f'循环没有被兜底住, 转了 {task.rounds} 轮'
    assert task.rounds >= 2, '应该先重试几轮再放弃'


def test_goto_demon_retreat_clicks_generic_back_key():
    """关面板要走通用返回键(旧素材 I_DEMON_BACK_CHECK 0.6969 根本点不到)"""
    task, _ = run_goto_demon_retreat()

    assert task.targets.count(GameUiAssets.I_BACK_Y) >= 2, \
        f'没有用通用返回键关面板: {[t.name for t in task.targets[:6]]}'
