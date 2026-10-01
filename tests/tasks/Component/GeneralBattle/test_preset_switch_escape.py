# -*- coding: utf-8 -*-
"""
switch_preset_team 的"战斗已开打 / 超时"两个出口的回归测试

背景(2026-10-01 17:07 / 17:10 oas2 两次 GameStuckError, 每次都会重启整个游戏客户端,
把正在打的逢魔boss战斗打废):
共斗(逢魔boss)战斗会在脚本切阵容的这段时间里自己开打, 左下角从"预设"变成"自动/手动",
O_PRESET / O_PRESET_FULL 的 keyword('预' / '预设')永远匹配不上 —— 老代码这个 while
既发不出点击也没有出口, 空转到 60 秒零点击被 device 判卡死。

现场截图实测(见 _diag/demon_prepare_fix_check.py, 阈值 0.8):
  I_BATTLE_INFO        0.992 / 0.993  -> 命中(新出口能认出来)
  I_PRESET_ENSURE      0.238 / 0.234  -> 不命中(老循环必然空转)
  I_PRESENT_LESS_THAN_5 0.10 / 0.076  -> 不命中
  I_WIN / I_FALSE / I_REWARD / I_DE_WIN 全部不命中(新出口不误报)
"""
from unittest import mock

import numpy as np

from tasks.Component.GeneralBattle import general_battle as gb
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets


class FakeDevice:
    image = np.zeros((720, 1280, 3), dtype=np.uint8)

    def __init__(self):
        self.clicks = []

    def click(self, x=None, y=None, control_check=True, control_name='Click'):
        self.clicks.append((x, y, control_name))


class FakePresetBattle:
    """只实现 switch_preset_team 用到的接口, 判定逻辑走真代码"""

    I_PRESET_ENSURE = GeneralBattleAssets.I_PRESET_ENSURE
    I_PRESENT_LESS_THAN_5 = GeneralBattleAssets.I_PRESENT_LESS_THAN_5
    I_PRESET = GeneralBattleAssets.I_PRESET
    I_PRESET_WIT_NUMBER = GeneralBattleAssets.I_PRESET_WIT_NUMBER
    I_DE_WIN = GeneralBattleAssets.I_DE_WIN
    I_WIN = GeneralBattleAssets.I_WIN
    I_FALSE = GeneralBattleAssets.I_FALSE
    I_REWARD = GeneralBattleAssets.I_REWARD
    O_PRESET = GeneralBattleAssets.O_PRESET
    O_PRESET_FULL = GeneralBattleAssets.O_PRESET_FULL
    C_PRESET_GROUP_1 = GeneralBattleAssets.C_PRESET_GROUP_1
    C_PRESET_GROUP_2 = GeneralBattleAssets.C_PRESET_GROUP_2
    C_PRESET_GROUP_3 = GeneralBattleAssets.C_PRESET_GROUP_3
    C_PRESET_TEAM_1 = GeneralBattleAssets.C_PRESET_TEAM_1
    C_PRESET_TEAM_2 = GeneralBattleAssets.C_PRESET_TEAM_2
    C_PRESET_TEAM_3 = GeneralBattleAssets.C_PRESET_TEAM_3

    switch_preset_team = gb.GeneralBattle.switch_preset_team

    def __init__(self, real_battle=False, ensure_visible=False, preset_template=False):
        self.device = FakeDevice()
        self.real_battle = real_battle
        self.ensure_visible = ensure_visible  # 预设确认面板在不在
        self.preset_template = preset_template  # 图片模板能不能匹配到"预设"按钮
        self.screenshots = 0
        self.ocr_calls = 0

    def screenshot(self):
        self.screenshots += 1

    def is_in_real_battle(self, is_screenshot=True):
        return self.real_battle

    def appear(self, target, threshold=None, interval=None, **kwargs):
        if target is self.I_PRESET_ENSURE:
            return self.ensure_visible
        return False

    def appear_then_click(self, target, threshold=None, interval=None, **kwargs):
        if target is self.I_PRESET:
            if self.preset_template and not self.ensure_visible:
                self.ensure_visible = True  # 点开预设面板
                return True
            return False
        if target is self.I_PRESET_ENSURE:
            self.ensure_visible = False  # 点掉确认按钮, 面板收起
            return True
        return False

    def ocr_appear(self, target, interval=None, exact=False):
        self.ocr_calls += 1
        # 图片模板匹配不到时靠 OCR 兜底(oas1 极逢魔就是这条路走通的)
        return not self.ensure_visible

    def click(self, target=None, interval=None, **kwargs):
        if target is self.O_PRESET or target is self.O_PRESET_FULL:
            self.ensure_visible = True  # OCR 点到"预设" -> 面板出现
        if target is not None:
            self.device.clicks.append((getattr(target, 'name', str(target)), target))
        return True

    def wait_until_appear(self, target, wait_time=None):
        return self.ensure_visible


class ReachedTimer:
    """让 12 秒的预设面板超时计时器"立刻到达" """

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        return self

    def reached(self):
        return True


class NeverReachedTimer:
    """正常路径用: 12 秒超时永远不到(等价于"预设面板按时出现")"""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        return self

    def reached(self):
        return False


# --------------------------------------------------------------------------- #
# 新出口
# --------------------------------------------------------------------------- #
def test_switch_preset_aborts_when_battle_already_started():
    """oas2 现场: 切阵容时战斗已经开打 -> 一眼退出, 不再空转到 60 秒被判卡死"""
    fake = FakePresetBattle(real_battle=True, ensure_visible=False)

    assert gb.GeneralBattle.switch_preset_team(fake, True, 1, 3) is None
    assert fake.screenshots == 1  # 一轮就退出, 不会 60 秒零点击
    assert fake.device.clicks == []  # 战斗界面上不乱点
    assert fake.ocr_calls == 0  # 连 OCR 都不做


def test_switch_preset_aborts_on_timeout():
    """预设面板迟迟不出现(12s) -> 放弃切阵容而不是空转"""
    fake = FakePresetBattle(real_battle=False, ensure_visible=False)

    with mock.patch.object(gb, 'Timer', ReachedTimer):
        assert gb.GeneralBattle.switch_preset_team(fake, True, 1, 3) is None

    assert fake.device.clicks == []


# --------------------------------------------------------------------------- #
# 回归: 新出口不能误伤正常路径
# --------------------------------------------------------------------------- #
def test_switch_preset_still_switches_on_normal_prepare_page():
    """正常准备页(战斗没开打): 必须照旧点开预设面板并确认"""
    fake = FakePresetBattle(real_battle=False, ensure_visible=False, preset_template=False)

    with mock.patch.object(gb, 'Timer', NeverReachedTimer), \
            mock.patch.object(gb.time, 'sleep', lambda *args, **kwargs: None):
        assert gb.GeneralBattle.switch_preset_team(fake, True, 1, 3) is None

    clicked = [name for name, _ in fake.device.clicks]
    # 预设组是"颜色不对才点", 全黑测试图上颜色匹配不上 -> 只断言必点的预设队和确认
    assert 'preset_team_3' in clicked  # 选了预设队
    assert fake.ensure_visible is False  # 确认面板被点掉了
    assert fake.ocr_calls > 0  # 真走了"OCR 找预设按钮"的流程(图片模板没命中)


# --------------------------------------------------------------------------- #
# 兜底补点用的 press_prepare(ignore_budget=True)
# --------------------------------------------------------------------------- #
def test_press_prepare_rescue_ignores_battle_before_budget():
    """battle_wait 的兜底补点要能突破 battle_before 的 6 次预算, 否则救不回准备页"""

    class FakePrepare(FakePresetBattle):
        PREPARE_CLICK_INTERVAL = (0.0, 0.0)
        PREPARE_CLICK_LIMIT = 1
        I_PREPARE_HIGHLIGHT = GeneralBattleAssets.I_PREPARE_HIGHLIGHT
        press_prepare = gb.GeneralBattle.press_prepare

    fake = FakePrepare()
    fake._prepare_click_count = 0
    fake._prepare_next_click = 0.0
    fake.appear = lambda target, **kwargs: True  # 准备按钮亮着

    assert gb.GeneralBattle.press_prepare(fake) is True  # 用掉预算内的 1 次
    assert gb.GeneralBattle.press_prepare(fake) is False  # 预算用完就不再点
    assert gb.GeneralBattle.press_prepare(fake, ignore_budget=True) is True  # 兜底可以突破
    assert len(fake.device.clicks) == 2
