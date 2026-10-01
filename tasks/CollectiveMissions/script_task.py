# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import random
import re
from cached_property import cached_property
from enum import Enum
from datetime import timedelta

from module.exception import TaskEnd, RequestHumanTakeover
from module.logger import logger
from module.base.timer import Timer
from module.atom.ocr import RuleOcr

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_guild
from tasks.CollectiveMissions.assets import CollectiveMissionsAssets


class MC(str, Enum):
    """
    任务卡上的任务类型。

    卡片标题 = "<自定义任务名>·<任务类型>"，左侧那张自定义任务卡写作 "远远不够·养成"：
      * '·' 右边才是**任务类型**（养成 / 觉醒一 / 御魂三 / 契灵探查 …），唯一可靠的判据；
      * '·' 左边是寮管理自己起的名字（本机是 "远远不够"），可以是任何文字，不能当判据。

    旧实现拿 '·' 左边那半截当判据（result_1 == '远远不够' 就当成喂 N 卡），于是
    "远远不够·御魂三" 被误判成 MC.FEED，_feed 去点左侧卡片的「提交」按钮连点 10 次
    → GameTooManyClickError → 游戏重启（2026-10-01 22:30 oas2 现场）。
    """
    BL = '契灵'
    AW1 = '觉醒一'
    AW2 = '觉醒二'
    AW3 = '觉醒三'
    GR1 = '御灵一'
    GR2 = '御灵二'
    GR3 = '御灵三'
    SO1 = '御魂一'
    SO2 = '御魂二'
    SO3 = '御魂三'
    FRIEND = '结伴同行'
    UNKNOWN = '未知'
    FEED = '养成'  # 喂 N 卡（旧配置里这个类型写成 "远远不够"，见 MissionsConfig）

class ScriptTask(GameUi, CollectiveMissionsAssets):
    missions: list = []  # 用于记录三个的任务的种类

    @cached_property
    def rule(self) -> list:
        rule = self.config.collective_missions.missions_config.missions_rule
        # 旧写法兜底：喂 N 卡任务以前写作 "远远不够"（那是左侧自定义任务名，不是类型名）。
        # 正常情况 Config 加载时 MissionsConfig.mr_validator 已经换掉了，这里再兜一次，
        # 免得"进程没重启、配置模型还是老的"时把 养成 当成不认识的写法丢掉。
        rule = rule.replace('远远不够', MC.FEED.value)
        rule = rule.replace(' ', '').replace('\n', '')
        # 正则表达式 分离 ">"
        rule = re.split(r'>', rule)
        mc_values_list = [member.value for member in MC]
        unknown = [item for item in rule if item and item not in mc_values_list]
        if unknown:
            logger.warning(f'missions_rule 里这些写法不是任务类型，已忽略: {unknown}')
        rule = [item for item in rule if item in mc_values_list]
        return rule

    def run(self):
        self.ui_get_current_page()
        self.ui_goto(page_guild)
        rule = self.config.collective_missions.missions_config.missions_rule
        self.ui_click(self.I_CM_SHRINE, self.I_CM_CM)
        self.ui_click(self.I_CM_CM, self.I_CM_RECORDS)
        logger.info('Start to detect missions')

        # 1. 先领奖励。
        #    必须在"判上限"之前：三个任务共享每日 30 次上限，中间的任务(我爱我寮)
        #    会在日常里自动完成，所以即使「今日已完成次数」已经 30/30，
        #    它的奖励仍可能挂在卡片上没领。顺序反了就永远领不到。
        self.claim_rewards()

        # 2. 再判断今天是否已经完成到上限
        self.screenshot()
        current, remain, total = self.O_CM_NUMBER.ocr(self.device.image)
        if total and current >= total:
            logger.warning(f'Today\'s missions have been completed ({current}/{total})')
            self.set_next_run(task='CollectiveMissions', success=False, finish=True)
            raise TaskEnd('CollectiveMissions')

        # 3. 还有剩余次数 → 切换为目标任务并完成
        mission_name = self.config.collective_missions.missions_config.missions_select
        self.select_mission(mission_name)
        # 判断最优的任务是哪一个
        mission, index = self.detect_best()
        logger.info(f'Best mission is {mission}')
        logger.info(f'Best mission index is {index}')
        if mission == MC.BL:
            # 契灵单独处理
            self._bondling_fairyland(index)
        elif mission == MC.FEED:
            # 单独喂一个 N 卡
            self._feed(index)
        elif mission == MC.AW1 or mission == MC.AW2 or mission == MC.AW3 \
                or mission == MC.GR1 or mission == MC.GR2 or mission == MC.GR3:
            # 其他就捐材料
            self._donate(index)
        elif mission in (MC.SO1, MC.SO2, MC.SO3):
            # 御魂就捐御魂
            self._soul(index)

        # 退出
        while 1:
            self.screenshot()
            if self.appear(self.I_CM_SHRINE) or self.appear(self.I_CHECK_MAIN):
                break
            if self.ui_reward_appear_click(False):
                # 兜底：残留的奖励弹窗（例如自动发放的奖励晚一拍才弹出来）
                continue
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1):
                continue
            if self.appear_then_click(self.I_UI_BACK_YELLOW, interval=1):
                continue

        self.set_next_run(task='CollectiveMissions', success=True, finish=True)
        raise TaskEnd('CollectiveMissions')


    def read_card(self, ocr_1: RuleOcr, ocr_2: RuleOcr) -> str:
        """
        读一张任务卡的标题，并把分隔符 '·' 去掉（例如 "远远不够·养成" → "远远不够养成"）。

        每张卡片的标题各占两个 OCR 区域：前一个盖住 '·' 左边，后一个盖住右边。
        左边那半截是自定义任务名，右边那半截才是任务类型。
        :return: 标题全文（已去掉 '·' 和空格）
        """
        self.screenshot()
        result_1 = ocr_1.ocr(self.device.image)
        result_2 = ocr_2.ocr(self.device.image)
        return (result_1 + result_2).replace('·', '').replace(' ', '')

    @staticmethod
    def classify(name: str) -> MC:
        """
        把卡片标题文本翻译成任务类型。

        只认类型名（养成 / 觉醒一 / 御魂三 / 契灵探查 / 结伴同行 …），
        这些类型名在标题里的位置不受自定义任务名影响，所以左右两半可以一起判。
        """
        for member in (MC.FRIEND, MC.BL, MC.FEED, MC.AW1, MC.AW2, MC.AW3,
                       MC.GR1, MC.GR2, MC.GR3, MC.SO1, MC.SO2, MC.SO3):
            if member.value in name:
                return member
        return MC.UNKNOWN

    def detect_one(self, ocr_1: RuleOcr, ocr_2: RuleOcr) -> MC:
        """
        检测某一个位置是什么的任务
        :param ocr_1:
        :param ocr_2:
        :return:
        """
        return self.classify(self.read_card(ocr_1, ocr_2))

    def detect_best(self) -> tuple:
        """
        在 missions_rule 里挑优先级最高、而且当前三张卡片上真的存在的任务。

        missions_rule 是**白名单 + 优先级**：没写进去的类型不会做（左侧自定义任务
        刷新出来的类型也一样），所以想做什么就往里加。
        :return: 任务类型, 0/1/2；三个类型都不在 missions_rule 里时返回 (MC.UNKNOWN, 0)
        """
        classes = [self.detect_one(self.O_CM_1, self.O_CM_2),
                   self.detect_one(self.O_CM_3, self.O_CM_4),
                   self.detect_one(self.O_CM_5, self.O_CM_6)]
        logger.info(f'missions: {[c.value for c in classes]}')
        logger.info(f'missions_rule: {self.rule}')

        # (优先级, 卡片位置, 任务类型)，按优先级取最小的那个
        candidates = [(self.rule.index(c), i, c) for i, c in enumerate(classes) if c in self.rule]
        if not candidates:
            logger.warning('三张卡片的类型都不在 missions_rule 里，本次不做任务')
            return MC.UNKNOWN, 0
        order, best_index, best_class = min(candidates, key=lambda item: item[0])
        logger.info(f'Best mission is {best_class.value} (order={order}, index={best_index})')
        return best_class, best_index


    def _bondling_fairyland(self, index: int):
        """
        如果御灵已经做了那么就领取奖励
        否则将契灵之境的任务设置为当前，同时两个小时后继续执行当前的任务收菜
        :return:
        """
        def bondling_finish():
            self.screenshot()
            if self.appear(self.I_CM_REWARDS):
                return True
            return False
        if not bondling_finish():
            self.config.bondling_fairyland.scheduler.next_run = self.start_time
            if not self.config.bondling_fairyland.scheduler.enable:
                logger.error('The scheduler of bondling_fairyland is not enable')
                logger.error('Please enable it in config file')
                raise RequestHumanTakeover
            self.set_next_run(task='CollectiveMissions', success=True, finish=True, target=self.start_time + timedelta(hours=2))
            return True
        # 领取奖励
        self.claim_rewards()

    def claim_rewards(self, timeout: float = 3) -> None:
        """
        领掉卡片上所有亮着的「领取奖励」。

        游戏规则：左中右三个任务共享每日 30 次上限，其中只有**前 10 次**完成的任务
        有双倍奖励（触发时会弹两次奖励窗）。中间的任务会在日常活动里自动完成，
        所以即使「今日已完成次数」已到 30/30，它的奖励仍可能挂在卡片上没领 ——
        这一步因此必须放在"判上限"之前。

        I_CM_REWARDS 的 roi_back=(200,458,914,88) 横跨三张卡底部，
        match() 会自动定位到有按钮的那张卡，不需要为每张卡单独写一条。
        """
        logger.info('Start to collect rewards')
        check_timer = Timer(timeout)
        check_timer.start()
        while 1:
            self.screenshot()
            if self.ui_reward_appear_click(True):
                check_timer.reset()
                continue
            if self.appear_then_click(self.I_CM_REWARDS, interval=1):
                check_timer.reset()
                continue
            if check_timer.reached():
                break
        logger.info('Finish to collect rewards')

    def _donate(self, index: int):
        """
        捐赠材料
        :param index: 0, 1, 2 三个任务的位置
        :return:
        """
        match_click = {
            0: self.C_CM_1,
            1: self.C_CM_2,
            2: self.C_CM_3,
        }
        while 1:
            self.screenshot()
            if self.appear(self.I_CM_PRESENT):
                break
            if self.click(match_click[index], interval=1.5):
                continue
        # 开始捐材料
        logger.info('Start to donate')
        # 判断哪一个的材料最多
        self.screenshot()
        max_index = 0
        max_number = 0
        for i, ocr in enumerate([self.O_CM_1_MATTER, self.O_CM_2_MATTER,
                                 self.O_CM_3_MATTER, self.O_CM_4_MATTER]):
            curr, remain, total = ocr.ocr(self.device.image)
            if total > max_number:
                max_number = total
                max_index = i
        if max_number <= 30:
            logger.info('The number of all matter is less than 30')
            logger.info('Please check your game resolution')
            raise RequestHumanTakeover

        match_swipe = {
            0: self.S_CM_MATTER_1,
            1: self.S_CM_MATTER_2,
            2: self.S_CM_MATTER_3,
            3: self.S_CM_MATTER_4,
        }
        match_image = {
            0: self.I_CM_ADD_1,
            1: self.I_CM_ADD_2,
            2: self.I_CM_ADD_3,
            3: self.I_CM_ADD_4,
        }
        # 滑动到最多的材料
        random_click = [self.I_CM_ADD_1, self.I_CM_ADD_2, self.I_CM_ADD_3, self.I_CM_ADD_4]
        window_control = self.config.script.device.control_method == 'window_message'
        swipe_count = 0
        click_count = 0
        while 1:
            self.screenshot()
            if self.appear(self.I_CM_MATTER):
                break
            if not window_control and self.swipe(match_swipe[max_index], interval=2.5):
                swipe_count += 1
                time.sleep(1.5)
                continue

            # 为什么使用window_message无法滑动
            if window_control and click_count > 30:
                logger.info('Swipe to the most matter failed')
                logger.info('Please check your game resolution')
                break
            if window_control and self.click(random.choice(random_click), interval=0.7):
                click_count += 1
                continue


            if not window_control and swipe_count >= 5:
                logger.info('Swipe to the most matter failed')
                logger.info('Please check your game resolution')
                raise RequestHumanTakeover

        logger.info('Swipe to the most matter')
        # 领奖。
        #
        # 游戏规则：左中右三个任务共享每日 30 次上限，其中**只有前 10 次**完成的任务
        # 有双倍奖励（界面右下角「双倍奖励 X/10」），触发时会产生**两次**奖励弹窗。
        #
        # 但中间的任务(我爱我寮)会在日常活动里自动完成 10~30 次，通常它先把前 10 次
        # 的双倍额度吃掉 —— 之后再做左边的任务时已经没有双倍了，**只会弹一次**。
        #
        # 所以这里不能死等第 2 次弹窗：原实现以「领够 2 次」为唯一出口，
        # 遇到没双倍的情况就会一直空转，直到设备 stuck 检测（60s）抛 GameStuckError。
        reward_number = 0
        total_timer = Timer(30).start()    # 整个领奖阶段的兜底超时
        second_timer = Timer(5).start()    # 领到第 1 次后，再给第 2 次留的等待时间
        while 1:
            self.screenshot()

            if self.ui_reward_appear_click(False):
                reward_number += 1
                second_timer.reset()
                total_timer.reset()
                continue

            if reward_number >= 2:
                logger.info('双倍奖励生效，已领 2 次')
                break
            if reward_number >= 1 and second_timer.reached():
                logger.info('本次只有 1 次奖励弹窗（双倍额度已用完），继续')
                break
            if total_timer.reached():
                logger.warning(f'领奖超时，本次已领 {reward_number} 次')
                break

            if self.appear_then_click(self.I_CM_PRESENT, interval=1):
                continue
        self.ui_reward_appear_click(True)
        logger.info('Donate finished')
        return True

    def select_mission(self, missions_select: str) -> bool:
        """
        点「切换任务」把左侧的自定义任务刷新成指定的任务。

        :param missions_select: 配置里填的任务名。填类型名（"养成"、"御魂二"）
                                或者卡片上的全名（"远远不够·养成"）都能认出来 ——
                                按 '·' 右边的类型名来判，不需要照抄自定义任务名。
        :return: 换到了返回 True；填的名字认不出来、或者点了 20 次还没换到，返回 False
        """
        expect = self.classify(missions_select)
        if expect == MC.UNKNOWN:
            logger.warning(f'missions_select="{missions_select}" 认不出任务类型，'
                           f'本次不切换，直接按 missions_rule 选任务'
                           f'（喂 N 卡请填 "养成"）')
            return False

        click_cnt = 0
        while 1:
            name = self.read_card(self.O_CM_1, self.O_CM_2)
            missions = self.classify(name)
            logger.info(f"当前任务: {name}（{missions.value}）")
            logger.info(f"目标任务: {missions_select}（{expect.value}）")

            if missions == expect:
                logger.info(f"成功切换任务")
                return True
            if click_cnt > 20:
                logger.warning(f'click_cnt={click_cnt}，没换到 {expect.value}')
                return False
            if not (self.I_CM_SWITCH.match_brightness(self.device.image) and
                self.I_CM_SWITCH.match_brightness(self.device.image) and
                self.I_CM_SWITCH.match_mean_color(self.device.image, color=(134, 107, 83))
            ):
                # 无法刷新
                logger.warning(f'[SelectMission] cannot refresh, brightness/color mismatch at click_cnt={click_cnt}')
                return False
            if self.appear_then_click(self.I_CM_SWITCH, interval=2):
                logger.info(f"尝试切换任务")
                click_cnt += 1
                # 切换任务是"合法连点"：每次点击屏幕内容都在变（任务名在轮换），
                # 但框架的连点保护是按按钮计数的（device.py: 同一按钮累计 10 次就抛
                # GameTooManyClickError 并强制重启），属于误伤。
                # 清掉记录，让上面 click_cnt > 20 成为真正的安全网。
                # 同类先例：BondlingFairyland/battle.py "需要10次结契因此清空点击记录"
                self.device.click_record_clear()



    def _soul(self, index: int):
        """
        搞收御魂的任务
        :param index:
        :return:
        """
        match_click = {
            0: self.C_CM_1,
            1: self.C_CM_2,
            2: self.C_CM_3,
        }
        self.ui_click(match_click[index], self.I_SL_SUBMIT)
        while 1:
            self.screenshot()
            number_text = self.O_SL_NUMBER.ocr(self.device.image)
            submit_number = int(re.findall(r'\d+', number_text)[-1])
            if submit_number > 0:
                break

            if self.ocr_appear(self.O_SL_LEVEL):
                # 如果没有识别到这个，那就说明没有御魂可以提交了，要退出
                logger.warning('No soul can be submit')
                self.ui_click(self.I_UI_BACK_RED, self.I_CM_RECORDS)
                return False

            if self.click(self.L_SL_LONG, interval=2.5):
                time.sleep(1)
                continue
        # 领取奖励
        logger.info('Start to collect soul rewards')
        check_timer = Timer(3)
        check_timer.start()
        while 1:
            self.screenshot()
            if self.ui_reward_appear_click(True):
                check_timer.reset()
                continue
            if self.appear_then_click(self.I_SL_SUBMIT, interval=1):
                check_timer.reset()
                continue
            if check_timer.reached():
                break
        logger.info('Finish to collect soul rewards')
        self.wait_until_appear(self.I_CM_RECORDS)

    def _feed(self, index: int):
        logger.info('Start to feed soul')
        match_click = {
            0: self.C_CM_1,
            1: self.C_CM_2,
            2: self.C_CM_3,
        }
        self.ui_click(match_click[index], self.I_FEED_HEAP)
        logger.info('Submit to feed soul')
        click_list = random.sample([self.L_FEED_CLICK_1, self.L_FEED_CLICK_2, self.L_FEED_CLICK_3, self.L_FEED_CLICK_4], 2)
        # 选 N 卡，等"提交"按钮出现。
        # NOTE 必须有上限：没有 N 卡可提交（或这张卡今天已经提交过、面板没打开）时，
        #      原实现会一直长按同一批格子 -> 框架连点保护(同一按钮累计 ≥10 次)生效
        #      -> GameTooManyClickError -> 重启游戏并记一次失败。
        feed_round = 8
        for _ in range(feed_round):
            self.screenshot()
            if self.appear(self.I_FEED_SUBMIT):
                break
            for click in click_list:
                self.click(click)
            # 选卡属于"合法连点"（每次点击屏幕内容都在变），清掉记录避免被误判
            self.device.click_record_clear()
        else:
            logger.warning(f'No N card to submit (submit button not found in {feed_round} rounds), skip this mission')
            if not self.ui_click(self.I_UI_BACK_RED, self.I_CM_RECORDS, interval=1, timeout=5):
                self.ui_click(self.I_UI_BACK_YELLOW, self.I_CM_RECORDS, interval=1, timeout=5)
            return False
        logger.info('Finish to feed soul')
        # 领奖。
        #
        # 「养成」（卡片标题 "远远不够·养成"）提交 N 卡后奖励是**自动发放**的：可能一次弹窗都没有（直接回到任务列表），
        # 也可能只弹一次（前 10 次的双倍额度已被别的任务用掉时）。
        # 原实现以「领够 2 次」为唯一出口，遇到这两种情况就会一直空转，直到设备 stuck
        # 检测(60s)抛 GameStuckError —— 表现就是"提交完就呆在那里"。
        # （_donate 之前遇到过同样的问题并已修好，这里与它保持一致）
        #
        # 现在四种情况都会退出：
        #   1) 领够 2 次（双倍生效）；2) 领到 1 次后再等 5s；
        #   3) 已回到任务列表且连续 3s 没有奖励弹窗；4) 整个领奖阶段兜底 30s。
        reward_number = 0
        submitted = False
        total_timer = Timer(30).start()   # 整个领奖阶段的兜底超时
        second_timer = Timer(5).start()   # 领到第 1 次后，再给第 2 次留的等待时间
        list_timer = Timer(3).start()     # 已经回到任务列表后的确认时间
        while 1:
            self.screenshot()

            if self.ui_reward_appear_click(False):
                reward_number += 1
                second_timer.reset()
                total_timer.reset()
                list_timer.reset()
                continue

            if reward_number >= 2:
                logger.info('双倍奖励生效，已领 2 次')
                break
            if reward_number >= 1 and second_timer.reached():
                logger.info('本次只有 1 次奖励弹窗（双倍额度已用完），继续')
                break
            if total_timer.reached():
                logger.warning(f'领奖超时，本次已领 {reward_number} 次')
                break

            if self.appear_then_click(self.I_FEED_SUBMIT, interval=1):
                submitted = True
                list_timer.reset()
                continue

            if submitted and self.appear(self.I_CM_RECORDS):
                # 提交已点过、奖励弹窗也不再出现、而且人已经在任务列表上 → 奖励是自动发的
                if list_timer.reached():
                    logger.info('奖励已自动发放，已回到任务列表，结束领奖')
                    break
            else:
                list_timer.reset()
        self.ui_reward_appear_click(True)
        logger.info('Feed finished')
        return True




if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()

