# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
"""收菜(登录后领奖励)

这个模块原先是 tasks/Restart/login.py 的一部分: 游戏重启 -> 登录 -> 顺手把日常奖励点一遍。
现在收菜是独立任务, 登录流程通过 HarvestHandler.harvest() 复用同一份逻辑。

NOTE 图片规则仍然放在 tasks/Restart/harvest/ 下(assets_extract 生成的 RestartAssets 里),
     这里只是复用, 不做搬运, 免得规则表和已生成的 assets.py 对不上。
"""
from module.base.timer import Timer
from module.logger import logger
from tasks.GameUi.game_ui import GameUi
from tasks.Restart.assets import RestartAssets


class HarvestHandler(GameUi, RestartAssets):
    """
    收菜的公共执行体: 可以被独立的 Harvest 任务调用,
    也可以被 Restart 的登录流程调用(app_handle_login -> harvest)。

    NOTE 继承 GameUi(而不是 BaseTask): 收菜任务要先 ui_goto(page_main) 回庭院,
         ui_goto 在 GameUi 里。其它任务(DailyTrifles / Delegation 等)也都是继承 GameUi,
         少了这一层跑起来就是 AttributeError: 'ScriptTask' object has no attribute 'ui_goto'。
    """

    def harvest(self, skip_courtyard: bool = False):
        """
        获得奖励
        :param skip_courtyard: 跳过庭院事务(庭院事务只会由收菜任务自己去点)
        :return: 如果没有发现任何奖励后退出
        """
        logger.hr('Harvest')
        timer_harvest = Timer(5)  # 如果连续5秒没有发现任何奖励，退出
        skip_default = False
        courtyard_affairs_done = False  # 庭院事务只执行一次
        while 1:
            self.device.screenshot()
            # https://github.com/runhey/OnmyojiAutoScript/pull/1761
            if not self.device.check_screen_size_sample():
                continue
            self._burst()

            # 点击'获得奖励'
            if self.ui_reward_appear_click():
                timer_harvest.reset()
                continue
            # 获得奖励
            if self.appear_then_click(self.I_UI_AWARD, interval=0.2):
                timer_harvest.reset()
                continue
            # 偶尔会打开到聊天频道
            if self.appear_then_click(self.I_HARVEST_CHAT_CLOSE, interval=1):
                timer_harvest.reset()
                continue
            # 偶尔会进入其他页面
            # 左上角的黄色关闭
            if self.appear_then_click(self.I_LOGIN_YELLOW_CLOSE, interval=0.6):
                timer_harvest.reset()
                logger.info('Close yellow close')
                continue
            # 关闭宠物小屋
            if self.appear_then_click(self.I_HARVEST_BACK_PET_HOUSE, interval=0.6):
                timer_harvest.reset()
                logger.info('Close yellow close')
                continue
            # 御魂溢确认
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2.5):
                timer_harvest.reset()
                skip_default = True
                logger.info('Soul overflow')
                continue
            # 关闭姿度出现的蒙版
            if self.appear(self.I_HARVEST_ZIDU, interval=1):
                timer_harvest.reset()
                self.I_HARVEST_ZIDU.roi_front[0] -= 200
                self.I_HARVEST_ZIDU.roi_front[1] -= 200
                if self.click(self.I_HARVEST_ZIDU, interval=2):
                    logger.info('Close zidu')
                continue

            # 庭院事务
            if not skip_courtyard and self.config.harvest.harvest_config.enable_courtyard_affairs \
                    and not courtyard_affairs_done:
                self.harvest_courtyard_affairs()
                timer_harvest.reset()
                courtyard_affairs_done = True
                continue
            # 勾玉
            if self.config.harvest.harvest_config.enable_jade \
                    and self.appear_then_click(self.I_HARVEST_JADE, interval=1.5):
                timer_harvest.reset()
                continue
            # 签到
            if self.config.harvest.harvest_config.enable_sign \
                    and self.appear_then_click(self.I_HARVEST_SIGN, interval=1.5):
                self.wait_until_appear(self.I_HARVEST_SIGN_2, wait_time=2)
                timer_harvest.reset()
                continue
            # 某些活动的特殊签到，有空看到就删掉
            if self.config.harvest.harvest_config.enable_sign \
                    and self.appear_then_click(self.I_HARVEST_SIGN_3, interval=0.7):
                timer_harvest.reset()
                continue
            if self.config.harvest.harvest_config.enable_sign \
                    and self.appear_then_click(self.I_HARVEST_SIGN_4, interval=1):
                timer_harvest.reset()
                continue
            if self.config.harvest.harvest_config.enable_sign \
                    and self.appear_then_click(self.I_HARVEST_SIGN_2, interval=1.5):
                self.wait_until_appear(self.I_LOGIN_RED_CLOSE, wait_time=2)
                timer_harvest.reset()
                continue
            # 999天的签到福袋
            if self.config.harvest.harvest_config.enable_sign_999 \
                    and self.appear_then_click(self.I_HARVEST_SIGN_999, interval=1.5):
                timer_harvest.reset()
                continue
            # 判断是否勾选了收取邮件（不收取邮件可以查看每日收获）
            if not skip_default and self.config.harvest.harvest_config.enable_mail and self.harvest_mail():
                timer_harvest.reset()
                continue
            if self.config.harvest.harvest_config.enable_ap \
                    and self.appear_then_click(self.I_HARVEST_AP, interval=1, threshold=0.7):
                timer_harvest.reset()
                continue
            # 御魂觉醒加成
            if self.config.harvest.harvest_config.enable_soul \
                    and self.appear_then_click(self.I_HARVEST_SOUL, interval=1):
                timer_harvest.reset()
                continue
            # 寮包
            if self.appear_then_click(self.I_HARVEST_GUILD_REWARD, interval=2):
                timer_harvest.reset()
                continue
            # 自选御魂
            if not skip_default and self.appear(self.I_HARVEST_SOUL_1):
                logger.info('Select soul 2')
                self.ui_click(self.I_HARVEST_SOUL_1, stop=self.I_HARVEST_SOUL_2)
                self.ui_click(self.I_HARVEST_SOUL_2, stop=self.I_HARVEST_SOUL_3, interval=3)
                self.ui_click_until_disappear(click=self.I_HARVEST_SOUL_3)
                timer_harvest.reset()

            # 红色的关闭
            if self.appear(self.I_LOGIN_RED_CLOSE):
                self.click(self.I_LOGIN_RED_CLOSE, interval=2)
                timer_harvest.reset()
                continue

            # 五秒内没有发现任何奖励，退出
            if not timer_harvest.started():
                timer_harvest.start()
            else:
                if timer_harvest.reached():
                    logger.info('No more reward')
                    return

    def harvest_mail(self) -> bool:
        if not self.appear_multi_scale(self.I_HARVEST_MAIL, scale_range=(0.8, 1.1)) and \
                not self.appear(self.I_HARVEST_MAIL_COPY):
            if not self.appear(self.I_READ_ALL_MAIL):
                return False
        logger.info('Harvest mail')
        while 1:
            self.screenshot()
            if self.appear(self.I_READ_ALL_MAIL):
                break
            if self.appear_then_click_multi_scale(self.I_HARVEST_MAIL, interval=1.5, scale_range=(0.8, 1.1)):
                continue
            if self.appear_then_click(self.I_HARVEST_MAIL_COPY, interval=1.5):
                continue
        timeout_timer = Timer(3).start()
        logger.info('Exec harvest mail')
        while 1:
            self.screenshot()
            if timeout_timer.reached():
                break
            if self.appear_then_click(self.I_HARVEST_MAIL_CONFIRM, interval=0.8):
                break

            if self.appear_then_click(self.I_READ_ALL_MAIL, interval=1.5):
                continue
            if self.appear_then_click(self.I_HARVEST_MAIL_ALL, interval=1.5):
                continue
            if self.appear_then_click(self.I_MAIL_RED_POINT, interval=4):
                continue
        self.ui_click_until_disappear(self.I_LOGIN_RED_CLOSE)
        return True

    def harvest_courtyard_affairs(self) -> bool:
        if not self.ui_click_multi_scale(self.I_NOTE, self.I_PAGE, timeout=3, scale_range=(0.8, 1.2)):
            logger.warning('courtyard affairs timeout!')
            return False
        count_success = 0
        while 1:
            self.screenshot()
            if self.appear(self.I_NO_TASKS):
                logger.info('courtyard affairs completed！')
                break
            # 每日六星御魂
            if self.appear_then_click(self.I_HARVEST_SOUL_2, interval=1) \
                    or self.appear_then_click(self.I_HARVEST_SOUL_3, interval=1):
                continue
            # 点击'获得奖励'
            if self.ui_reward_appear_click():
                continue
            # 获得奖励
            if self.appear_then_click(self.I_UI_AWARD, interval=0.2):
                continue
            # 式神满级，是否提取物经验？确定
            if self.appear_then_click(self.I_CONFIRM, interval=1):
                continue

            if self.appear_then_click(self.I_DAILY, interval=1):
                continue
            # 领取成功： 太傻逼了收取结界奖励游戏里面居然没有加上限制
            if self.appear_then_click(self.I_SUCCESS_CLAIMED, interval=1):
                continue
            if self.appear_then_click(self.I_SKIP):# 万花牌跳过
                continue
            if self.appear_then_click(self.I_LOGIN_RED_CLOSE, interval=1):# 万花牌X
                continue
            # 一键完成
            if count_success >= 3:
                logger.info(f'Click complete tasks {count_success} times')
                break
            if self.appear_then_click(self.I_COMPLETE_TASKS, interval=2.3):
                count_success += 1
                continue
        return True

    def execute(self, skip_courtyard: bool = False):
        """
        收菜任务的执行入口: 游戏没起来就登录, 然后收菜。
        需要在庭院界面调用(独立任务会先保证登录完成)。
        """
        self.harvest(skip_courtyard=skip_courtyard)
