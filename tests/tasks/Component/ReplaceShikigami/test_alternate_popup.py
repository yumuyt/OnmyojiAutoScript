# -*- coding: utf-8 -*-
"""式神育成"是否育成候补式神"弹窗的回归测试。

现场证据: log/error/1790890165214/2026-10-02_05-29-25-161098.png
          (式神育成界面 + "是否育成候补式神 取消/确定(不再提示)" 模态弹窗;
           实测 rs_u_confirm_alternate.png 匹配 1.0000, rs_u_circle_alternate.png 匹配 0.9994)
事故: 2026-10-02 05:29 OAS1 结界蹭卡, 弹窗在 set_shikigami 退出之后才出现,
      stop_image 又被弹窗挡住, 调用方于是在弹窗上连点 10 次 UI_UI_BACK_BLUE,
      触发 GameTooManyClickError -> 重启游戏。
"""
from tasks.Component.ReplaceShikigami.replace_shikigami import ReplaceShikigami
from tasks.KekkaiUtilize.script_task import ScriptTask as KekkaiUtilizeTask


class FakeDevice:
    def __init__(self):
        self.image = None


def make_replace_shikigami(visible=()):
    """只带外设的 ReplaceShikigami 替身"""
    t = ReplaceShikigami.__new__(ReplaceShikigami)
    t.visible = set(visible)
    t.clicked = []
    t.interval_timer = {}
    t.device = FakeDevice()
    t.screenshot = lambda: None

    def appear(target, interval=None, threshold=None):
        return target in t.visible

    def appear_then_click(target, action=None, interval=None, threshold=None, duration=None):
        if target not in t.visible:
            return False
        t.clicked.append(target)
        return True

    t.appear = appear
    t.appear_then_click = appear_then_click
    t.click = lambda target=None, interval=None: t.clicked.append(target) or True
    return t


def make_check_max_lv_task(visible=()):
    """结界蹭卡里"回到结界界面"那段循环的替身"""
    t = KekkaiUtilizeTask.__new__(KekkaiUtilizeTask)
    t.visible = set(visible)
    t.clicked = []
    t.back_clicks = 0
    t.frames = 0
    t.interval_timer = {}
    t.device = FakeDevice()
    t.realm_goto_grown = lambda: None
    t.detect_no_shikigami = lambda: False

    def screenshot():
        t.frames += 1
        assert t.frames < 50, '界面没有变化, 点击死循环了'

    def appear(target, interval=None, threshold=None):
        return target in t.visible

    def appear_multi_scale(target, interval=None, threshold=None, scales=None, scale_range=None):
        return target in t.visible

    def appear_then_click(target, action=None, interval=None, threshold=None, duration=None):
        if target not in t.visible:
            return False
        t.clicked.append(target)
        if target is KekkaiUtilizeTask.I_UI_BACK_BLUE:
            t.back_clicks += 1
        # 弹窗点掉之后, 育成界面才回得到结界界面
        if target in (KekkaiUtilizeTask.I_UI_CONFIRM,
                      KekkaiUtilizeTask.I_U_CONFIRM_ALTERNATE,
                      KekkaiUtilizeTask.I_U_CIRCLE_ALTERNATE):
            t.visible -= {KekkaiUtilizeTask.I_UI_CONFIRM,
                          KekkaiUtilizeTask.I_U_CONFIRM_ALTERNATE,
                          KekkaiUtilizeTask.I_U_CIRCLE_ALTERNATE}
            t.visible |= {KekkaiUtilizeTask.I_REALM_SHIN, KekkaiUtilizeTask.I_SHI_GROWN}
        return True

    t.screenshot = screenshot
    t.appear = appear
    t.appear_multi_scale = appear_multi_scale
    t.appear_then_click = appear_then_click
    return t


def test_dismiss_alternate_confirm_clicks_no_longer_prompt_then_confirm():
    t = make_replace_shikigami({ReplaceShikigami.I_U_CIRCLE_ALTERNATE,
                                ReplaceShikigami.I_U_CONFIRM_ALTERNATE,
                                ReplaceShikigami.I_UI_CONFIRM})

    assert t.dismiss_alternate_confirm() is True
    # 先勾上"不再提示", 同一帧里接着点确定
    assert t.clicked == [ReplaceShikigami.I_U_CIRCLE_ALTERNATE,
                         ReplaceShikigami.I_U_CONFIRM_ALTERNATE]


def test_dismiss_alternate_confirm_returns_false_without_popup():
    t = make_replace_shikigami()

    assert t.dismiss_alternate_confirm() is False
    assert t.clicked == []


def test_set_shikigami_dismisses_popup_left_on_the_screen():
    """stop_image 被弹窗挡住而提前结束时, 不能把弹窗留给调用方"""
    t = make_replace_shikigami({ReplaceShikigami.I_UI_CONFIRM})

    t.set_shikigami(shikigami_order=7, stop_image=ReplaceShikigami.I_RS_NO_ADD)

    assert t.clicked, '循环结束了却没把弹窗点掉'
    assert set(t.clicked) == {ReplaceShikigami.I_UI_CONFIRM}


def test_back_loop_dismisses_popup_instead_of_spamming_back():
    """返回循环: 弹窗是模态的, 点返回键没用, 得先把弹窗点掉"""
    t = make_check_max_lv_task({KekkaiUtilizeTask.I_UI_CONFIRM})

    t.check_max_lv()

    assert KekkaiUtilizeTask.I_UI_CONFIRM in t.clicked
    assert t.back_clicks == 0, '弹窗挡着的时候点返回键, 点满 10 次就会重启游戏'
