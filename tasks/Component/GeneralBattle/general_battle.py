# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import random
from time import sleep

import cv2
from module.base.timer import Timer

from module.base.utils import get_color, color_similar
from tasks.base_task import BaseTask
from tasks.Component.GeneralBattle.config_general_battle import GreenMarkType, GeneralBattleConfig
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.config_general_battle import GreenMarkType, GeneralBattleConfig
from tasks.Component.GeneralBuff.config_buff import BuffClass
from tasks.Component.GeneralBuff.general_buff import GeneralBuff
from tasks.Component.GeneralBattle.battle_wait import BattleWait

from module.logger import logger


class GeneralBattle(BattleWait, GeneralBuff):
    """
    使用这个通用的战斗必须要求这个任务的config有config_general_battle
    """

    # —— 准备阶段("准备"按钮)的参数 ——
    # 点一次"准备"之后必须先等游戏反应, 不能连点: 既不像人, 也会撞上 device 的连点保护
    PREPARE_CLICK_INTERVAL = (1.0, 1.6)  # 两次"准备"之间的随机间隔(秒)
    PREPARE_CLICK_LIMIT = 6  # 单场战斗最多补点几次(连点保护: 同一按钮 10 次 / 最近 15 次点击)
    PREPARE_CLICK_WAIT = 25  # 准备阶段的补点总预算(秒)
    # battle_before 的预算用完之后, battle_wait 里还能再补点几次"准备"。
    # 背景: 2026-10-01 17:11 oas1 极逢魔, 切阵容吃掉 5 秒预算里的 4 秒, 唯一一次"准备"
    # 落在预设面板收起动画里被游戏吞掉, 之后 5 分 20 秒一次都没点 —— 画面停在准备页,
    # 因为 battle_wait 加了 BATTLE_STATUS_S(480s 长卡死), 连报错都没有, 只能人工点。
    PREPARE_RESCUE_CLICK_LIMIT = 6  # battle_wait 阶段兜底补点的次数上限
    PREPARE_RESCUE_WINDOW = 120  # 兜底补点只在这段时间内做(秒), 免得长战斗里误判乱点

    _prepare_click_count = 0  # 本场战斗已经点了几次"准备"，类属性只作默认值
    _prepare_next_click = 0.0  # 下一次允许点"准备"的时间戳

    def prepare_click_reset(self):
        """重置"准备"点击预算，每次进入一场战斗时调用"""
        self._prepare_click_count = 0
        self._prepare_next_click = 0.0

    def press_prepare(self, ignore_budget: bool = False) -> bool:
        """
        按一次"准备": 按钮亮着才按，落点仍是 RuleImage.coord() 的正态随机点，
        两次点击之间随机间隔，单场有次数上限(超了就只等不点，免得触发连点保护)。

        背景: 2026-10-01 06:26 / 06:29 两次 GameStuckError 都是"点了一次准备、
        游戏在过场动画里把这次输入丢掉、之后没人再点"导致的。
        :param ignore_budget: True 表示不受 battle_before 的 6 次预算限制,
                              给 battle_wait 阶段的兜底补点用(它自己另有次数上限)
        :return: 本次是否按下
        """
        if not ignore_budget and self._prepare_click_count >= self.PREPARE_CLICK_LIMIT:
            return False
        if time.time() < self._prepare_next_click:
            return False
        if not self.appear(self.I_PREPARE_HIGHLIGHT):
            return False
        # 先把节奏占住, 免得 appear/click 的耗时让间隔越漂越长
        self._prepare_next_click = time.time() + random.uniform(*self.PREPARE_CLICK_INTERVAL)
        x, y = self.I_PREPARE_HIGHLIGHT.coord()
        self.device.click(x, y, control_name=self.I_PREPARE_HIGHLIGHT.name)
        self._prepare_click_count += 1
        logger.info(f'Press prepare ({self._prepare_click_count}/{self.PREPARE_CLICK_LIMIT}'
                    f'{", rescue" if ignore_budget else ""})')
        return True

    def run_general_battle(self, config: GeneralBattleConfig = None, buff: BuffClass or list[BuffClass] = None) -> bool:
        """
        运行脚本
        :return:
        """
        logger.hr("General battle start", 2)
        if config is None:
            config = GeneralBattleConfig()
        # 本人选择的策略是只要进来了就算一次，不管是不是打完了
        # 战斗统计
        self.current_count += 1
        logger.info(f"Current count: {self.current_count}")
        # 本场战斗的"准备"点击预算
        self.prepare_click_reset()
        # 战前设置
        self.battle_before(buff, config)
        # 绿标
        if self.is_in_battle(False):
            self.green_mark(config.green_enable, config.green_mark)
        # 战中设置
        win = self.battle_wait(random_click_swipt_enable=config.random_click_swipt_enable)
        if win:
            return True
        else:
            return False

    def battle_before(self, buff: BuffClass | list[BuffClass], config: GeneralBattleConfig, timeout: float = 5) -> bool:
        """战斗前设置

        切阵容/开加成的耗时不占用点"准备"的预算: 以前两者共用一个 5 秒计时器，
        第一次战斗(current_count == 1)时切预设会吃掉将近 4 秒，只剩一次点"准备"的机会，
        这一次被游戏吞掉就再也没人补点了。
        :return: True: 已经进入正式战斗 False: 超时/放弃补点
        """
        fallback_timer = Timer(timeout).start()  # 只兜底"既不是准备页也不是正式战斗"的异常画面
        prepare_timer = Timer(self.PREPARE_CLICK_WAIT)  # 进了准备页才起表
        confed = False
        while 1:
            self.screenshot()
            if self.is_in_real_battle(False):  # 战斗阶段
                return True
            if self.appear_then_click(self.I_DISABLE_7DAYS_DIFF_SOUL, interval=0.6):  # 关闭御魂不一致提示
                continue
            if self.appear_then_click(self.I_CONFIRM_CLOSE_DIFF_SOUL, interval=0.6):  # 确认关闭御魂不一致提示
                continue
            if self.is_in_prepare(False):  # 战斗准备阶段
                if not prepare_timer.started():
                    prepare_timer.start()
                if not getattr(config, 'lock_team_enable', False):  # 没有锁定阵容
                    if self.current_count == 1 and not confed:  # 第一次战斗且是本次第一次配置
                        # 进切阵容之前再看一眼: 共斗战斗(逢魔boss之类)会在你切阵容的过程中
                        # 自己开打, 那时左下角从"预设"变成"自动/手动", 切阵容注定失败。
                        # 背景: 2026-10-01 17:07 / 17:10 oas2 两次 GameStuckError 就是这样。
                        if self.is_in_real_battle(False):
                            sleep(random.uniform(0.3, 0.5))
                            continue
                        self.switch_preset_team(config.preset_enable, config.preset_group, config.preset_team)
                        # 切阵容期间被队友带进战斗的话, 加成面板已经不存在了, 别再去点
                        if not self.is_in_real_battle(False):
                            self.check_and_open_buff(buff)
                        confed = True
                        # 预设面板收起需要时间, 这段时间点"准备"会被游戏吞掉。
                        # 拟人也一样: 等面板消失、按钮亮起来再按。
                        sleep(random.uniform(0.4, 0.9))
                        prepare_timer.reset()  # 配置耗时不进准备预算, 从下一轮开始计时
                        continue
                    if prepare_timer.reached() or self._prepare_click_count >= self.PREPARE_CLICK_LIMIT:
                        logger.warning(f'准备点了 {self._prepare_click_count} 次仍未进入战斗'
                                       f'({prepare_timer.current():.1f}s), 停止补点')
                        return False
                    # 点击准备(锁定阵容自动点准备,不锁定阵容前面也已经配置完毕需要点准备)
                    if not self.press_prepare():
                        sleep(random.uniform(0.3, 0.5))
                    continue
                # 锁定阵容: 游戏会自己点准备, 这里只等, 但也不能无限等
                if prepare_timer.reached():
                    logger.warning('锁定阵容下等待战斗开始超时')
                    return False
                sleep(random.uniform(0.3, 0.5))
                continue
            # 未知界面, 既不是准备界面也不是战斗界面
            # logger.info('Wait for preparation page')  # 这玩意刷屏
            if fallback_timer.reached():
                return False
            sleep(random.uniform(0.4, 0.8))
        return False

    def run_general_battle_back(self, config: GeneralBattleConfig = None, exit_four: bool = False) -> bool:
        """
        进入挑战然后直接返回
        :param config:
        :return:
        """
        # 如果没有锁定队伍那么在点击准备后才退出的,退四的话就直接退出
        if not config.lock_team_enable and not exit_four:
            # 点击准备按钮
            self.wait_until_appear(self.I_PREPARE_HIGHLIGHT, wait_time=5)
            while 1:
                self.screenshot()
                if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1.5):
                    continue
                if not (self.appear(self.I_PRESET) or self.appear(self.I_PRESET_WIT_NUMBER)):
                    break
            logger.info(f"Click {self.I_PREPARE_HIGHLIGHT.name}")

        # 点击返回
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_EXIT, interval=1.5):
                continue
            if self.appear(self.I_EXIT_ENSURE):
                break
        logger.info(f"Click {self.I_EXIT.name}")

        # 点击返回确认
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_EXIT_ENSURE, interval=1.5):
                continue
            if self.appear(self.I_FALSE):
                break
        logger.info(f"Click {self.I_EXIT_ENSURE.name}")

        # 点击失败确认
        self.wait_until_appear(self.I_FALSE)
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_FALSE, interval=1.5):
                continue
            if not self.appear(self.I_FALSE):
                break
        logger.info(f"Click {self.I_FALSE.name}")

        return True

    def exit_battle(self, skip_first: bool = False) -> bool:
        """
        在战斗的时候强制退出战斗
        :return:
        """
        if skip_first:
            self.screenshot()

        if not self.appear(self.I_EXIT):
            return False

        # 点击返回
        logger.info(f"Click {self.I_EXIT.name}")
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_EXIT, interval=1.5):
                continue
            if self.appear(self.I_EXIT_ENSURE):
                break

        # 点击返回确认
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_EXIT_ENSURE, interval=1.5):
                continue
            if self.appear_then_click(self.I_FALSE, interval=1.5):
                continue
            if not self.appear(self.I_EXIT):
                break

        return True

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        """
        等待战斗结束 ！！！
        很重要 这个函数是原先写的， 优化版本在tasks/Secret/script_task下。本着不改动原先的代码的原则，所以就不改了
        :param random_click_swipt_enable:
        :return:
        """
        # 有的时候是长战斗，需要在设置stuck检测为长战斗
        # 但是无需取消设置，因为如果有点击或者滑动的话 handle_control_check会自行取消掉
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        # 战斗过程 随机点击和滑动 防封
        logger.info("Start battle process")
        win: bool = False
        while 1:
            self.screenshot()
            # 如果出现赢 就点击, 第二个是针对封魔的图片
            if self.appear(self.I_WIN, threshold=0.8) or self.appear(self.I_DE_WIN):
                logger.info("Battle result is win")
                if self.appear(self.I_DE_WIN):
                    self.ui_click_until_disappear(self.I_DE_WIN)
                win = True
                break

            # 如果出现失败 就点击，返回False
            if self.appear(self.I_FALSE, threshold=0.8):
                logger.info("Battle result is false")
                win = False
                break

            # 如果领奖励
            if self.appear(self.I_REWARD, threshold=0.6):
                win = True
                break

            # 如果领奖励出现金币
            if self.appear(self.I_REWARD_GOLD, threshold=0.8):
                win = True
                break
            # 如果开启战斗过程随机滑动
            if random_click_swipt_enable:
                self.random_click_swipt()

        # 再次确认战斗结果
        logger.info("Reconfirm the results of the battle")
        while 1:
            self.screenshot()
            if win:
                # 点击赢了
                action_click = random.choice([self.C_WIN_1, self.C_WIN_2, self.C_WIN_3])
                if self.appear_then_click(self.I_WIN, action=action_click, interval=0.5):
                    continue
                if not self.appear(self.I_WIN):
                    break
            else:
                # 如果失败且 点击失败后
                if self.appear_then_click(self.I_FALSE, threshold=0.6):
                    continue
                if not self.appear(self.I_FALSE, threshold=0.6):
                    return False
        # 最后保证能点击 获得奖励
        if not self.wait_until_appear(self.I_REWARD, wait_time=10):
            if not self.appear(self.I_STATISTICS):
                # 有些的战斗没有下面的奖励，所以直接返回
                logger.info("There is no reward, Exit battle")
                return win
        logger.info("Get reward")
        while 1:
            self.screenshot()
            # 如果出现领奖励
            action_click = random.choice([self.C_REWARD_1, self.C_REWARD_2, self.C_REWARD_3])
            if (self.appear_then_click(self.I_REWARD, action=action_click, interval=1.5) or
                self.appear_then_click(self.I_REWARD_GOLD, action=action_click, interval=1.5)#  or
                # self.appear_then_click(self.I_REWARD_STATISTICS, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_PURPLE_SNAKE_SKIN, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_GOLD_SNAKE_SKIN, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_EXP_SOUL_4, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_SOUL_5, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_SOUL_6, action=action_click, interval=1.5)
                ):
                continue
            if self._hook_special_reward():
                continue
            if (not self.appear(self.I_REWARD) and
                not self.appear(self.I_REWARD_GOLD)  # and
                # not self.appear(self.I_REWARD_STATISTICS) and
                # not self.appear(self.I_REWARD_PURPLE_SNAKE_SKIN) and
                # not self.appear(self.I_REWARD_GOLD_SNAKE_SKIN) and
                # not self.appear(self.I_REWARD_EXP_SOUL_4) and
                # not self.appear(self.I_REWARD_SOUL_5) and
                # not self.appear(self.I_REWARD_SOUL_6)
                ):
                break

        return win

    def battle_wait_v2(self, random_click_swipt_enable: bool) -> bool:
        """
        第二版战斗等待，参考 Orochi 和 Secret 的优化版本。
        :return: 胜利返回 True，失败返回 False
        """
        # 统一点击名称，防止 GameTooManyClickError 误报
        self.C_REWARD_1.name, self.C_REWARD_2.name, self.C_REWARD_3.name = 'C_REWARD', 'C_REWARD', 'C_REWARD'
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()

        logger.info("Start battle process")
        while 1:
            self.screenshot()
            # 出现赢的鼓，点击直到消失
            if self.appear_then_click(self.I_WIN, interval=0.8):
                continue
            # 逢魔胜利图
            if self.appear(self.I_DE_WIN):
                self.ui_click_until_disappear(self.I_DE_WIN)
                continue
            if self.appear(self.I_FALSE, threshold=0.8):
                logger.warning('False battle')
                self.ui_click_until_disappear(self.I_FALSE)
                return False
            appear_ghost, appear_reward, appear_gold = (
                self.appear(self.I_GREED_GHOST),
                self.appear(self.I_REWARD),
                self.appear(self.I_REWARD_GOLD)
            )
            if appear_ghost or appear_reward or appear_gold:
                logger.info('Win battle')
                timer = Timer(20).start()
                while 1:
                    self.screenshot()

                    _appear_ghost, _appear_reward, _appear_gold = (
                        self.appear(self.I_GREED_GHOST, threshold=0.6),
                        self.appear(self.I_REWARD),
                        self.appear(self.I_REWARD_GOLD)
                    )
                    # logger.info(f'_appear_ghost: {_appear_ghost} _appear_reward: {_appear_reward} _appear_gold: {_appear_gold}')
                    if any([_appear_ghost, _appear_reward, _appear_gold]):
                        action_click = random.choice([self.C_REWARD_1, self.C_REWARD_2, self.C_REWARD_3])
                        self.click(action_click, interval=1.5)
                    else:
                        logger.info('Battle done')
                        return True
                    if self._hook_special_reward():
                        continue
                    if timer.reached_and_reset():
                        logger.warning('battle ')
                        break
            # 随机滑动
            if random_click_swipt_enable:
                self.random_click_swipt()
        return False

    def _hook_special_reward(self) -> bool:
        """
        For overwrite https://github.com/runhey/OnmyojiAutoScript/issues/1580
        """
        return False

    def green_mark(self, enable: bool = False, mark_mode: GreenMarkType = GreenMarkType.GREEN_MAIN):
        """
        绿标， 如果不使能就直接返回
        :param enable:
        :param mark_mode:
        :return:
        """
        if enable:
            logger.info("Green is enable")
            x, y = None, None
            match mark_mode:
                case GreenMarkType.GREEN_LEFT1:
                    x, y = self.C_GREEN_LEFT_1.coord()
                    logger.info("Green left 1")
                case GreenMarkType.GREEN_LEFT2:
                    x, y = self.C_GREEN_LEFT_2.coord()
                    logger.info("Green left 2")
                case GreenMarkType.GREEN_LEFT3:
                    x, y = self.C_GREEN_LEFT_3.coord()
                    logger.info("Green left 3")
                case GreenMarkType.GREEN_LEFT4:
                    x, y = self.C_GREEN_LEFT_4.coord()
                    logger.info("Green left 4")
                case GreenMarkType.GREEN_LEFT5:
                    x, y = self.C_GREEN_LEFT_5.coord()
                    logger.info("Green left 5")
                case GreenMarkType.GREEN_MAIN:
                    x, y = self.C_GREEN_MAIN.coord()
                    logger.info("Green main")

            # 等待那个准备的消失
            # 战斗没开起来时不能干等: 以前这里是死循环, 只能等 60 秒的卡死检测抛
            # GameStuckError 然后重启整个游戏(2026-10-01 06:27 / 06:30 两次报错)。
            # 现在像人一样按一次"准备", 按完给它反应时间, 有间隔也有上限。
            wait_timer = Timer(self.PREPARE_CLICK_WAIT).start()
            while 1:
                self.screenshot()
                if not self.appear(self.I_PREPARE_HIGHLIGHT):
                    self.prepare_click_reset()  # 准备页没了, 本场预算用完了
                    break
                if wait_timer.reached() or self._prepare_click_count >= self.PREPARE_CLICK_LIMIT:
                    # 补点预算用完还不开打: 继续等(交给 device 的卡死检测兜底重启),
                    # 绝不能跳出去点绿标 —— 那是在准备页上乱点式神, 会把自己点成卡死
                    sleep(random.uniform(0.4, 0.8))
                    continue
                if not self.press_prepare():
                    sleep(random.uniform(0.3, 0.5))

            # 判断有无坐标的偏移
            self.appear_then_click(self.I_LOCAL)
            time.sleep(0.3)
            # 点击绿标
            self.device.click(x, y)

    def switch_preset_team(self, enable: bool = False, preset_group: int = 1, preset_team: int = 1):
        """
        切换预设的队伍， 要求是在不锁定队伍时的情况下
        :param enable:
        :param preset_group:
        :param preset_team:
        :return:
        """
        if not enable:
            logger.info("Preset is disable")
            return None

        logger.info("Preset is enable")
        # 点击预设按钮
        # 这个循环以前没有出口: 只有"预设确认面板出现"和"队伍不足5人"两个正常分支。
        # 2026-10-01 17:07 / 17:10 oas2 两次 GameStuckError: 共斗荒骷髅战斗在切阵容的
        # 这段时间里自己开打了, 左下角变成"自动/手动", O_PRESET/O_PRESET_FULL 的
        # keyword('预'/'预设')永远匹配不上 -> 一次点击都发不出, 循环空转到 60 秒零点击,
        # 被 device 判卡死 -> 重启整个游戏客户端, 正在打的逢魔boss直接报废。
        preset_timer = Timer(12).start()  # 最迟 12 秒还没等到预设面板就放弃切阵容
        while 1:
            self.screenshot()

            if self.appear(self.I_PRESET_ENSURE):
                break
            # 首个队伍没有满足5个式神，未出现预设按钮的情况下跳出循环
            if self.appear(self.I_PRESENT_LESS_THAN_5):
                break
            # 战斗已经开打 / 已经结算: 预设面板再也不会出现, 立刻放弃切阵容
            if (self.is_in_real_battle(False) or self.appear(self.I_DE_WIN)
                    or self.appear(self.I_WIN) or self.appear(self.I_FALSE)
                    or self.appear(self.I_REWARD)):
                logger.warning('Preset panel not found, battle has already started, skip preset switch')
                return None
            if preset_timer.reached():
                logger.warning('Preset button not found in 12s, skip preset switch')
                return None
            if self.appear_then_click(self.I_PRESET, threshold=0.8, interval=1):
                continue
            if self.appear_then_click(self.I_PRESET_WIT_NUMBER, threshold=0.8, interval=1):
                continue
            if self.ocr_appear(self.O_PRESET):
                self.click(self.O_PRESET, interval=1)
                continue
            if self.ocr_appear(self.O_PRESET_FULL):
                self.click(self.O_PRESET_FULL, interval=1)
                continue
        logger.info("Click preset button")

        def get_unselect_color(tmp1, tmp2, tmp3, size):
            # 获取未选择分组的颜色，3组之中必定存在两个颜色相似
            # area 参数格式是（x1,y1,x2,y2）
            color_1 = get_color(self.device.image,
                                (tmp1.roi_back[0], tmp1.roi_back[1],
                                 tmp1.roi_back[0] + size[0], tmp1.roi_back[1] + size[1]))
            color_2 = get_color(self.device.image,
                                (tmp2.roi_back[0], tmp2.roi_back[1],
                                 tmp2.roi_back[0] + size[0], tmp2.roi_back[1] + size[1]))
            color_3 = get_color(self.device.image,
                                (tmp3.roi_back[0], tmp3.roi_back[1],
                                 tmp3.roi_back[0] + size[0], tmp3.roi_back[1] + size[1]))

            if color_similar(color_1, color_2):
                return color_1
            if color_similar(color_2, color_3):
                return color_2
            return color_3

        # 选择预设组
        tmp = self.__getattribute__("C_PRESET_GROUP_" + str(preset_group))
        if tmp is None:
            tmp = self.C_PRESET_GROUP_1
        color_size = [self.C_PRESET_GROUP_1.roi_back[2],
                      self.C_PRESET_GROUP_1.roi_back[3]]
        # unselected_color = get_unselect_color(self.C_PRESET_GROUP_1, self.C_PRESET_GROUP_2, self.C_PRESET_GROUP_3, size=color_size)
        # 考虑到有些预设组没有预设，所以这里取一个比较固定的颜色
        unselected_color = (224.9, 208.3, 187.4)
        while True:
            self.screenshot()
            color_tmp = get_color(self.device.image,
                                  (tmp.roi_back[0], tmp.roi_back[1], tmp.roi_back[0] + color_size[0],
                                   tmp.roi_back[1] + color_size[1]))
            if color_similar(color_tmp, unselected_color):
                self.click(tmp, interval=0.2)
                continue
            break

        logger.info("Select preset group")

        # 选择预设的队伍
        time.sleep(0.5)
        tmp = self.__getattribute__("C_PRESET_TEAM_" + str(preset_team))
        if tmp is None:
            tmp = self.C_PRESET_TEAM_1
        color_size = [5, 5]
        # unselected_color = get_unselect_color(self.C_PRESET_TEAM_1, self.C_PRESET_TEAM_2, self.C_PRESET_TEAM_3, size=color_size )
        unselected_color = (216.8, 185.0, 146.8)
        while True:
            self.screenshot()
            color_tmp = get_color(self.device.image,
                                  (tmp.roi_back[0], tmp.roi_back[1], tmp.roi_back[0] + color_size[0],
                                   tmp.roi_back[1] + color_size[1]))
            if color_similar(color_tmp, unselected_color):
                self.click(tmp, interval=0.2)
                continue
            break

        self.click(tmp)
        logger.info("Select preset team")

        # 点击预设确认
        self.wait_until_appear(self.I_PRESET_ENSURE, wait_time=1)
        click_timer = Timer(10).start()
        while 1:
            self.screenshot()
            if click_timer.reached():
                logger.warning("Switch preset failure")
            if not self.appear(self.I_PRESET_ENSURE):
                break
            if self.appear_then_click(self.I_PRESET_ENSURE, threshold=0.8, interval=1):
                continue
        logger.info("Click preset ensure")
        return None

    def random_click_swipt(self):
        if 0 <= random.randint(0, 500) <= 3:  # 百分之4的概率
            rand_type = random.randint(0, 2)
            match rand_type:
                case 0:
                    self.click(self.C_RANDOM_CLICK, interval=20)
                case 1:
                    self.swipe(self.S_BATTLE_RANDOM_LEFT, interval=20)
                case 2:
                    self.swipe(self.S_BATTLE_RANDOM_RIGHT, interval=20)
            # 重新设置为长战斗
            # self.device.stuck_record_add('BATTLE_STATUS_S')
        else:
            time.sleep(0.4)  # 这样的好像不对

    # 判断是否在战斗中
    def is_in_battle(self, is_screenshot: bool = True) -> bool:
        """
        判断是否在战斗中
        tip: 因为有friends判别, 所以即使在准备界面也会识别在战斗中
        :return:
        """
        if is_screenshot:
            self.screenshot()
        if self.appear(self.I_BATTLE_INFO) or \
                self.appear(self.I_FRIENDS) or \
                self.appear(self.I_WIN) or \
                self.appear(self.I_FALSE) or \
                self.appear(self.I_REWARD):
            return True
        else:
            return False

    def is_in_real_battle(self, is_screenshot: bool = True):
        """
        判断是否在真正的战斗中(不是战斗准备界面也不是战斗结束界面)
        :param is_screenshot:
        :return:
        """
        if is_screenshot:
            self.screenshot()
        return self.appear(self.I_BATTLE_INFO)

    def is_in_prepare(self, is_screenshot: bool = True) -> bool:
        """
        判断是否在准备中
        :return:
        """
        if is_screenshot:
            self.screenshot()
        if self.appear(self.I_BUFF):
            return True
        elif self.appear(self.I_PREPARE_HIGHLIGHT):
            return True
        elif self.appear(self.I_PREPARE_DARK):
            return True
        elif self.appear(self.I_PRESET) or self.appear(self.I_PRESET_WIT_NUMBER):
            return True
        else:
            return False

    def check_take_over_battle(self, is_screenshot: bool, config: GeneralBattleConfig) -> bool or None:
        """
        中途接入战斗，并且接管
        :return:  赢了返回True， 输了返回False, 不是在战斗中返回None
        """
        if is_screenshot:
            self.screenshot()
        if not self.is_in_battle():
            return None

        return self.run_general_battle(config=config)

    def check_lock(self, enable: bool, lock_image, unlock_image):
        """
        检测是否锁定队伍，
        :param enable:
        :param lock_image:
        :param unlock_image:
        :return:
        """
        if enable:
            logger.info("Lock team")
            while 1:
                self.screenshot()
                if self.appear(lock_image):
                    break
                if self.appear_then_click(unlock_image, interval=1):
                    continue
        else:
            logger.info("Unlock team")
            while 1:
                self.screenshot()
                if self.appear(unlock_image):
                    break
                if self.appear_then_click(lock_image, interval=1):
                    continue

    def check_and_open_buff(self, buff: BuffClass or list[BuffClass] = None):
        """
        检测是否开启buff
        :param buff:
        :return:
        """
        if not buff:
            return
        logger.info(f'Open buff {buff}')
        self.ui_click(self.I_BUFF, self.I_CLOUD, interval=2)
        if isinstance(buff, BuffClass):
            buff = [buff]
        match_method = {
            BuffClass.AWAKE: (self.awake, True),
            BuffClass.SOUL: (self.soul, True),
            BuffClass.GOLD_50: (self.gold_50, True),
            BuffClass.GOLD_100: (self.gold_100, True),
            BuffClass.EXP_50: (self.exp_50, True),
            BuffClass.EXP_100: (self.exp_100, True),
            BuffClass.AWAKE_CLOSE: (self.awake, False),
            BuffClass.SOUL_CLOSE: (self.soul, False),
            BuffClass.GOLD_50_CLOSE: (self.gold_50, False),
            BuffClass.GOLD_100_CLOSE: (self.gold_100, False),
            BuffClass.EXP_50_CLOSE: (self.exp_50, False),
            BuffClass.EXP_100_CLOSE: (self.exp_100, False),
        }
        for b in buff:
            func, is_open = match_method[b]
            func(is_open)
            time.sleep(0.1)
        logger.info(f'Open buff success')
        while 1:
            self.screenshot()
            if not self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF, interval=1):
                continue

    def boss_mark(self, enable=True) -> bool:
        if not enable or self._boss_mark_flag:
            return False
        if self.ocr_appear(self.O_BOSS_MARK):
            self.screenshot()
            if self.ocr_appear(self.O_BOSS_MARK):
                self._boss_mark_flag = True
                logger.info('Boss marked')
                self.device.stuck_record_add('BATTLE_STATUS_S')
                return True
        if self.device.click_record.count(str(self.O_BOSS_MARK)) >= 3:
            self._boss_mark_flag = True
            logger.info('Boss mark skipped due to maybe no boss')
            self.device.stuck_record_add('BATTLE_STATUS_S')
            return False
        if self.click(self.O_BOSS_MARK, interval=1.8):
            return False
        return False

    def boss_mark_reset(self):
        self._boss_mark_flag = False


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = GeneralBattle(c, d)
    self = t
    # t.check_buff([BuffClass.EXP_50, BuffClass.GOLD_50])

    img = cv2.imread(r"E:\preset3.png")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    self.device.image = img


    def get_unselect_color(tmp1, tmp2, tmp3, size):
        # 获取未选择分组的颜色，3组之中必定存在两个颜色相似
        # area 参数格式是（x1,y1,x2,y2）
        color_1 = get_color(self.device.image,
                            (tmp1.roi_back[0], tmp1.roi_back[1],
                             tmp1.roi_back[0] + size[0], tmp1.roi_back[1] + size[1]))
        color_2 = get_color(self.device.image,
                            (tmp2.roi_back[0], tmp2.roi_back[1],
                             tmp2.roi_back[0] + size[0], tmp2.roi_back[1] + size[1]))
        color_3 = get_color(self.device.image,
                            (tmp3.roi_back[0], tmp3.roi_back[1],
                             tmp3.roi_back[0] + size[0], tmp3.roi_back[1] + size[1]))

        if color_similar(color_1, color_2):
            return color_1
        if color_similar(color_2, color_3):
            return color_2
        return color_3


    color_size = [self.C_PRESET_GROUP_1.roi_back[2],
                  self.C_PRESET_GROUP_1.roi_back[3]]
    unselected_color = get_unselect_color(self.C_PRESET_GROUP_1, self.C_PRESET_GROUP_2, self.C_PRESET_GROUP_3,
                                          size=color_size)
    color_size = [5, 5]
    unselected_color = get_unselect_color(self.C_PRESET_TEAM_1, self.C_PRESET_TEAM_2, self.C_PRESET_TEAM_3,
                                          size=color_size
                                          )
