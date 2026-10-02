# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import datetime, timedelta

from tasks.Component.config_base import Time
from tasks.Restart.login import LoginHandler
from tasks.Restart.assets import RestartAssets
from tasks.base_task import BaseTask
from datetime import datetime, time

from module.logger import logger
from module.exception import TaskEnd, RequestHumanTakeover


class ScriptTask(LoginHandler):

    def run(self) -> None:
        """
        主要就是登录的模块
        :return:
        """
        if not self.delay_pending_tasks():
            self.app_restart()
        raise TaskEnd('ScriptTask end')

    def app_stop(self):
        logger.hr('App stop')
        self.device.app_stop()

    def app_start(self):
        logger.hr('App start')
        self.device.app_start()
        self.app_handle_login()
        # self.ensure_no_unfinished_campaign()

    def app_restart(self):
        logger.hr('App restart')
        self.device.app_stop()
        self.device.app_start()
        self.app_handle_login()

        # 没勾"定时重启"时, 重启就是"卡死恢复/手动调用"用的工具:
        # 执行完把下次运行排到一周后 —— 既不会因为 next_run 过期被反复调度,
        # 也不会让"关掉定时重启"变成事实上的每天都在重启。
        if not self.config.restart.scheduler.schedule:
            # NOTE 这里**不能传 success=True**: Config.task_delay 取的是
            #      min(success_interval, target) —— 传了 success 就会选中"明天",
            #      结果变成"关掉定时重启却还是每天重启一次"(实测日志里两个候选都在,
            #      落到 next_run 的是 2026-10-04 而不是预期的那天)。
            #      只传 target 时 run 里只有这一个候选, 才会真的排到一周后。
            self.set_next_run(task='Restart', finish=True, server=False,
                              target=datetime.now() + timedelta(weeks=1))
            return

        # self.config.task_delay(server_update=True)
        self.set_next_run(task='Restart', success=True, finish=True, server=True)
        # 如果启用了定时领体力（每天 12-14、20-22 时内各有 20 体力）
        if self.config.harvest.harvest_config.enable_ap:
            now = datetime.now()
            # 如果时间在00:00-12:00之间则设定时间为当日 12 时
            if now.time() < time(12, 0):
                self.custom_next_run(task='Restart', custom_time=Time(12, 0), time_delta=0)
            # 如果时间在12:00-20:00之间则设定时间为当日 20 时
            elif now.time() >= time(12, 0) and now.time() < time(20, 0):
                self.custom_next_run(task='Restart', custom_time=Time(20, 0), time_delta=0)
            # 如果时间在20:00-23:59之间则设定时间为次日 12 时
            else:
                self.custom_next_run(task='Restart', custom_time=Time(12, 0), time_delta=1)

    def delay_pending_tasks(self) -> bool:
        """
        周三更新游戏的时候延迟
        @return:
        """
        # 定时重启关掉时这里也不排时间: 重排出来的 9:00 会让维护窗口后再白跑一次重启
        if not self.config.restart.scheduler.schedule:
            return False
        datetime_now = datetime.now()
        if not (datetime_now.weekday() == 2 and 6 <= datetime_now.hour <= 8):
            return False
        logger.info("The game server is updating, delay the pending tasks to 9:00")
        logger.warning('Delay pending tasks')
        # running 中的必然是 Restart
        for task in self.config.pending_task:
            print(task.command)
            self.set_next_run(task=task.command, target=datetime_now.replace(hour=9, minute=0, second=0, microsecond=0))
        self.set_next_run(task='Restart', success=True, finish=True, server=True)
        return True
