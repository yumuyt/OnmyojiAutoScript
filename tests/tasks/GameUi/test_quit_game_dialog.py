# -*- coding: utf-8 -*-
"""庭院上"退出游戏"确认弹窗把导航点死的回归测试。

现场证据: log/error/1790924859236/2026-10-02_15-07-39-096801.png
          (庭院 + "退出游戏 / 确定要退出游戏? 取消 确认" 模态弹窗)
当时的日志: 14:59 脚本停在庭院等调度, 15:05 RyouToppa 起跑, ui_goto 认得 page_main,
          于是反复点"探索"灯(约 670,156), 弹窗是模态的所以页面上什么都没发生,
          60s 后 "Cannot goto page[page_kekkai_toppa], timeout[60s] reached" -> GameStuckError。

实测(用仓库里真实的 RuleImage 素材回放这张截图):
  I_CHECK_MAIN 仍然命中 0.9939 -> 旧代码才会认为"我在庭院, 继续点";
  I_QUIT_GAME_DIALOG 命中, I_QUIT_GAME_CANCEL 命中(点击坐标 791,438, 离"确认"的 880~921 很远);
  两张没有该弹窗的真实截图(育成候补 / 获得奖励)上两个素材都不命中。
"""
import types
from types import SimpleNamespace

import pytest

from module.exception import GamePageUnknownError
from tasks.GameUi.assets import GameUiAssets as G
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_exploration, page_main


class CountingTimer:
    """照抄真实 Timer 的两个关键行为, 再把 10s 看门狗换成"循环几次就到点"

    真实 `Timer(limit)` 不 start 时 `_current` 就是 0, `reached()` 立刻为 True ——
    限流计时器第一次用必须能立刻点。看门狗那个 (limit=10) 则换成几次就到点, 免得测试真等 10 秒。
    """

    def __init__(self, limit, count=0):
        self.limit = limit
        self.left = 6 if limit >= 10 else 0

    def start(self):
        return self

    def reset(self):
        self.left = 6 if self.limit >= 10 else 0
        return self

    def reached(self):
        if self.left > 0:
            self.left -= 1
            return False
        return True


def make_ui(dialog_up=True, dismissible=True, page='page_main'):
    """不带 config/device 的 GameUi 替身: 只留取当前页面这一路用到的外设"""
    ui = GameUi.__new__(GameUi)
    ui.device = SimpleNamespace(image=None,
                                app_is_running=lambda: True,
                                get_orientation=lambda: None,
                                screenshot=lambda *a, **k: None)
    ui.config = SimpleNamespace(script=SimpleNamespace(
        device=SimpleNamespace(control_method='minitouch', screenshot_method='scrcpy')))
    ui.interval_timer = {}
    ui.dialog_up = dialog_up          # "退出游戏"弹窗是否挂在屏幕上
    ui.dismissible = dismissible      # 点"取消"能不能把弹窗点掉
    ui.current_page = page
    ui.clicks = []                    # [(target, dialog_up_when_clicked)]
    ui.events = []                    # 按顺序记录, 用来验证"先点掉弹窗再判页面"
    ui.frame_dialog_up = None         # 判定当前页面时, 那一帧弹窗还在不在

    def maybe_screenshot(soft_skip=False):
        ui.frame_dialog_up = ui.dialog_up
        ui.events.append(('screenshot', ui.dialog_up))
        ui.device.image = object()
        return ui.device.image

    def appear(target, interval=None, threshold=None):
        if target is G.I_QUIT_GAME_DIALOG:
            return ui.dialog_up
        if target is G.I_QUIT_GAME_CANCEL:
            return ui.dialog_up
        return False

    def appear_then_click(target, action=None, interval=None, threshold=None, duration=None):
        if not appear(target):
            return False
        ui.clicks.append((target, ui.dialog_up))
        if target is G.I_QUIT_GAME_CANCEL:
            ui.events.append(('cancel_click', ui.dialog_up))
            if ui.dismissible:
                ui.dialog_up = False
        return True

    def ui_page_appear(page, skip_first_screenshot=True, interval=None):
        ui.events.append(('page_appear', page.name, ui.dialog_up))
        return page.name == ui.current_page

    ui.maybe_screenshot = maybe_screenshot
    ui.appear = appear
    ui.appear_then_click = appear_then_click
    ui.ui_page_appear = ui_page_appear
    ui.click = lambda target=None, interval=None: ui.clicks.append((target, ui.dialog_up)) or True
    ui.try_close_unknown_page = lambda skip_screenshot=True: False
    return ui


def _cancel_clicks(ui):
    return [item for item in ui.clicks if item[0] is G.I_QUIT_GAME_CANCEL]


def test_page_is_returned_only_after_the_dialog_is_dismissed(monkeypatch):
    """"退出游戏"弹窗压着时, 取当前页面必须先把弹窗点掉, 不能把弹窗背后的庭院直接返回"""
    monkeypatch.setattr('tasks.GameUi.game_ui.Timer', CountingTimer)
    ui = make_ui(dialog_up=True, dismissible=True)

    page = ui.ui_get_current_page()

    assert page is page_main
    assert len(_cancel_clicks(ui)) == 1
    # 判定出 page_main 的那一帧, 弹窗必须已经消失
    assert ui.frame_dialog_up is False
    # 顺序: 先点"取消", 再判页面
    assert [e[0] for e in ui.events if e[0] in ('cancel_click', 'page_appear')][:2] == \
           ['cancel_click', 'page_appear']


def test_no_dialog_means_no_cancel_click(monkeypatch):
    monkeypatch.setattr('tasks.GameUi.game_ui.Timer', CountingTimer)
    ui = make_ui(dialog_up=False)

    assert ui.ui_get_current_page() is page_main

    assert _cancel_clicks(ui) == []
    assert ui.frame_dialog_up is False


def test_undismissable_dialog_gives_up_instead_of_spinning(monkeypatch):
    """弹窗点不掉时按超时收手(交给上层重启游戏), 而不是无限点下去"""
    monkeypatch.setattr('tasks.GameUi.game_ui.Timer', CountingTimer)
    ui = make_ui(dialog_up=True, dismissible=False)

    with pytest.raises(GamePageUnknownError):
        ui.ui_get_current_page()

    # 有上限: 看门狗到点前的那几次尝试, 而不是一直点
    assert 1 <= len(_cancel_clicks(ui)) <= 8


def test_cancel_is_only_clicked_when_the_title_matches():
    """"取消"素材单独命中(没有"退出游戏"标题)时不许点 —— 别把别的弹窗点歪"""
    ui = make_ui(dialog_up=False)
    ui.appear = lambda target, interval=None, threshold=None: target is G.I_QUIT_GAME_CANCEL
    clicked = []
    ui.appear_then_click = lambda target, action=None, interval=None, threshold=None, duration=None: \
        clicked.append(target) or True

    assert ui.try_close_blocking_dialog() is False
    assert clicked == []


def test_try_close_blocking_dialog_reports_the_click(monkeypatch):
    monkeypatch.setattr('tasks.GameUi.game_ui.Timer', CountingTimer)
    ui = make_ui(dialog_up=True, dismissible=True)

    assert ui.try_close_blocking_dialog() is True
    assert len(_cancel_clicks(ui)) == 1
    # 弹窗没了以后再问一次, 什么都不点
    assert ui.try_close_blocking_dialog() is False
    assert len(_cancel_clicks(ui)) == 1


def test_cancel_clicks_are_rate_limited(monkeypatch):
    """限流没到点就直接返回: 同一张弹窗点不掉时不许连着猛点(设备端 10 次判连点重启游戏)"""
    monkeypatch.setattr('tasks.GameUi.game_ui.Timer', CountingTimer)
    ui = make_ui(dialog_up=True, dismissible=False)
    ui._blocking_dialog_timer = SimpleNamespace(reached=lambda: False, reset=lambda: None)

    assert ui.try_close_blocking_dialog() is False
    assert _cancel_clicks(ui) == []
