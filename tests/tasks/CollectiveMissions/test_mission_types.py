# -*- coding: utf-8 -*-
"""
集体任务: 任务类型识别 / missions_rule 白名单 / 指定任务切换

背景(2026-10-01 22:30 oas2 现场):
卡片标题 = "<自定义任务名>·<任务类型>", 本机左侧自定义任务卡写作 "远远不够·养成"。
旧实现的判据是 '·' 左边那半截 —— `result_1 == '远远不够'` 就返回 MC.FEED(喂 N 卡),
于是:
  1) 想指定 "养成" 时永远匹配不上(枚举值是 '远远不够', 配置里填 "养成" 或者卡片全名
     "远远不够·养成" 都不相等) → select_mission 白点 20 次「切换任务」, 眼睁睁刷过
     养成卡片;
  2) "远远不够·御魂三" 里的 御魂三 当时不在 MC 枚举里 → 落到那个 '远远不够' 兜底分支
     被误判成 MC.FEED → detect_best 选中它 → _feed 去点左卡「提交」按钮连点 10 次
     → GameTooManyClickError → 游戏被强制重启。

现在: 类型只认 '·' 右边的类型名(养成 / 御魂三 / …), '·' 左边随便叫什么都不影响。
"""
from types import SimpleNamespace

from tasks.CollectiveMissions.config import MissionsConfig
from tasks.CollectiveMissions.script_task import MC, ScriptTask


# ---------------------------------------------------------------- 类型识别

def test_classify_real_ocr_texts():
    """日志里真实出现过的标题文本(CM_1 + CM_2 拼起来)"""
    cases = {
        '远远不够养成': MC.FEED,          # 左侧自定义任务卡: 养成
        '远远不够御魂三': MC.SO3,          # 曾经被误判成 FEED
        '远远不够御魂二': MC.SO2,
        '远远不够御魂一': MC.SO1,
        '远远不够觉醒一': MC.AW1,
        '远远不够觉醒二': MC.AW2,
        '远远不够觉醒三': MC.AW3,
        '远远不够御灵一': MC.GR1,
        '远远不够御灵二': MC.GR2,
        '远远不够御灵三': MC.GR3,
        '契灵探查': MC.BL,
        '结伴同行': MC.FRIEND,
        '我爱我寮': MC.UNKNOWN,
        '我爱我察': MC.UNKNOWN,            # OCR 错字, 中间卡片本来也不用做
        '': MC.UNKNOWN,
    }
    for text, want in cases.items():
        assert ScriptTask.classify(text) == want, text


def test_custom_task_name_is_not_a_mission_type():
    """自定义任务名(本机 "远远不够")换了字, 识别结果不能变"""
    assert ScriptTask.classify('请做觉醒养成') == MC.FEED
    assert ScriptTask.classify('随便起的名御魂三') == MC.SO3
    # 反过来: 只有自定义任务名、没有类型名时, 必须认不出来(否则又会误判)
    assert ScriptTask.classify('远远不够') == MC.UNKNOWN


# ---------------------------------------------------------------- 配置迁移

def test_missions_rule_migration():
    """旧配置里的 "远远不够" 加载时换成类型名 "养成"; 老写法 御魂五/四 照旧映射"""
    conf = MissionsConfig(missions_rule='契灵 > 御魂五 > 御魂四 > 远远不够')
    assert conf.missions_rule == '契灵 > 御魂二 > 御魂一 > 养成'


def test_default_rule_uses_type_names():
    conf = MissionsConfig()
    assert conf.missions_rule.endswith('养成')
    assert '远远不够' not in conf.missions_rule


# ---------------------------------------------------------------- 白名单

def _make_task(rule: str) -> ScriptTask:
    task = ScriptTask.__new__(ScriptTask)
    task.config = SimpleNamespace(
        collective_missions=SimpleNamespace(
            missions_config=SimpleNamespace(missions_rule=rule)))
    return task


def test_rule_parsing_ignores_unknown_words():
    task = _make_task('契灵 > 养成\n> 御魂二 > 随便写的 > 未知')
    assert task.rule == ['契灵', '养成', '御魂二', '未知']


def test_rule_tolerates_legacy_word():
    """进程没重启、配置模型还是老的时候(规则里仍写 "远远不够"), 也得解析出 养成"""
    task = _make_task('契灵 > 御魂二 > 远远不够')
    assert task.rule == ['契灵', '御魂二', '养成']


def test_detect_best_picks_highest_priority_in_rule():
    task = _make_task('契灵 > 觉醒三 > 御魂二 > 养成')
    cards = {(task.O_CM_1, task.O_CM_2): MC.SO3,       # 左: 御魂三, 不在白名单
             (task.O_CM_3, task.O_CM_4): MC.UNKNOWN,   # 中: 我爱我寮
             (task.O_CM_5, task.O_CM_6): MC.SO2}       # 右: 御魂二, 在白名单
    task.detect_one = lambda ocr_1, ocr_2: cards[(ocr_1, ocr_2)]

    mission, index = task.detect_best()
    assert (mission, index) == (MC.SO2, 2)


def test_detect_best_skips_when_nothing_is_listed():
    """老实现在这里会因为 best_class 没绑定而 UnboundLocalError"""
    task = _make_task('契灵 > 觉醒三')
    cards = {(task.O_CM_1, task.O_CM_2): MC.SO3,
             (task.O_CM_3, task.O_CM_4): MC.UNKNOWN,
             (task.O_CM_5, task.O_CM_6): MC.FRIEND}
    task.detect_one = lambda ocr_1, ocr_2: cards[(ocr_1, ocr_2)]

    assert task.detect_best() == (MC.UNKNOWN, 0)


# ---------------------------------------------------------------- 切换任务

class FakeSwitch:
    def match_brightness(self, image):
        return True

    def match_mean_color(self, image, color=None):
        return True


def _make_select_task(cards: list):
    """cards: 依次读到的卡片标题; 只剩一张时反复读它"""
    task = ScriptTask.__new__(ScriptTask)
    task.config = SimpleNamespace(
        collective_missions=SimpleNamespace(
            missions_config=SimpleNamespace(
                missions_rule='契灵 > 觉醒三 > 御魂二 > 养成')))
    task.I_CM_SWITCH = FakeSwitch()
    reads = list(cards)
    task.reads = reads

    def read_card(ocr_1, ocr_2):
        return reads.pop(0) if len(reads) > 1 else reads[0]

    clicks = []
    cleared = []
    task.read_card = read_card
    task.device = SimpleNamespace(click_record_clear=lambda: cleared.append(1),
                                  image=None)
    task.appear_then_click = lambda button, interval=1: clicks.append(button) or True
    return task, clicks, cleared


def test_select_mission_accepts_type_name():
    """配置里填类型名 "养成" """
    task, clicks, _ = _make_select_task(['远远不够御魂一', '远远不够养成'])
    assert task.select_mission('养成') is True
    assert len(clicks) == 1          # 只点了一次「切换任务」


def test_select_mission_accepts_full_card_name():
    """配置里填卡片全名 "远远不够·养成" 也认"""
    task, clicks, _ = _make_select_task(['远远不够养成'])
    assert task.select_mission('远远不够·养成') is True
    assert clicks == []


def test_select_mission_gives_up_on_unknown_target():
    """填了认不出来的名字(例如旧写法 "远远不够"): 立刻返回, 不空点「切换任务」"""
    task, clicks, _ = _make_select_task(['远远不够御魂一'])
    assert task.select_mission('远远不够') is False
    assert clicks == []
    assert task.reads == ['远远不够御魂一']


def test_select_mission_gives_up_after_20_clicks():
    """刷不到就优雅放弃(以前最多点 10 次就被框架 GameTooManyClickError 强制重启)"""
    task, clicks, cleared = _make_select_task(['远远不够御魂一'])
    assert task.select_mission('觉醒三') is False
    assert len(clicks) == 21
    assert len(cleared) == 21
