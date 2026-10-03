# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep
from datetime import timedelta, datetime, time
from cached_property import cached_property

from module.exception import TaskEnd
from module.logger import logger
from module.base.timer import Timer

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_hunt, page_shikigami_records, page_guild
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralInvite.general_invite import GeneralInvite
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.DemonRetreat.assets import DemonRetreatAssets
from tasks.AbyssShadows.assets import AbyssShadowsAssets
from tasks.DemonRetreat.config import DemonRetreat
from tasks.Component.config_base import Time
from tasks.Component.activity_window import RETRY_WINDOW, activity_target, in_retry_window

class ScriptTask(GameUi, GeneralBattle, SwitchSoul, DemonRetreatAssets, AbyssShadowsAssets):

    def retreat_run_time(self) -> Time:
        """内置的周六退治开打时刻(游戏里周六 10:00~23:00 由会长/副会长开)

        NOTE 脚本进程还没重启时, 老配置模型里可能没有这个字段(或还是旧字段名 custom_run_time),
             此时退回默认 10:00 而不是让任务报错
        """
        cfg: DemonRetreat = self.config.demon_retreat
        run_time = getattr(cfg.demon_retreat_time, 'custom_run_time_saturday', None)
        if run_time is None:
            run_time = getattr(cfg.demon_retreat_time, 'custom_run_time', None)
        if run_time is None:
            logger.warning("custom_run_time_saturday not found in config model, use default 10:00 "
                           "(restart the script process to enable this option)")
            run_time = Time(hour=10, minute=0, second=0)
        return run_time

    @staticmethod
    def days_until_saturday(today: int = None) -> int:
        """距离下一个周六的天数(周一=0; 周六当天返回 0)"""
        today = datetime.now().weekday() if today is None else today
        return (5 - today) % 7

    def plan_next_saturday(self, run_time: Time) -> None:
        """排到下一个周六的内置退治时刻

        内置时间的关键: 不管任务是哪天被拉起来的(比如暂停很久后重启),
        排期都会回到"下一个周六的配置时刻", 不跟着这次运行的时间漂移
        """
        # 周六当天跑完 -> 排到 7 天后的同一时刻
        delta = self.days_until_saturday() or 7
        logger.info(f"Plan next run: {delta} day(s) later at {run_time}")
        self.custom_next_run(task='DemonRetreat', custom_time=run_time,
                             time_delta=delta, server=False)

    def plan_after_failure(self, run_time: Time, finish: bool) -> None:
        """退治没进去/打失败时的排期

        - 开打时刻前 30 分钟 ~ 后 1 小时(activity_window 的 LEAD_WINDOW/RETRY_WINDOW): 按失败间隔重试(仍在当天)
        - 比这更早(被提前拉起): 直接排到今天那一刻, 不空跑
        - 超出窗口: 放弃当天, 排到下周六
        """
        now = datetime.now()
        target = activity_target(now, run_time)
        if in_retry_window(now, run_time):
            # 活动时刻前 30 分钟 ~ 后 1 小时: 按失败间隔重试(仍在当天)
            self.set_next_run(task='DemonRetreat', finish=finish, server=False, success=False)
        elif now < target:
            logger.info(f"Demon retreat starts at {run_time}, wait until {target}")
            self.set_next_run(task='DemonRetreat', target=target, server=False)
        else:
            logger.warning(f"Retry window({RETRY_WINDOW}) exceeded, the next time is next Saturday")
            self.plan_next_saturday(run_time)

    def run(self):
        """
        首领退治主函数
        """

        cfg: DemonRetreat = self.config.demon_retreat
        # 内置的退治开打时刻, 排程全部以它为基准(server=False)
        run_time = self.retreat_run_time()

        # 判断是否为周六，只有周六才可以进行退治
        current_day_of_week = datetime.now().weekday()  # Monday is 0 and Sunday is 6

        if current_day_of_week == 5:
            # 是周六，继续运行写好的任务代码
            pass
        else:
            # 不是周六: 直接排到下周六的内置时刻
            self.plan_next_saturday(run_time)
            raise TaskEnd

        if cfg.switch_soul_config.enable:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(cfg.switch_soul_config.switch_group_team)
        if cfg.switch_soul_config.enable_switch_by_name:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul_by_name(cfg.switch_soul_config.group_name, cfg.switch_soul_config.team_name)

        # 进入妖怪退治
        if not self.goto_demon_retreat():
            logger.warning("Failed to enter demon retreat")
            if self.back_from_rank_panel():
                pass
            self.goto_main()
            self.plan_after_failure(run_time, finish=False)
            raise TaskEnd

        # 首领退治战斗
        success = self.demon_retreat()

        # 战斗结束 回到寮信息界面 准备领取奖励
        # 先返回
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_PRAY, interval=1):
                logger.warning("Claim rewards")
            if self.appear_then_click(self.I_HUNT, interval=1):
                continue
            if self.appear_then_click(self.I_REWARD_ALL, interval=1.5):
                self.ui_reward_appear_click(True)
                logger.info('Claim rewards finished')
                break
            if self.appear(self.I_RANK_LSIT):
                logger.info("No rewards to claim")
                if self.back_from_rank_panel():
                    break

        # 保持好习惯，一个任务结束了就返回到庭院，方便下一任务的开始
        self.goto_main()

        # 设置下次运行时间
        if success:
            logger.info(f"The next time the demon retreat is next Saturday")
            self.plan_next_saturday(run_time)
        else:
            self.plan_after_failure(run_time, finish=True)

        raise TaskEnd



    def back_from_rank_panel(self) -> bool:
        """关掉"伤害排名"面板(左上返回键)

        NOTE 任务自带的 I_DEMON_BACK_CHECK 是坏素材: 2026-10-03 那几帧只有 0.6969
             (阈值 0.7, 历史全部截图最高 0.7187), 差一点点就是点不到 -> 面板一直开着 ->
             goto_demon_retreat 每轮都判"没进去"。这里补上通用的页面返回键(同帧 0.9670)。
        """
        return (self.appear_then_click(self.I_BACK_Y, interval=1)
                or self.appear_then_click(self.I_DEMON_BACK_CHECK, interval=1))

    def goto_demon_retreat(self) -> bool:
        """
        进入首领退治
        """
        self.ui_get_current_page()
        logger.info("Entering demon_retreat")
        self.ui_goto(page_guild)

        goto_demon_retreat_num = 0
        # 面板关不掉时的兜底: 这个循环原来只靠 I_HUNT 的出现次数计数(goto_demon_retreat_num),
        # 而面板一挡住 I_HUNT 就再也不出现 -> 计数器永远是 1 -> 无限循环
        # (2026-10-03 实测 58~83 轮 × (sleep3+sleep20) ≈ 22~32 分钟, 全程零点击, 最后被 device 的
        #  "60 秒 + 60 张截图无点击"卡死检测打断; 又因为卡死不走任务的排期逻辑, next_run 一直是
        #  过期的 19:20, 调度器立刻重排 -> 一轮又一轮地空跑)。现在按轮次 + 限时双重兜底,
        # 到点就优雅失败, 交给 run() 里的 plan_after_failure 去排期(窗口内重试 / 排下周六)。
        attempt = 0
        give_up_timer = Timer(90).start()
        while 1:
            self.screenshot()
            # 有界兜底放在 continue 之前, 免得被"进入神社"那条 continue 绕过
            attempt += 1
            if goto_demon_retreat_num >= 5 or attempt > 5 or give_up_timer.reached():
                logger.warning(f'Cannot enter demon retreat (clicked hunt {goto_demon_retreat_num} times, '
                               f'{attempt} rounds, {give_up_timer.current():.0f}s), give up this run')
                break
            # 进入神社
            if self.appear_then_click(self.I_SHRINE, interval=1):
                logger.info("Enter I_SHRINE")
                continue
            # 进入首领退治
            if self.appear_then_click(self.I_HUNT, interval=1.5):
                goto_demon_retreat_num += 1

            # 确保不离开退治
            if self.appear_then_click(self.I_QUIT_BACK, interval=1):
                pass
            if (self.appear(self.I_HUNT_CHECK)
                    or self.appear(self.I_DEMON_GATHER)
                    or self.is_in_prepare(False)):
                if self.appear_then_click(self.I_QUIT_BACK, interval=1):
                    pass
                logger.info("Enter demon_retreat success")
                return True

            # 周六打完了，但是迟到了只能领取奖励
            if self.appear_then_click(self.I_REWARD_ALL, interval=1):
                logger.info("Already challenged demon_retreat")
                sleep(1)
                if self.back_from_rank_panel():
                    pass
                logger.info(f"The next time the demon retreat is next Saturday")
                self.plan_next_saturday(self.retreat_run_time())
                raise TaskEnd

            if self.appear(self.I_RANK_LSIT):
                logger.info("Enter demon_retreat false")
                sleep(3)
                if self.back_from_rank_panel():
                    pass
                sleep(20)
        return False

    def demon_retreat(self):
        cfg: DemonRetreat = self.config.demon_retreat
        logger.hr('demon retreat', 2)

        # 来晚了直接进入战斗
        if not set(self.O_LATER_ENTER_CHECK.ocr(image=self.device.image)).intersection(set("集结")):
            logger.info("arrive later")
            self.ui_click_until_disappear(self.I_ENTER_FIRE, interval=1)
            self.device.stuck_record_add('BATTLE_STATUS_S')
            success = self.run_demon_battle(cfg.general_battle)
        else:
            # 等待进入战斗
            sleep(5)
            self.device.stuck_record_add('BATTLE_STATUS_S')
            self.wait_until_disappear(self.I_DEMON_GATHER)
            self.device.stuck_record_clear()
            self.device.stuck_record_add('BATTLE_STATUS_S')
            success = self.run_demon_battle(cfg.general_battle)

        return success




    def run_demon_battle(self, config: GeneralBattleConfig = None) -> bool:
        """
        重写通用战斗
        三轮战斗 战斗过程中检测挑战
        """
        # TODO 战斗过程中切换预设
        logger.hr("General battle start", 2)
        self.current_count += 1
        logger.info(f"Current count: {self.current_count}")
        if config is None:
            config = GeneralBattleConfig()

        # 如果没有锁定队伍。那么可以根据配置设定队伍
        if not config.lock_team_enable:
            logger.info("Lock team is not enable")
            # 如果更换队伍
            if self.current_count == 1:
                self.switch_preset_team(config.preset_enable, config.preset_group, config.preset_team)

            # 点击准备按钮
            self.wait_until_appear(self.I_PREPARE_HIGHLIGHT)
            self.wait_until_appear(self.I_BUFF)
            while 1:
                self.screenshot()
                if not self.appear(self.I_BUFF):
                    break
                if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1.5):
                    continue

            logger.info("Click prepare ensure button")

            # 照顾一下某些模拟器慢的
            sleep(0.1)

        # 绿标
        self.wait_until_disappear(self.I_BUFF)
        if self.is_in_battle(False):
            self.green_mark(config.green_enable, config.green_mark)

        win = self.battle_wait(config.random_click_swipt_enable)
        if win:
            return True
        else:
            return False




    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        """
        重写 三轮战斗 战斗过程中点击准备 返回到寮信息界面
        :param random_click_swipt_enable:
        :return:
        """
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        # 战斗过程 随机点击和滑动 防封 并点击 准备
        logger.info("Start battle process")
        stuck_timer = Timer(180)
        stuck_timer.start()
        while 1:
            self.screenshot()
            if self.appear(self.I_WIN):
                logger.info('Battle win')
                self.ui_click_until_disappear(self.I_WIN)
                return True
            # 战斗过程中出现准备
            if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1.5):
                self.device.stuck_record_clear()
                self.device.stuck_record_add('BATTLE_STATUS_S')
            # 如果出现失败 就点击，返回False
            if self.appear(self.I_FALSE, threshold=0.8):
                logger.info("Battle result is false")
                self.ui_click_until_disappear(self.I_FALSE)
                return False
            # 如果三分钟还没打完，再延长五分钟
            if stuck_timer and stuck_timer.reached():
                stuck_timer = None
                self.device.stuck_record_clear()
                self.device.stuck_record_add('BATTLE_STATUS_S')


    def goto_main(self):
        ''' 保持好习惯，一个任务结束了就返回庭院，方便下一任务的开始或者是出错重启
        '''
        self.ui_get_current_page()
        logger.info("Exiting DemonRetreat")
        self.ui_goto(page_main)






if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('日常1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()

