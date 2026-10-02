# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import random
from module.base.timer import Timer
from module.exception import RequestHumanTakeover, GameTooManyClickError, GameStuckError
from module.logger import logger
from tasks.Restart.assets import RestartAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.Component.GeneralBuff.assets import GeneralBuffAssets
from tasks.base_task import BaseTask

class LoginMixin:
    """
    登录流程的公共实现。

    使用者必须自己提供资产/引擎基类:
      - LoginHandler: BaseTask + RestartAssets + GameUiAssets + GeneralBuffAssets
      - tasks.Harvest.ScriptTask: GameUi(含 GameUiAssets) + RestartAssets
    """

    character: str

    def __init__(self, *wargs, **kwargs):
        super().__init__(*wargs, **kwargs)
        self.character = self.config.restart.login_character_config.character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = self.character

    def _app_handle_login(self) -> bool:
        """
        最终是在庭院界面
        :return:
        """
        logger.hr('App login')
        self.device.stuck_record_add('LOGIN_CHECK')

        confirm_timer = Timer(1.5, count=2).start()
        orientation_timer = Timer(10)
        login_success = False

        while 1:
            # Watch device rotation
            if not login_success and orientation_timer.reached():
                # Screen may rotate after starting an app
                self.device.get_orientation()
                orientation_timer.reset()

            self.device.screenshot()
            # https://github.com/runhey/OnmyojiAutoScript/pull/1761
            if not self.device.check_screen_size_sample():
                continue
            self._burst()

            # 取消继续战斗
            if self.appear_then_click(self.I_CANCEL_BATTLE, interval=0.8):
                logger.info('Cancel continue battle')
                continue
            # 确认进入庭院(优化：先检测加成图标确认在庭院页面，再检测式神录图标)
            if self.appear(self.I_BUFF_1, interval=0.2):
                # 加成图标存在，确认在庭院页面
                if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.2):
                    # 式神录图标存在，认为已在庭院
                    if confirm_timer.reached():
                        logger.info('Login to main confirm (buff and shikigami records button appears)')
                        break
                    login_success = True
                else:
                    # 式神录图标不存在，点击展开卷轴
                    if self.click(self.C_LOGIN_SCROLL_CLOSE_AREA, interval=2):
                        logger.info('Click scroll expand area because shikigami records not found')
                        self.screenshot()
                        continue
                    confirm_timer.reset()

            # 网络异常
            # if self.ocr_appear(self.O_LOGIN_NETWORK):
            #     logger.error('Network error')
            #     raise RequestHumanTakeover('Network error')

            # 跳过观看视频
            # if self.ocr_appear_click(self.O_LOGIN_SKIP_1, interval=1):
            #     continue
            # 下载插画
            if self.appear_then_click(self.I_LOGIN_LOAD_DOWN, interval=1):
                logger.info('Download inbetweening')
                continue
            # 不观看视频
            if self.appear_then_click(self.I_WATCH_VIDEO_CANCEL, interval=0.6):
                logger.info('Close video')
                continue
            # 右上角的红色的关闭
            if self.appear_then_click(self.I_LOGIN_RED_CLOSE, interval=0.6):
                logger.info('Close red close')
                continue
            # 左上角的黄色关闭
            if self.appear_then_click(self.I_LOGIN_YELLOW_CLOSE, interval=0.6):
                logger.info('Close yellow close')
                continue
            # 绑定手机号弹窗
            if self.appear_then_click(self.I_LOGIN_LOGIN_GOTO_BIND_PHONE):
                while 1:
                    self.screenshot()
                    if self.appear_then_click(self.I_LOGIN_LOGIN_CANCEL_BIND_PHONE):
                        logger.info("Close bind phone")
                        break
                continue
            # 关闭各种邀请弹窗(主要时结界卡寄养邀请)
            from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
            if self.appear_then_click(gia.I_I_REJECT, interval=0.8):
                logger.info("reject invites")
                continue
            # 关闭阴阳师精灵提示
            if self.appear_then_click(self.I_LOGIN_LOGIN_ONMYOJI_GENIE):
                logger.info("click onmyoji genie")
                continue
            # 点击屏幕进入游戏
            if self.appear(self.I_LOGIN_SPECIFIC_SERVE, interval=0.6) \
                    and self.ocr_appear_click(self.O_LOGIN_SPECIFIC_SERVE, interval=0.6):
                while True:
                    self.screenshot()
                    if self.appear(self.I_LOGIN_SPECIFIC_SERVE):
                        self.click(self.C_LOGIN_ENSURE_LOGIN_CHARACTER_IN_SAME_SVR, interval=2)
                        continue
                    break
                logger.info('login specific user')
                continue
            
            # 创建角色, 误入新区直接重启
            if self.appear(self.I_CREATE_ACCOUNT):
                logger.warning('Appear create account')
                raise GameStuckError('Appear create account')

            # 点击“进入游戏”速度过快会进入区服设置，同时需在检测I_LOGIN_8之前检测，因为新服图标会让I_LOGIN_8向右偏移导致永远无法检测成功
            # 同时修复了点击位置（之前是点击I_CHARACTARS而不是左边的区域）
            if self.appear(self.I_CHARACTARS, interval=1):
                logger.info('误入区服设置')
                # https://github.com/runhey/OnmyojiAutoScript/issues/585
                self.device.click(x=106, y=535)
                
            # 点击’进入游戏‘
            if not self.appear(self.I_LOGIN_8):
                continue
            
            # 登录体验服时，点击“进入游戏”速度过快，可能会出现体验服的弹窗
            if self.appear(self.I_EARLY_SERVER):
                if self.appear_then_click(self.I_EARLY_SERVER_CANCEL):
                    logger.info('Cancel switch from early server to normal server')
                    continue
            if self.ocr_appear_click(self.O_LOGIN_ENTER_GAME_ORIGIN, interval=3) or self.ocr_appear_click(self.O_LOGIN_ENTER_GAME, interval=3):
                self.wait_until_appear(self.I_LOGIN_SPECIFIC_SERVE, True, wait_time=5)
                continue

        return login_success

    def app_handle_login(self) -> bool:
        for _ in range(2):
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            try:
                self._app_handle_login()
                # 收菜已经独立成任务(tasks/Harvest), 这里只是沿用"登录后顺带收菜"的行为
                if self.config.harvest.scheduler.enable:
                    from tasks.Harvest.handler import HarvestHandler
                    HarvestHandler(config=self.config, device=self.device).harvest()
                return True
            except (GameTooManyClickError, GameStuckError) as e:
                logger.warning(e)
                self.device.app_stop()
                self.device.app_start()
                continue

        logger.critical('Login failed more than 3')
        logger.critical('Onmyoji server may be under maintenance, or you may lost network connection')
        raise RequestHumanTakeover

    def set_specific_usr(self, character: str):
        self.character = character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = character


class LoginHandler(LoginMixin, BaseTask, RestartAssets, GameUiAssets, GeneralBuffAssets):
    """
    登录处理器(重启流程/切号流程用)

    真正的登录逻辑在 LoginMixin 里: 收菜任务需要"能登录"但资产组合和这里不同
    (它必须继承 GameUi 才能 ui_goto), 两者直接多重继承会因为
    GameUiAssets / BaseTask 重复而 MRO 冲突, 所以共享的部分抽成 mixin。
    """



