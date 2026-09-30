# This Python file uses the following encoding: utf-8
# @author ohspecial
# github https://github.com/ohspecial
from datetime import datetime ,timedelta
import time

from module.exception import TaskEnd
from module.logger import logger
from module.base.timer import Timer

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_guild, page_main
from tasks.GuildBanquet.assets import GuildBanquetAssets
from tasks.GuildBanquet.config import Weekday
from tasks.Component.activity_window import RETRY_WINDOW, in_retry_window

WEEKDAYDICT = {
    0: '星期一',
    1: '星期二',
    2: '星期三',
    3: '星期四',
    4: '星期五',
    5: '星期六',
    6: '星期日'
}

class ScriptTask(GameUi, GuildBanquetAssets):
    """寮宴会

    内置时间(与狭间暗域一致): 两次宴会的日期与时刻都配在 guild_banquet_time 里,
    排程全部以它为基准, 不再依赖调度器的强制设定服务时间 scheduler.server_update。
    """

    def run(self):
        self.run_time = self.config.guild_banquet.guild_banquet_time

        self.ui_get_current_page()
        self.ui_goto(page_guild)
        
        if self.appear(self.I_FLAG):
            wait_count = 0
            wait_timer = Timer(230)
            wait_timer.start()
            logger.info("Start guild banquet!")
            self.device.stuck_record_add('BATTLE_STATUS_S')
        else:
            # 如果没有找到FLAG，可能是宴会还没开始：5分钟后再看一次
            # 超出重试窗口(或今天不是宴会日)则由 check_runtime 排到下一场宴会
            if self.check_runtime():
                time_now = datetime.now()
                time_later = time_now + timedelta(minutes=5)
                logger.info(f"Guild banquet has not started, check again at {time_later}")
                # NOTE server=False: 否则 server_update 不是 09:00 时会被改写成"明天 server_update 时刻"
                self.set_next_run(task='GuildBanquet',
                              finish=True,
                              target=time_later,
                              server=False)
            self.ui_get_current_page()
            self.ui_goto(page_main)
            raise TaskEnd

        last_check_time = 0  # 记录上次实际检测时间
        last_log_time = 0  # 记录上次日志输出时间
        last_flag_status = False  # 记录上次真实检测结果

        while True:
            self.screenshot()
            # 条件1: 强制检测间隔管理
            current_time = time.time()
            if current_time - last_check_time >= 10:
                # 达到间隔要求时执行真实检测
                actual_status = self.appear(self.I_FLAG)
                last_flag_status = actual_status
                last_check_time = current_time
                logger.debug(f"Actual detection at {current_time}, status: {actual_status}")
                
                # 重置日志计时器
                last_log_time = current_time
            else:
                # 未达间隔时沿用上次结果
                logger.debug(f"Using cached status: {last_flag_status}")
                
                
            # 条件2: 状态判断逻辑
            if last_flag_status:
                if current_time - last_log_time >= 10:
                    logger.info("Banquet ongoing, waiting...")
                    last_log_time = current_time
            else:
                logger.info("Guild banquet end")
                break  # 退出循环

            # 条件3: 超时保护
            if wait_timer.reached():
                wait_timer.reset()
                if wait_count >= 3:
                    # 宴会最长15分钟
                    logger.info('Guild banquet timeout')
                    break
                wait_count += 1
                logger.info(f'Banquet ongoing, waiting... (Count: {wait_count})')
                self.device.stuck_record_clear()
                self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.stuck_record_clear()
        self.set_config()
        self.ui_get_current_page()
        self.ui_goto(page_main)
        self.plan_next_run()
        raise TaskEnd

    # ---------------------------------------------------------------- 内置时间
    def banquet_schedule(self) -> list:
        """内置的宴会时间表 [(星期, 时刻), ...]

        读的是当前配置, 因此 set_config() 回写时刻之后立刻就是新的时间;
        两次设置允许落在同一天(同一天的两场宴会)
        """
        cfg = self.config.guild_banquet.guild_banquet_time
        return [(self.get_key_from_value(WEEKDAYDICT, cfg.day_1.value), cfg.run_time_1),
                (self.get_key_from_value(WEEKDAYDICT, cfg.day_2.value), cfg.run_time_2)]

    def today_run_time(self):
        """今天的宴会时刻; 今天不是宴会日则返回 None"""
        today = datetime.now().weekday()
        for day, run_time in self.banquet_schedule():
            if day == today:
                return run_time
        return None

    def next_banquet_time(self, now: datetime = None) -> datetime:
        """内置时间里的下一场宴会时刻: 今天还没到点就是今天, 否则是下一次宴会日"""
        now = now or datetime.now()
        candidates = []
        for day, run_time in self.banquet_schedule():
            target = (now + timedelta(days=(day - now.weekday()) % 7)).replace(
                hour=run_time.hour, minute=run_time.minute, second=run_time.second, microsecond=0)
            if target <= now:
                # 今天这一场已经开始了(或已结束), 下一场在同一天的下一周
                target += timedelta(days=7)
            candidates.append(target)
        return min(candidates)

    def check_runtime(self) -> bool:
        """
        宴会还没开始时, 只有落在今天的内置宴会时刻的"前 30 分钟 ~ 后 1 小时"窗口内才继续重试

        比这更早(比如暂停很久后一大早就被拉起来)或超出窗口(或今天本来就不是宴会日),
        都直接排到下一场宴会并返回 False
        """

        now = datetime.now()
        run_time = self.today_run_time()
        if run_time is None:
            logger.info("Today is not a guild banquet day, stop retrying and plan the next banquet")
            self.plan_next_run()
            return False

        if in_retry_window(now, run_time):
            return True

        logger.warning(f"Retry window({RETRY_WINDOW}) exceeded, plan the next banquet")
        self.plan_next_run()
        return False

    def plan_next_run(self):
        """排到内置时间表里的下一场宴会

        NOTE 显式传 server=False: 否则 server_update 不是 09:00 时会被改写成
             "明天 server_update 时刻"(见 Config.task_delay), 内置的宴会时刻就白配了
        """
        target = self.next_banquet_time()
        logger.info(f"Plan next run: {target}")
        self.set_next_run(task='GuildBanquet', target=target, server=False)

    def get_key_from_value(self, dict, value):
        return [k for k, v in dict.items() if v == value][0]
    
    def get_weekday_enum(self, value: str) -> Weekday:
        for day in Weekday:
            if day.value == value:
                return day

    @staticmethod
    def seconds_of(run_time) -> int:
        """时刻换算成当天的秒数, 用来比较两场宴会谁离得更近"""
        return run_time.hour * 3600 + run_time.minute * 60 + run_time.second

    def set_config(self):
        """
        宴会结束时, 把这次宴会实际开始的时刻(结束时刻往前推15分钟)回写到配置里,
        这样会长改了宴会时间也能自己跟上
        """
        
        try:
            # 当结束宴会时，设置宴会时间的日期及时间，宴会时间设置为运行结束时间提前15分钟(因识图问题，宴会可能被认为提前关闭几秒钟)
            next_time = datetime.now() - timedelta(minutes=14, seconds=55)
            next_time = next_time.replace(second=0, microsecond=0)
            # 计算下次运行时间
            next_time = datetime.time(next_time)
            
            today = datetime.now().weekday()          
            schedule = self.banquet_schedule()
            day_1, day_2 = schedule[0][0], schedule[1][0]
            
            # 修改配置文件
            # 当天配置的那一场: 两次配置可以落在同一天, 回写离这次宴会最近的那一场
            same_day = [i for i, (day, _) in enumerate(schedule) if day == today]
            if same_day:
                index = min(same_day,
                            key=lambda i: abs(self.seconds_of(schedule[i][1]) - self.seconds_of(next_time)))
                if index == 0:
                    self.run_time.run_time_1 = next_time
                else:
                    self.run_time.run_time_2 = next_time
            elif today < day_1:
                self.run_time.day_1 = self.get_weekday_enum(WEEKDAYDICT.get(today))
                self.run_time.run_time_1 = next_time
            elif today > day_2:
                self.run_time.day_2 = self.get_weekday_enum(WEEKDAYDICT.get(today))    
                self.run_time.run_time_2 = next_time
            else:
                # 如果当前时间在两个配置时间之间，则默认把工作日设置第一天，周末设为第二天
                if today <= 4:  # 工作日
                    self.run_time.day_1 = self.get_weekday_enum(WEEKDAYDICT.get(today))
                    self.run_time.run_time_1 = next_time
                else:  # 周末
                    self.run_time.day_2 = self.get_weekday_enum(WEEKDAYDICT.get(today))       
                    self.run_time.run_time_2 = next_time
            logger.info(f"Set next run time: {self.run_time}")
            
            self.config.save()
        except Exception as e:
            logger.error(f"Error setting banquet config: {e}")
            raise TaskEnd


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
