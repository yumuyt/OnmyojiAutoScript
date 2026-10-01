# -*- coding: utf-8 -*-
"""道馆结算门控 (2026-10-01 19:10 事故) 的回归测试。

游戏规则: 道馆攻破结算页出现之前主动退出道馆 -> 本次突破没有任何奖励;
          结算页出现之后再退出则奖励照发。
现场证据: log/error/1790853050656/2026-10-01_19-10-50-605245.png
          (寮境 + "退出后将无法领取本次道馆突破奖励, 确认退出?" 弹窗, 右下角"挑战"按钮被挡住)
"""
import re
import types
from datetime import datetime, timedelta
from types import SimpleNamespace

from tasks.Dokan.dokan_scene import DokanScene
from tasks.Dokan.script_task import ScriptTask


def _fake_appear(self, target, interval=None, threshold=None):
    return target in self._appear_set


def _fake_remain(self):
    text = self.O_DOKAN_ATTACK_REMAIN.detect_text(self.device.image)
    match = re.search(r'(\d{1,2})\s*[:：]\s*(\d{2})', (text or '').replace(' ', ''))
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def make_task(appear_set=(), countdown='剩余突破时间14:38'):
    """不带 config/device 的 ScriptTask 替身: 只留结算门控用到的那几个外设"""
    t = ScriptTask.__new__(ScriptTask)
    t._appear_set = set(appear_set)
    t.clicked = []
    t.interval_timer = {}
    t.device = SimpleNamespace(image=None, screenshot=lambda *a, **k: None)
    t.O_DOKAN_ATTACK_REMAIN = SimpleNamespace(detect_text=lambda image: countdown)
    t.dokan_joined = False
    t.dokan_settled = False
    t._remain_count_updated = False
    t._settled_page_clicks = 0
    t._settlement_deadline = None
    t._settlement_wait_start = None
    t._settlement_wait_last_log = None
    t.click = lambda target=None, interval=None: t.clicked.append(target) or True
    t.screenshot = lambda: None
    t.wait_until_appear = lambda *a, **k: True
    t.ui_click_until_disappear = lambda *a, **k: t.clicked.append(a[0]) or True
    t.appear = types.MethodType(_fake_appear, t)
    t.dokan_remain_seconds = types.MethodType(_fake_remain, t)
    return t


def test_exit_allowed_truth_table():
    t = make_task()
    # 只在道馆地图上找馆: 没有奖励可丢, 可以退
    assert t.exit_allowed() is True

    # 人在道馆里、还没结算: 一律不准主动退出
    t.dokan_joined, t.dokan_settled, t._settlement_deadline = True, False, None
    assert t.exit_allowed() is False

    t._settlement_deadline = datetime.now() + timedelta(minutes=5)
    assert t.exit_allowed() is False

    # 结算页出现过 -> 可以退
    t.dokan_settled = True
    assert t.exit_allowed() is True

    # 等结算超时(道馆活动时间早该走完) -> 允许退出
    t.dokan_settled = False
    t._settlement_deadline = datetime.now() - timedelta(seconds=1)
    assert t.exit_allowed() is True


def test_cancel_exit_dokan_clicks_the_red_cancel_button():
    t = make_task()
    t.cancel_exit_dokan()
    assert t.clicked == [ScriptTask.C_DOKAN_EXIT_CANCEL]
    # 2026-10-01 现场帧里红色"取消"按钮实测 x468~604 y396~452
    assert tuple(ScriptTask.C_DOKAN_EXIT_CANCEL.roi_front) == (468, 396, 136, 56)


def test_cancel_exit_dokan_caps_repeated_clicks():
    """同一个按钮点满 10 次会被 OAS 判成连点并重启游戏, 所以取消也要限次"""
    t = make_task()
    assert [t.cancel_exit_dokan() for _ in range(4)] == [True, True, True, False]
    assert len(t.clicked) == ScriptTask.EXIT_CANCEL_MAX


def test_note_scene_marks_joined_only_inside_a_dokan():
    t = make_task()
    t.note_scene(DokanScene.RYOU_DOKAN_SCENE_FINDING_DOKAN)
    assert t.dokan_joined is False
    t.note_scene(DokanScene.RYOU_DOKAN_SCENE_START_CHALLENGE)
    assert t.dokan_joined is True


def test_wait_settlement_tick_uses_countdown():
    t = make_task(countdown='剩余突破时间14:38')
    t.dokan_joined = True
    t.wait_settlement_tick()
    remain = (t._settlement_deadline - datetime.now()).total_seconds()
    assert 870 + 360 <= remain <= 880 + 360  # 878s + 6 分钟宽限
    assert t.exit_allowed() is False


def test_wait_settlement_tick_hard_cap_without_countdown():
    t = make_task(countdown='')
    t.dokan_joined = True
    assert t.dokan_remain_seconds() is None
    t.wait_settlement_tick()
    remain = (t._settlement_deadline - datetime.now()).total_seconds()
    assert 29 * 60 <= remain <= 30 * 60
    # 心跳: 超过硬上限后允许退出
    t._settlement_wait_start = datetime.now() - ScriptTask.SETTLEMENT_WAIT_MAX - timedelta(seconds=1)
    t._settlement_wait_last_log = datetime.now() - timedelta(seconds=60)
    t.wait_settlement_tick()
    assert t.exit_allowed() is True


def test_quit_battle_stops_when_already_back_in_dokan_scene():
    """19:10 的根因: 战斗已结束回到寮境, 左上角箭头是"退出道馆", 不能再点"""
    t = make_task(appear_set={ScriptTask.I_RYOU_DOKAN_START_CHALLENGE})
    t.quit_battle()
    assert t.clicked == []


def test_quit_battle_cancels_the_reward_dialog():
    """万一弹出了"退出后将无法领取本次道馆突破奖励", 只点取消"""
    t = make_task(appear_set={ScriptTask.I_RYOU_DOKAN_EXIT_ENSURE})
    t.quit_battle()
    assert t.clicked == [ScriptTask.C_DOKAN_EXIT_CANCEL]


def test_quit_battle_still_clicks_when_really_in_battle():
    t = make_task(appear_set=set())
    t.quit_battle()
    assert t.clicked, "还在战斗结算页时应该继续点左上角退出按钮"
    assert all(c is ScriptTask.C_DOKAN_BATTLE_QUIT_AREA for c in t.clicked)


def test_goto_main_refuses_to_confirm_exit_before_settlement():
    t = make_task(appear_set={ScriptTask.I_RYOU_DOKAN_EXIT_ENSURE})
    t.dokan_joined = True
    assert t.goto_main() is False
    assert t.clicked == [ScriptTask.C_DOKAN_EXIT_CANCEL]


def test_goto_main_confirms_exit_after_settlement():
    t = make_task()
    t.dokan_joined = True
    t.dokan_settled = True
    state = {'confirmed': False}

    def appear(target, interval=None, threshold=None):
        if target is ScriptTask.I_RYOU_DOKAN_EXIT_ENSURE:
            return not state['confirmed']
        # 确认退出之后才会回到庭院
        return target is ScriptTask.I_CHECK_MAIN and state['confirmed']

    def ui_click_until_disappear(*args, **kwargs):
        state['confirmed'] = True
        t.clicked.append(args[0])
        return True

    t.appear = appear
    t.ui_click_until_disappear = ui_click_until_disappear
    assert t.goto_main() is True
    assert t.clicked == [ScriptTask.I_RYOU_DOKAN_EXIT_ENSURE]
