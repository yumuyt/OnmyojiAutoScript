# -*- coding: utf-8 -*-
"""
"准备"阶段的补点回归测试

背景(2026-10-01 06:26 / 06:29 两次地域鬼王 GameStuckError + 重启游戏):
battle_before 的 5 秒预算从进函数就起表，current_count == 1 时切预设要吃掉近 4 秒，
于是只剩一次点"准备"的机会；这一次被游戏在过场动画里吞掉后，
green_mark 里"等准备消失"的循环既不补点也没有超时，只能等 60 秒的卡死检测。
"""
import time
from unittest import mock

from tasks.Component.GeneralBattle import general_battle as gb
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets


class FakeDevice:
    image = None

    def __init__(self):
        self.clicks = []

    def click(self, x=None, y=None, control_check=True, control_name='Click'):
        self.clicks.append((x, y, control_name))


class FakeBattle:
    """只实现 press_prepare / battle_before 用到的接口，逻辑走真代码"""

    PREPARE_CLICK_INTERVAL = (0.0, 0.0)  # 测试里去掉随机等待，random.uniform(0, 0) == 0.0
    PREPARE_CLICK_LIMIT = gb.GeneralBattle.PREPARE_CLICK_LIMIT
    PREPARE_CLICK_WAIT = gb.GeneralBattle.PREPARE_CLICK_WAIT
    I_PREPARE_HIGHLIGHT = GeneralBattleAssets.I_PREPARE_HIGHLIGHT
    I_DISABLE_7DAYS_DIFF_SOUL = GeneralBattleAssets.I_DISABLE_7DAYS_DIFF_SOUL
    I_CONFIRM_CLOSE_DIFF_SOUL = GeneralBattleAssets.I_CONFIRM_CLOSE_DIFF_SOUL

    press_prepare = gb.GeneralBattle.press_prepare
    prepare_click_reset = gb.GeneralBattle.prepare_click_reset
    battle_before = gb.GeneralBattle.battle_before

    def __init__(self, button_lit=True, presses_to_start=None, lock_team=False):
        self.device = FakeDevice()
        self._prepare_click_count = 0
        self._prepare_next_click = 0.0
        self.button_lit = button_lit
        # 点到第几次才真正进入战斗(读真实的补点计数, 所以测的是真逻辑)
        self.presses_to_start = presses_to_start
        self.current_count = 1
        self.lock_team = lock_team
        self.setup_calls = 0
        self.screenshots = 0

    # —— press_prepare 需要的接口 ——
    def appear(self, target, interval=None, threshold=None):
        return self.button_lit

    # —— battle_before 需要的接口 ——
    def screenshot(self):
        self.screenshots += 1

    def is_in_prepare(self, is_screenshot=True):
        return True

    def is_in_real_battle(self, is_screenshot=True):
        if self.presses_to_start is None:
            return False
        return self._prepare_click_count >= self.presses_to_start

    def appear_then_click(self, target, interval=None, threshold=None, **kwargs):
        return False

    def switch_preset_team(self, *args, **kwargs):
        self.setup_calls += 1
        time.sleep(0.3)  # 模拟"切预设要花时间"

    def check_and_open_buff(self, *args, **kwargs):
        pass


def make_config(lock_team=False):
    class FakeConfig:
        lock_team_enable = lock_team
        preset_enable = True
        preset_group = 1
        preset_team = 3

    return FakeConfig()


# --------------------------------------------------------------------------- #
# press_prepare
# --------------------------------------------------------------------------- #
def test_press_prepare_clicks_once_and_lands_inside_button():
    fake = FakeBattle(button_lit=True)
    fake.PREPARE_CLICK_INTERVAL = (0.0, 0.0)

    assert gb.GeneralBattle.press_prepare(fake) is True
    assert fake._prepare_click_count == 1
    assert len(fake.device.clicks) == 1

    x, y, name = fake.device.clicks[0]
    bx, by, bw, bh = GeneralBattleAssets.I_PREPARE_HIGHLIGHT.roi_front
    assert bx <= x <= bx + bw and by <= y <= by + bh  # 落点仍在按钮范围内
    assert name == 'GB_PREPARE_HIGHLIGHT'


def test_press_prepare_skips_when_button_dark():
    fake = FakeBattle(button_lit=False)

    assert gb.GeneralBattle.press_prepare(fake) is False
    assert fake._prepare_click_count == 0
    assert fake.device.clicks == []


def test_press_prepare_throttles_by_interval():
    fake = FakeBattle(button_lit=True)
    fake.PREPARE_CLICK_INTERVAL = (1.0, 1.6)

    assert gb.GeneralBattle.press_prepare(fake) is True
    # 间隔没到就再点 = 连点, 必须被拦下
    assert gb.GeneralBattle.press_prepare(fake) is False
    assert len(fake.device.clicks) == 1


def test_press_prepare_stops_at_limit():
    fake = FakeBattle(button_lit=True)
    fake.PREPARE_CLICK_INTERVAL = (0.0, 0.0)
    fake.PREPARE_CLICK_LIMIT = 6

    for _ in range(20):
        gb.GeneralBattle.press_prepare(fake)

    assert fake._prepare_click_count == 6
    assert len(fake.device.clicks) == 6  # 到上限后只等不点, 不会撞上连点保护(10 次)


def test_prepare_click_reset_clears_budget():
    fake = FakeBattle(button_lit=True)
    fake.PREPARE_CLICK_INTERVAL = (0.0, 0.0)
    fake.PREPARE_CLICK_LIMIT = 2

    gb.GeneralBattle.press_prepare(fake)
    gb.GeneralBattle.press_prepare(fake)
    assert gb.GeneralBattle.press_prepare(fake) is False

    gb.GeneralBattle.prepare_click_reset(fake)

    assert fake._prepare_click_count == 0
    assert gb.GeneralBattle.press_prepare(fake) is True


# --------------------------------------------------------------------------- #
# battle_before
# --------------------------------------------------------------------------- #
def test_battle_before_keeps_clicking_until_battle_starts():
    fake = FakeBattle(button_lit=True, presses_to_start=3)

    with mock.patch.object(gb, 'sleep', lambda *args, **kwargs: None):
        assert gb.GeneralBattle.battle_before(fake, None, make_config()) is True

    assert fake._prepare_click_count == 3


def test_battle_before_setup_time_does_not_eat_prepare_budget():
    """切阵容花掉的时间不能算进点"准备"的预算(这次卡死的根因)"""
    fake = FakeBattle(button_lit=True, presses_to_start=1)
    fake.PREPARE_CLICK_WAIT = 0.2  # 预算比切阵容的 0.3s 还短

    with mock.patch.object(gb, 'sleep', lambda *args, **kwargs: None):
        assert gb.GeneralBattle.battle_before(fake, None, make_config()) is True

    assert fake.setup_calls == 1
    assert fake._prepare_click_count == 1


def test_battle_before_gives_up_after_click_limit():
    fake = FakeBattle(button_lit=True, presses_to_start=None)
    fake.PREPARE_CLICK_LIMIT = 6

    with mock.patch.object(gb, 'sleep', lambda *args, **kwargs: None):
        assert gb.GeneralBattle.battle_before(fake, None, make_config()) is False

    assert fake._prepare_click_count == 6
    assert len(fake.device.clicks) == 6


def test_battle_before_lock_team_waits_without_clicking():
    fake = FakeBattle(button_lit=True, presses_to_start=None, lock_team=True)
    fake.PREPARE_CLICK_WAIT = 0.3  # 这里保留真实 sleep, 让等超时自然发生

    assert gb.GeneralBattle.battle_before(fake, None, make_config(lock_team=True)) is False
    assert fake._prepare_click_count == 0
    assert fake.device.clicks == []
