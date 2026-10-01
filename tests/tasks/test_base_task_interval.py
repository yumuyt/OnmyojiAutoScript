# -*- coding: utf-8 -*-
"""
节流闸门(interval)的回归测试

历史行为: interval 每次不同时会重建 Timer, 而新建的 Timer._current = 0 ->
reached() 立刻为 True -> 节流当场失效。Duel 里的
`self.click(self.C_DUEL_CLICK_5, interval=random.uniform(0.7, 1.4))` 传的就是动态 interval,
也就是说那行"降低点击频率"其实一直没生效。
"""
from module.atom.click import RuleClick
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from tasks.base_task import BaseTask


class FakeDevice:
    image = None

    def __init__(self):
        self.clicks = []

    def click(self, x=None, y=None, control_check=True, control_name='Click'):
        self.clicks.append((x, y, control_name))


class FakeTarget:
    """只实现 appear() 用到的两个接口: .name 和 .match()"""

    def __init__(self, name='TARGET', hit=True):
        self.name = name
        self.hit = hit
        self.match_calls = 0

    def match(self, image, threshold=None):
        self.match_calls += 1
        return self.hit


class FakeSelf:
    # 把真实的节流闸门挂上来: 测试里只绕过 config/device 的构造, 逻辑仍走真代码
    interval_gate = BaseTask.interval_gate

    def __init__(self):
        self.interval_timer = {}
        self.device = FakeDevice()


def rewind(self_, name, seconds):
    """把某个节流计时器往前拨 seconds 秒, 模拟时间流逝"""
    self_.interval_timer[name]._current -= seconds


def test_appear_throttles_same_interval():
    self_ = FakeSelf()
    target = FakeTarget()

    assert BaseTask.appear(self_, target, interval=1.0) is True
    assert BaseTask.appear(self_, target, interval=1.0) is False
    # 被拦下时不应该再做一次模板匹配(省 CPU)
    assert target.match_calls == 1


def test_appear_still_throttles_when_interval_changes():
    self_ = FakeSelf()
    target = FakeTarget()

    assert BaseTask.appear(self_, target, interval=1.0) is True
    # 动态 interval(随机值) 也必须继续被节流
    assert BaseTask.appear(self_, target, interval=1.5) is False
    assert target.match_calls == 1


def test_interval_limit_is_updated_in_place():
    self_ = FakeSelf()
    target = FakeTarget()

    BaseTask.appear(self_, target, interval=1.0)
    timer = self_.interval_timer[target.name]
    BaseTask.appear(self_, target, interval=1.5)

    # 同一个 Timer 对象, 只更新 limit
    assert self_.interval_timer[target.name] is timer
    assert timer.limit == 1.5


def test_appear_passes_after_interval():
    self_ = FakeSelf()
    target = FakeTarget()

    assert BaseTask.appear(self_, target, interval=1.0) is True
    rewind(self_, target.name, 2.0)
    assert BaseTask.appear(self_, target, interval=1.5) is True
    assert target.match_calls == 2


def test_click_still_throttles_when_interval_changes():
    self_ = FakeSelf()
    click = RuleClick(roi_front=(10, 20, 30, 40), roi_back=(10, 20, 30, 40), name='C_DUEL_CLICK_5')

    assert BaseTask.click(self_, click, interval=0.7) is True
    assert len(self_.device.clicks) == 1
    # Duel 的真实写法: interval=random.uniform(...) 每次都不同
    assert BaseTask.click(self_, click, interval=1.4) is False
    assert len(self_.device.clicks) == 1

    rewind(self_, click.name, 2.0)
    assert BaseTask.click(self_, click, interval=1.4) is True
    assert len(self_.device.clicks) == 2


def test_ocr_appear_still_throttles_when_interval_changes():
    self_ = FakeSelf()
    ocr = RuleOcr(name='O_AB_BOSS_NAME', mode='Full', method='Default',
                  roi=(0, 0, 10, 10), area=(0, 0, 10, 10), keyword='')
    # 模拟上一次识别刚刚结束(计时器刚 reset)
    self_.interval_timer[ocr.name] = Timer(1.0).start()

    # 动态 interval 也必须继续被节流: 拦下就返回 None, 不会去调 OCR(device.image 是 None)
    assert BaseTask.ocr_appear(self_, ocr, interval=2.0) is None
    assert self_.interval_timer[ocr.name].limit == 2.0
    assert self_.interval_timer[ocr.name].reached() is False
