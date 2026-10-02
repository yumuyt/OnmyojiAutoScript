# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import datetime, time

from pydantic import Field

from tasks.Component.config_base import DateTime, Time, TimeDelta
from tasks.Component.config_scheduler import Scheduler

from module.logger import logger


class RestartScheduler(Scheduler):
    """
    重启的调度器

    NOTE 这里把 Scheduler 的字段重新列了一遍(而不是只覆盖 enable):
         pydantic 里子类新加的字段会排在父类字段后面, "定时重启"开关就会掉到页面最下面。
         重启页的顺序应该是 enable -> 定时重启 -> (定时重启才用得到的)服务时间/随机延迟,
         所以按想要的顺序显式声明, 声明顺序就是 OASX 页面上的顺序。
    """
    enable: bool = Field(default=True, description='enable_help')
    # 是否按固定时间重启。
    # 重启最主要用于任务卡死后的恢复(框架自己调用 Restart), 这种场景不需要定时;
    # 关掉这个开关后, Restart 不会因为到了某个时间而被调度, 只在被调用时才执行,
    # server_update / next_run 也就不会再强制把下次运行时间改到某个固定时刻。
    schedule: bool = Field(default=False, description='restart_schedule_help')
    next_run: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"), description='next_run_help')
    priority: int = Field(default=0, description='priority_help')
    success_interval: TimeDelta = Field(default=TimeDelta(days=1), description='success_interval_help')
    failure_interval: TimeDelta = Field(default=TimeDelta(days=1), description='failure_interval_help')
    server_update: Time = Field(default=Time(hour=9, minute=5, second=0), description='server_update_help')
    delay_date: int = Field(default=1, description='delay_date_help', ge=1, le=31)
    float_time: Time = Field(default=Time(hour=0, minute=0, second=0), description='float_time_help')
