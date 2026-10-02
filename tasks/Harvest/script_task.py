# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import datetime, time, timedelta

from module.logger import logger
from module.exception import TaskEnd
from tasks.Component.config_base import Time
from tasks.Harvest.handler import HarvestHandler
from tasks.Restart.login import LoginMixin

# 脚本进程还没重启时老配置模型里没有内置时间字段, 退回这个默认(与 HarvestTime 一致)
DEFAULT_RUN_TIMES = (Time(hour=0, minute=15, second=0), Time(hour=20, minute=0, second=0))


class ScriptTask(LoginMixin, HarvestHandler):
    """
    独立的收菜任务

    - 游戏在跑: 就近回到庭院再收菜(收菜本来就不需要重启游戏)
    - 游戏没跑: 起游戏 + 登录, 再收菜
    - 收完按内置时刻(每天两次, 默认 00:15 / 20:00)排下一次

    NOTE 登录能力用 LoginMixin(不是 LoginHandler): 收菜要回庭院就得有 ui_goto,
         而 ui_goto 在 GameUi 里(HarvestHandler 已经继承), GameUi 自带 GameUiAssets,
         再叠一个 LoginHandler 会和它重复 -> MRO 冲突。
    """

    def run(self) -> None:
        if not self.device.app_is_running():
            logger.info('Game is not running, start and login before harvest')
            self.app_start()
        else:
            # 可能停在别的页面(上次中断残留), 先回庭院, 免得收菜在陌生页面乱点
            from tasks.GameUi.page import page_main
            self.ui_goto(page_main)
        self.execute()
        self.plan_next_run()
        raise TaskEnd('Harvest end')

    def app_start(self):
        logger.hr('App start')
        self.device.app_start()
        self.app_handle_login()

    # ---------------------------------------------------------------- 内置时间
    def run_times(self) -> tuple:
        """内置的两餐收菜时刻(每天两次)

        NOTE 老配置模型(脚本进程还没重启)里没有 harvest_time, 此时退回默认时刻,
             不要让任务直接报错
        """
        harvest_time = getattr(self.config.harvest, 'harvest_time', None)
        slot_1 = getattr(harvest_time, 'run_time_1', None)
        slot_2 = getattr(harvest_time, 'run_time_2', None)
        if slot_1 is None or slot_2 is None:
            logger.warning('harvest.harvest_time not found in config model, '
                           'use default 00:15 / 20:00 (restart the script process to enable this option)')
            return DEFAULT_RUN_TIMES
        return slot_1, slot_2

    def next_harvest_time(self, now: datetime = None) -> datetime:
        """内置时刻里的下一次收菜: 今天还没到点就是今天, 否则是明天的第一个时刻

        两个时刻允许配成同一个(等于每天只收一次)。
        """
        now = now or datetime.now()
        candidates = []
        for run_time in self.run_times():
            for days in (0, 1):
                target = (now + timedelta(days=days)).replace(
                    hour=run_time.hour, minute=run_time.minute,
                    second=run_time.second, microsecond=0)
                if target > now:
                    candidates.append(target)
        if not candidates:
            # 理论上不会发生(明天那两个时刻一定在未来), 兜底成一天后
            return now + timedelta(days=1)
        return min(candidates)

    def plan_next_run(self):
        """排到内置时刻表里的下一次收菜

        NOTE 显式传 server=False: 否则 server_update 不是 09:00 时会被改写成
             "明天 server_update 时刻"(见 Config.task_delay), 内置时刻就白配了
        """
        target = self.next_harvest_time()
        logger.info(f'Next harvest at {target}')
        self.set_next_run(task='Harvest', target=target, server=False)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    config = Config('oas1')
    device = Device(config)
    task = ScriptTask(config, device)
    task.execute()
