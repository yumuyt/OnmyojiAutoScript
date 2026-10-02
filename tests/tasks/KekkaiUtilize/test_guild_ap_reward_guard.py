# -*- coding: utf-8 -*-
"""寮体力收取被"获得奖励"面板卡死的回归测试。

现场证据: log/error/1790892689087/2026-10-02_06-11-29-073276.png
          (阴阳寮主界面 + "获得奖励 体力+15" 面板 + 体力道具详情 tooltip)
实测: ku_guild_ap.png 在 I_GUILD_AP.roi_back 内对面板中央的体力图标匹配 0.8238 >= 阈值 0.8,
      所以面板挂着的时候点"寮体力", 点的其实是面板里的体力图标, 只会弹出道具详情,
      面板再也点不掉。2026-10-02 06:11 OAS2 就是 KU_GUILD_AP / UI_UI_REWARD
      互点 6 次之后触发 GameTooManyClickError, 然后重启游戏。
"""
import tasks.KekkaiUtilize.script_task as kekkai_utilize
from tasks.KekkaiUtilize.script_task import ScriptTask


# 同一个按钮点满 10 次就会被判成连点并重启游戏(module/device/device.py: click_record_check)
DEVICE_CLICK_LIMIT = 10


class FakeDevice:
    def __init__(self):
        self.image = None

    def click(self, x, y, control_name=None):
        return None


def make_task(panel_up=False, ap_available=True, dismiss_after=1):
    """不带 config/device 的 ScriptTask 替身: 只留收取寮体力用到的那几个外设"""
    t = ScriptTask.__new__(ScriptTask)
    t.device = FakeDevice()
    t.interval_timer = {}
    t.panel_up = panel_up            # "获得奖励"面板是否挂在屏幕上
    t.ap_taken = not ap_available    # 寮体力图标是否已经被收掉
    t.dismiss_after = dismiss_after  # 第几次点"获得奖励"能把面板点掉
    t.reward_clicks = 0
    t.clicked = []                   # [(target, action, panel_up)]
    t.frames = 0

    def screenshot():
        t.frames += 1
        assert t.frames < 100, '界面没有变化, 点击死循环了'

    def appear(target, interval=None, threshold=None):
        if target is ScriptTask.I_UI_REWARD:
            return t.panel_up
        if target is ScriptTask.I_GUILD_AP:
            # 面板挂着的时候, 面板中央的体力图标也会被 I_GUILD_AP 匹配上(现场实测 0.8238)
            return t.panel_up or not t.ap_taken
        return False

    def appear_then_click(target, action=None, interval=None, threshold=None, duration=None):
        if not appear(target):
            return False
        t.clicked.append((target, action, t.panel_up))
        if target is ScriptTask.I_GUILD_AP:
            if t.panel_up:
                # 点到的是面板里的体力图标: 只弹道具详情, 别的什么都不会发生
                return True
            t.panel_up = True     # 收到体力, 弹出"获得奖励"面板
            t.ap_taken = True     # 真图标随之消失
        elif target is ScriptTask.I_UI_REWARD:
            t.reward_clicks += 1
            assert t.reward_clicks < DEVICE_CLICK_LIMIT, \
                f'同一个按钮点到了 {t.reward_clicks} 次, 会被判成连点并重启游戏'
            if t.reward_clicks >= t.dismiss_after:
                t.panel_up = False
        return True

    t.screenshot = screenshot
    t.appear = appear
    t.appear_then_click = appear_then_click
    return t


def _no_sleep(monkeypatch):
    monkeypatch.setattr(kekkai_utilize.time, 'sleep', lambda seconds: None)


def _ap_clicks(t):
    return [item for item in t.clicked if item[0] is ScriptTask.I_GUILD_AP]


def test_guild_ap_is_never_clicked_while_reward_panel_is_up(monkeypatch):
    """面板挂在屏幕上时不许点寮体力, 面板点掉之后才只收一次"""
    _no_sleep(monkeypatch)
    t = make_task(panel_up=True, dismiss_after=2)

    assert t.check_guild_ap_or_assets() is True

    # 每一次点寮体力, 面板都必须是已经消失的状态
    assert [panel for _, _, panel in _ap_clicks(t)] == [False]
    assert len(_ap_clicks(t)) == 1
    assert t.clicked[0][0] is ScriptTask.I_UI_REWARD


def test_undismissable_reward_panel_gives_up_without_hammering(monkeypatch):
    """面板点不掉时收手, 而不是一直互点到设备判连点为止"""
    _no_sleep(monkeypatch)
    t = make_task(panel_up=True, dismiss_after=10 ** 9)

    assert t.check_guild_ap_or_assets() is False

    assert _ap_clicks(t) == []
    # 默认最多点 4 次"获得奖励", 离设备的 10 次上限还有余量
    assert t.reward_clicks == 4
    assert t.frames < 20


def test_dismiss_reward_panel_click_budget(monkeypatch):
    _no_sleep(monkeypatch)
    t = make_task(panel_up=True, dismiss_after=10 ** 9)

    assert t.dismiss_reward_panel(timeout=5, max_click=2) is False
    assert t.reward_clicks == 2


def test_reward_panel_is_dismissed_and_ap_collected_once(monkeypatch):
    """正常收体力: 面板一次点掉, 寮体力只点一次"""
    _no_sleep(monkeypatch)
    t = make_task(panel_up=False, dismiss_after=1)

    assert t.check_guild_ap_or_assets() is True

    assert [target for target, _, _ in t.clicked] == [ScriptTask.I_GUILD_AP,
                                                      ScriptTask.I_UI_REWARD]
    assert t.clicked[1][1] is ScriptTask.C_UI_REWARD
