# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
from time import sleep

from enum import Enum
from cached_property import cached_property
from datetime import datetime, timedelta

from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer

from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.DemonEncounter.config import BossType, DemonEncounter, convert_to_general_battle_config
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_demon_encounter, page_demon_encounter_realworld, page_shikigami_records
from tasks.DemonEncounter.assets import DemonEncounterAssets
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.DemonEncounter.data.answer import Answer


class LanternClass(Enum):
    BATTLE = 0  # 打怪  --> 无法判断因为怪的图片不一样，用排除法
    BOX = 1  # 开宝箱
    MAIL = 2  # 邮件答题
    REALM = 3  # 打结界
    EMPTY = 4  # 空
    MYSTERY = 5  # 神秘任务
    BOSS = 6  # 大鬼王


class ScriptTask(GameUi, GeneralBattle, DemonEncounterAssets, SwitchSoul):
    conf: DemonEncounter = None

    def run(self):
        self.conf = self.config.demon_encounter
        if not self.check_time():
            logger.warning('Time is not right')
            raise TaskEnd('DemonEncounter')
        self.ui_get_current_page()
        # 切换御魂
        soul_config = self.config.demon_encounter.demon_soul_config
        best_soul_config = self.config.demon_encounter.best_demon_soul_config
        if soul_config.enable or best_soul_config.enable:
            self.ui_goto(page_shikigami_records)
            self.checkout_soul()
        self.ui_goto(page_demon_encounter_realworld)
        # 顶部"今日挑战次数:X/1"检测, 0/1表示今日已打过, 直接结束
        if self.check_challenge_done():
            logger.info('Challenge count 0/1, already challenged today')
            self.set_next_run(task='DemonEncounter', success=True, finish=False)
            raise TaskEnd('DemonEncounter')
        self.execute_lantern()
        self.execute_boss()

        self.set_next_run(task='DemonEncounter', success=True, finish=False)
        raise TaskEnd('DemonEncounter')

    def check_challenge_done(self) -> bool:
        """
        OCR识别现世逢魔顶部"今日挑战次数:剩余/总", 支持老号X/1与新号X/2
        DigitCounter 返回 (current, remain, total), current 即剩余次数
        :return: True表示剩余=0, 今日已打过
        """
        current, _remain, total = self.O_DE_CHALLENGE_COUNT.ocr(self.device.image)
        if total > 0:
            logger.info(f'Demon encounter challenge count: {current}/{total}')
            return current == 0
        logger.warning('Challenge count not recognized, assume attempts remain')
        return False

    def checkout_soul(self):
        """
        切换御魂
        """
        select_best_demon = getattr(self.conf.best_demon_boss_config, f'{self.boss_type}_select', False)
        if select_best_demon:
            group, team = getattr(self.conf.best_demon_soul_config, self.boss_type).split(",")
        else:
            group, team = getattr(self.conf.demon_soul_config, self.boss_type).split(",")
        if group and team:
            self.run_switch_soul_by_name(group, team)
            return
        logger.error(f'Unknown switch soul conf: group[{group}], team[{team}]')

    def execute_boss(self):
        """
        打boss
        :return:
        """
        logger.hr('Start boss battle', 1)

        def find_boss():
            search_button = self.I_DE_BOSS_BEST if self.best_demon_enable else self.I_DE_BOSS
            boss_name = 'best boss' if self.best_demon_enable else 'normal boss'

            # 每轮搜索前若中央有未购买的宝箱展示, 先点左下角定位(小指针)把它挪开;
            # 一整轮(2次搜索)都没找到则重进逢魔之时清状态, 最多3轮。
            for reenter_round in range(1, 4):
                self.screenshot()
                if self.appear(self.I_DE_BOX_CENTER):
                    logger.info(
                        f'Box display at map center, click location to reset view '
                        f'(round {reenter_round}/3)'
                    )
                    self.appear_then_click(self.I_DE_LOCATION, interval=2)
                    time.sleep(1)

                # 最多重新执行两轮“逢魔/极逢魔 -> 地图中央首领”的完整流程。
                for search_attempt in range(1, 3):
                    self.device.click_record_clear()
                    self.screenshot()
                    if self.appear(self.I_BOSS_FIRE) or self.appear(self.I_BEST_BOSS_FIRE):
                        return True
                    # 没找到boss但地图中央出现宝箱, 导致点击宝箱出现50勾玉购买界面(事后补救)
                    if self.appear(self.I_JADE_50):
                        self.ui_click_until_smt_disappear(self.I_DE_FIND, self.I_JADE_50, interval=1)
                        continue
                    if not self.appear_then_click(search_button, interval=2):
                        # 首领按钮一两次没认出来(实机上出现过 0.797 贴阈值的情况)不代表要重开局:
                        # 本轮先退出, 交给下面"重进逢魔地图清状态"的恢复逻辑, 3 轮都找不到
                        # 才放弃本次运行。全程不抛错、不重启游戏。
                        logger.warning(f'{boss_name} search button not found '
                                       f'(round {reenter_round}/3, attempt {search_attempt}/2)')
                        break
                    logger.info(
                        f'Finding {boss_name}, attempt {search_attempt}/2 '
                        f'(re-enter round {reenter_round}/3)...'
                    )
                    time.sleep(1)

                    # 每轮点击地图中央框选的红色“集结”区域至多两次，
                    # 每次等待集结挑战标志5秒。
                    for center_attempt in range(1, 3):
                        self.click(self.C_DM_BOSS_CLICK, interval=2)
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            self.screenshot()
                            if self.appear(self.I_BOSS_FIRE) or self.appear(self.I_BEST_BOSS_FIRE):
                                logger.info(
                                    f'{boss_name} gather appeared after center click '
                                    f'{center_attempt}/2'
                                )
                                return True
                            time.sleep(0.2)
                        logger.warning(
                            f'{boss_name} gather did not appear after center click '
                            f'{center_attempt}/2'
                        )

                    # 本轮失败，返回逢魔地图，重新点击逢魔/极逢魔进行下一轮搜寻。
                    self.screenshot()
                    if self.appear(self.I_UI_BACK_RED):
                        self.appear_then_click(self.I_UI_BACK_RED, interval=2)
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            self.screenshot()
                            if self.appear(search_button):
                                break
                            time.sleep(0.2)

                # 2次搜索都没找到: 重进地图清状态, 最多3轮
                logger.info(f'Boss not found, re-enter demon encounter map (round {reenter_round}/3)')
                self.ui_goto_page(page_demon_encounter)
                self.ui_goto_page(page_demon_encounter_realworld)

            # 3 轮重进地图都没找到: 放弃本次运行, 半小时后自己再来一次。
            # 这里刻意不抛 GameStuckError —— 那会走"重启游戏"的路子,
            # 而重进地图本身已经是最温和的恢复手段了。
            logger.warning(f'Cannot enter {boss_name} after 3 re-enter rounds, '
                           f'give up this run and retry later')
            return False

        def enter_boss():
            logger.info('trying to enter boss...')
            # 点击集结挑战
            boss_fire_count = 0  # 五次没点到就意味着今天已经挑战过了
            ocr_people_item = self.O_DE_BEST_BOSS_PEOPLE if self.best_demon_enable else self.O_DE_BOSS_PEOPLE
            while 1:
                self.screenshot()

                if self.appear(self.I_BOSS_FIRE) or self.appear(self.I_BEST_BOSS_FIRE):
                    current, remain, total = ocr_people_item.ocr(self.device.image)
                    if total == 300 and current >= 290:
                        logger.info('Boss battle people is full')
                        if not self.appear(self.I_UI_BACK_RED):
                            logger.warning('Boss battle people is full but no red back')
                            continue
                        self.ui_click_until_disappear(self.I_UI_BACK_RED)
                        # 退出重新选一个没人慢的boss
                        logger.info('Exit and reselect')
                        return False

                logger.info('Boss battle people is not full')

                if self.appear(self.I_BOSS_CONFIRM):
                    self.ui_click(self.I_BOSS_NO_SELECT, self.I_BOSS_SELECTED)
                    self.ui_click(self.I_BOSS_CONFIRM, self.I_BOSS_GATHER)
                    break
                if self.appear(self.I_BOSS_GATHER):
                    break
                if boss_fire_count >= 5:
                    logger.warning('Boss battle already done')
                    self.set_next_run(task='DemonEncounter', success=False, finish=True, server=True)
                    self.ui_click_until_disappear(self.I_UI_BACK_RED)
                    raise TaskEnd('DemonEncounter')

                if (self.appear_then_click(self.I_BOSS_FIRE, interval=3)
                        or self.appear_then_click(self.I_BEST_BOSS_FIRE, interval=3)):
                    boss_fire_count += 1
                    continue
            return True

        fail_count = 0
        while True:
            if fail_count >= 5:
                return
            if not find_boss():
                # 首领找不到: 记一次失败, 并安排半小时后重试(逢魔 17:00-23:00 内还有机会),
                # 全程不抛错、不重启游戏。server=False 是为了绕开 server_update
                # 把下次运行时间强制改写成"明天 17:05"。
                self.set_next_run(task='DemonEncounter', success=False, server=False,
                                  target=datetime.now() + timedelta(minutes=30))
                raise TaskEnd('DemonEncounter')
            if enter_boss():
                break
            fail_count += 1

        logger.info('Boss battle confirm and enter')
        # 等待挑战, 5秒也是等
        time.sleep(5)
        # 延长时间并在战斗结束后改回来
        self.device.stuck_timer_long = Timer(480, count=480).start()
        preset_switched = False
        # "集结中"和"准备"同时可见时的升级计时: 准备按钮的 ROI(1128,536,100,100) 与
        # 集结挑战/集结中按钮的 ROI(1087,562,100,36) 是重叠的, 所以不能一看到亮块就
        # 当成准备页(那样会在集结阶段误开一场"战斗", 然后落进 battle_wait 等 480s 长卡死)。
        # 正常集结(oas1 2026-10-01 实测 106s / oas2 37s)照旧等; 只有两个元素同时可见
        # 且持续超过 180s 才升级去处理准备页 —— 比 device 的 480s 硬卡死早 5 分钟出来。
        gather_wait_timer = Timer(180)
        while True:
            self.screenshot()
            if self.appear(self.I_BOSS_DONE_CHECK):
                break
            appear_prepare = self.appear(self.I_PREPARE_HIGHLIGHT)
            if self.appear(self.I_BOSS_GATHER):
                if appear_prepare:
                    if not gather_wait_timer.started():
                        gather_wait_timer.start()
                else:
                    gather_wait_timer.clear()
                if not (appear_prepare and gather_wait_timer.reached()):
                    self.device.stuck_record_clear()
                    self.device.stuck_record_add('BATTLE_STATUS_S')
                    logger.info('Boss Gathering...' + (' (prepare button also visible)' if appear_prepare else ''))
                    sleep(2)
                    continue
                logger.warning(f'Gather flag and prepare button both stay for '
                               f'{gather_wait_timer.current():.0f}s, handle prepare page first')
            if self.appear(self.I_BOSS_WAIT):
                logger.info('Boss battle failed, waiting for 2 seconds...')
                sleep(2)
                continue
            if appear_prepare:
                gather_wait_timer.clear()
                if preset_switched:
                    self.run_general_battle()
                    continue
                preset_switched = True
                # 逢魔其他战斗会影响current_count导致大于0
                self.current_count = 0
                if self.best_demon_enable:
                    general_battle_config = convert_to_general_battle_config(self.boss_type,
                                                                             best_demon_battle_conf=self.conf.best_demon_battle_config)
                else:
                    general_battle_config = convert_to_general_battle_config(self.boss_type,
                                                                             demon_battle_conf=self.conf.demon_battle_config)
                self.run_general_battle(config=general_battle_config)
                continue
            logger.info('Unknown scene Or Boss fight failed.waiting for Prepare_Button appear...')
            self.wait_until_appear(self.I_PREPARE_HIGHLIGHT, wait_time=2)

        self.device.stuck_timer_long = Timer(300, count=300).start()

        # 等待回到挑战boss主界面
        self.wait_until_appear(self.I_BOSS_GATHER)
        while 1:
            self.screenshot()
            if self.appear(self.I_DE_LOCATION):
                break
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1):
                continue
            if self.appear_then_click(self.I_BOSS_BACK_WHITE, interval=1):
                continue
        # 返回到封魔主界面

    def execute_lantern(self):
        """
        点灯笼 四次
        :return:
        """
        # 先点四次
        ocr_timer = Timer(0.8)
        ocr_timer.start()
        while 1:
            self.screenshot()
            if not ocr_timer.reached():
                continue
            else:
                ocr_timer.reset()
            cu, re, total = self.O_DE_COUNTER.ocr(self.device.image)
            if cu + re != total:
                logger.warning('Lantern count error')
                continue
            if cu == 0 and re == 4:
                break

            if self.appear_then_click(self.I_DE_FIND, interval=2.5):
                continue
        logger.info('Lantern count success')
        # 然后领取红色达摩
        self.screenshot()
        if not self.appear(self.I_DE_AWARD):
            self.ui_get_reward(self.I_DE_RED_DHARMA)
        self.wait_until_appear(self.I_DE_AWARD)
        # 然后到四个灯笼
        match_click = {
            1: self.C_DE_1,
            2: self.C_DE_2,
            3: self.C_DE_3,
            4: self.C_DE_4,
        }
        for i in range(1, 5):
            logger.hr(f'Check lantern {i}', 3)
            lantern_type = self.check_lantern(i)
            match lantern_type:
                case LanternClass.BOX:
                    self._box(match_click[i])
                case LanternClass.MAIL:
                    self._mail(match_click[i])
                case LanternClass.REALM:
                    self._realm(match_click[i])
                case LanternClass.EMPTY:
                    logger.warning(f'Lantern {i} is empty')
                case LanternClass.BATTLE:
                    self._battle(match_click[i])
                case LanternClass.MYSTERY:
                    self._mystery(match_click[i])
                case LanternClass.BOSS:
                    self._boss(match_click[i])
            time.sleep(1)

    def check_lantern(self, index: int = 1):
        """
        检查灯笼的类型
        :param index: 四个灯笼，从1开始
        :return:
        """
        # 分类模板的搜索区(须容纳完整灯笼图案), 与点击区 C_DE_* 分离:
        # 点击区只包住内部图形, 模板放不进搜索区会全部误判成 battle
        match_roi = {
            1: self.C_DE_MATCH_1.roi_front,
            2: self.C_DE_MATCH_2.roi_front,
            3: self.C_DE_MATCH_3.roi_front,
            4: self.C_DE_MATCH_4.roi_front,
        }
        match_empty = {
            1: self.I_DE_DEFEAT_1,
            2: self.I_DE_DEFEAT_2,
            3: self.I_DE_DEFEAT_3,
            4: self.I_DE_DEFEAT_4,
        }
        self.I_DE_BOX.roi_back = match_roi[index]
        self.I_DE_LETTER.roi_back = match_roi[index]
        self.I_DE_MYSTERY.roi_back = match_roi[index]
        self.I_DE_REALM.roi_back = match_roi[index]
        self.I_DE_FIND_BOSS.roi_back = match_roi[index]
        target_box = self.I_DE_BOX
        target_letter = self.I_DE_LETTER
        target_mystery = self.I_DE_MYSTERY
        target_realm = self.I_DE_REALM
        target_find_boss = self.I_DE_FIND_BOSS
        target_empty = match_empty[index]

        # 开始判断
        self.screenshot()
        if self.appear(target_box):
            logger.info(f'Lantern {index} is box')
            return LanternClass.BOX
        elif self.appear(target_letter):
            logger.info(f'Lantern {index} is letter')
            return LanternClass.MAIL
        elif self.appear(target_mystery):
            logger.info(f'Lantern {index} is mystery task')
            return LanternClass.MYSTERY
        elif self.appear(target_realm):
            logger.info(f'Lantern {index} is realm')
            return LanternClass.REALM
        elif self.appear(target_empty):
            logger.info(f'Lantern {index} is empty')
            return LanternClass.EMPTY
        elif self.appear(target_find_boss):
            logger.info(f'Lantern {index} is boss')
            return LanternClass.BOSS
        else:
            # 无法判断是否是战斗的还是结界的
            logger.info(f'Lantern {index} is battle')
            return LanternClass.BATTLE

    def _box(self, target_click):
        box_buy_config = self.config.demon_encounter.box_buy_config
        while 1:
            self.screenshot()
            if self.appear(self.I_JADE_50):
                break
            if self.click(target_click, interval=1):
                continue
        while 1:
            self.screenshot()
            if not self.appear(self.I_MYSTERY_AMULET) and not (box_buy_config.box_buy_sushi and self.appear(self.I_SUSHI)):
                if self.appear_then_click(self.I_DE_FIND, interval=2.5):
                    break
            # 默认购买蓝票
            if self.appear(self.I_MYSTERY_AMULET):
                logger.info('Buy a mystery amulet for 50 jade')
                self.click(self.I_JADE_50)
                continue
            # 可选购买体力
            if box_buy_config.box_buy_sushi and self.appear(self.I_SUSHI):
                logger.info('Buy one hundred sushi for 50 jade')
                self.click(self.I_JADE_50)
                continue

    def _mail(self, target_click):
        # 答题
        def answer():
            click_match = {
                1: self.C_ANSWER_1,
                2: self.C_ANSWER_2,
                3: self.C_ANSWER_3,
            }
            index = None
            self.screenshot()
            question = self.O_LETTER_QUESTION.detect_text(self.device.image)
            question = question.replace('?', '').replace('？', '')
            answer_1 = self.O_LETTER_ANSWER_1.detect_text(self.device.image)
            answer_2 = self.O_LETTER_ANSWER_2.detect_text(self.device.image)
            answer_3 = self.O_LETTER_ANSWER_3.detect_text(self.device.image)
            if answer_1 == '其余选项皆对':
                index = 1
            elif answer_2 == '其余选项皆对':
                index = 2
            elif answer_3 == '其余选项皆对':
                index = 3
            if not index:
                index = Answer().answer_one(question=question, options=[answer_1, answer_2, answer_3])
            if index is None:
                index = 1
            logger.info(f'Question: {question}, Answer: {index}')
            return click_match[index]

        while 1:
            self.screenshot()
            if self.appear(self.I_LETTER_CLOSE):
                break
            if self.click(target_click, interval=1):
                continue
        logger.info('Question answering Start')
        for i in range(1, 4):
            # 还未测试题库无法识别的情况
            logger.hr(f'Answer {i}', 3)
            answer_click = answer()
            # self.ui_get_reward(answer())
            while 1:
                self.screenshot()
                if self.ui_reward_appear_click():
                    time.sleep(0.5)
                    while 1:
                        self.screenshot()
                        # 等待动画结束
                        if not self.appear(self.I_UI_REWARD, threshold=0.6):
                            logger.info('Get reward success')
                            break
                        # 一直点击
                        if self.ui_reward_appear_click():
                            continue
                    break
                # 如果没有出现红色关闭按钮，说明答题结束
                if not self.appear(self.I_LETTER_CLOSE):
                    time.sleep(2.5)
                    self.screenshot()
                    if not self.appear(self.I_LETTER_CLOSE):
                        self.ui_reward_appear_click()
                        logger.warning('Answer finish')
                        return

                # 一直点击
                self.click(answer_click, interval=1.5)
            time.sleep(0.5)

    def _battle(self, target_click):
        while 1:
            self.screenshot()
            if not self.appear(self.I_DE_LOCATION):
                logger.info('Battle Start')
                break
            if self.appear(self.I_DE_SMALL_FIRE):
                # 小鬼王
                logger.info('Small Boss')
                while 1:
                    self.screenshot()
                    if not self.appear(self.I_DE_SMALL_FIRE):
                        break
                    if self.appear_then_click(self.I_DE_SMALL_FIRE, interval=1):
                        continue
                break

            if self.click(target_click, interval=1):
                continue
        if self.run_general_battle():
            logger.info('Battle End')

    def _realm(self, target_click):
        # 结界
        while 1:
            self.screenshot()
            if not self.appear(self.I_DE_LOCATION):
                logger.info('Battle Start')
                break
            if self.appear_then_click(self.I_DE_REALM_FIRE, interval=0.7):
                continue

            if self.click(target_click, interval=1):
                continue
        if self.run_general_battle():
            logger.info('Battle End')

    def _mystery(self, target_click):
        # 神秘任务， 不做
        pass

    def _boss(self, target_click):
        # 运气爆表，点灯笼出现大鬼王
        while 1:
            self.screenshot()
            if self.appear(self.I_BOSS_KILLED):
                # 这个大鬼王已经击败
                logger.warning('Boss already killed')
                self.ui_click_until_disappear(self.I_UI_BACK_RED)
                break
            if self.appear(self.I_BOSS_FIRE):
                self.execute_boss()
                break
            if self.click(target_click, interval=2.3):
                continue

    def check_time(self):
        """
        检查时间是否正确，
        如果正确就继续
        如果不在17:00到22:00之间,就推迟到下一个 17:30
        :return:
        """
        now = datetime.now()
        if now.hour < 17:
            # 17点之前，推迟到当天的17点半
            logger.info('Before 17:00, wait to 17:30')
            target_time = datetime(now.year, now.month, now.day, 17, 30, 0)
            self.set_next_run(task='DemonEncounter', success=False, finish=False, target=target_time)
            return False
        elif now.hour >= 23:
            # 23点之后，推迟到第二天的17:30
            logger.info('After 23:00, wait to 17:30')
            target_time = datetime(now.year, now.month, now.day, 17, 30, 0) + timedelta(days=1)
            self.set_next_run(task='DemonEncounter', success=False, finish=False, target=target_time)
            return False
        else:
            return True

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        # 重写
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        # 战斗过程 随机点击和滑动 防封
        logger.info("Start battle process")
        check_timer = None
        # "准备"兜底: battle_before 的预算可能被切阵容吃光, 或者那唯一一次点击被游戏吞掉,
        # 这时脚本会停在准备界面干等到 480 秒长卡死才报错。
        # 背景: 2026-10-01 17:11 oas1 极逢魔 在准备页空了 5 分 20 秒(靠人手动点准备才开打),
        # 因为加了 BATTLE_STATUS_S 连报错都没有。这里给一小笔额外预算, 自己会找机会补点。
        rescue_left = self.PREPARE_RESCUE_CLICK_LIMIT
        rescue_timer = Timer(8).start()  # 先给游戏 8 秒自己进战斗的机会
        rescue_window = Timer(self.PREPARE_RESCUE_WINDOW).start()
        while 1:
            self.screenshot()
            if self.appear(self.I_DE_WIN):
                logger.info('Appear [demon encounter] win button')
                self.ui_click_until_disappear(self.I_DE_WIN)
                check_timer = Timer(3)
                check_timer.start()
                continue
            if self.appear_then_click(self.I_WIN, interval=1):
                logger.info('Appear win button')
                check_timer = Timer(3)
                check_timer.start()
                continue
            if self.appear(self.I_REWARD):
                logger.info('Win battle')
                self.ui_click_until_disappear(self.I_REWARD)
                return True

            # 失败的
            if self.appear(self.I_FALSE):
                logger.warning('False battle')
                self.ui_click_until_disappear(self.I_FALSE)
                return False
            # 还停在准备界面 -> 兜底补点"准备"
            if rescue_left > 0 and not rescue_window.reached() and rescue_timer.reached():
                if self.press_prepare(ignore_budget=True):
                    rescue_left -= 1
                    continue
            # 时间到
            if check_timer and check_timer.reached():
                logger.warning('Obtain battle timeout')
                return True

    @property
    def boss_type(self) -> str:
        boss_name = BossType(datetime.now().weekday()).name
        if self.best_demon_enable:
            return f'best_demon_{boss_name}'
        return f'demon_{boss_name}'

    @property
    def best_demon_enable(self) -> bool:
        boss_name = BossType(datetime.now().weekday()).name
        return getattr(self.conf.best_demon_boss_config, f'best_demon_{boss_name}_select', False)

    def wait_and_click(self, target) -> bool:
        """
        等待目标出现并点击，然后返回True
        :param target: 图片规则
        :return: 点击成功返回True
        """
        from module.base.timer import Timer
        from module.exception import TaskEnd
        timeout = 60
        timer = Timer(timeout)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if self.appear(target):
                if self.appear_then_click(target, interval=1):
                    return True
        logger.warning(f'wait_and_click {target.name} timeout')
        return False


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('du')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()
    # t.battle_wait(True)
