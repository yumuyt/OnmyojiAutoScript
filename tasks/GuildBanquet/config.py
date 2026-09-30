# This Python file uses the following encoding: utf-8
# @author ohspecial
# github https://github.com/ohspecial
from enum import Enum  

from pydantic import Field

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time


class Weekday(str,Enum):
    Monday: str = "星期一"
    Tuesday: str = "星期二" 
    Wednesday: str = "星期三"
    Thursday: str = "星期四"
    Friday: str = "星期五"
    Saturday: str = "星期六"
    Sunday: str = "星期日"


class GuildBanquetTime(ConfigBase):
    """内置的两场宴会时间(星期 + 时刻), 与狭间暗域的 abyss_shadows_time 一样由任务自己用

    排程以此为准: 到宴会日的这个时刻自动运行, 独立于调度器的强制设定服务时间
    (scheduler.server_update 不再参与, 否则会被改写成"明天 server_update 时刻")
    """

    # 每周第1场宴会
    day_1: Weekday = Field(
        default=Weekday.Wednesday,
        description="每周第1次运行时间设置，注意第一次时间要比第二次时间早",
    )
    run_time_1: Time = Field(
        default=Time(hour=19, minute=0, second=0),
        description="内置的第1场宴会开始时刻，默认19:00；到点后若宴会还没开，会在之后1小时内按失败间隔每5分钟再看一次，超出即排到下一场宴会",
    )
    # 每周第2场宴会
    day_2: Weekday = Field(
        default=Weekday.Saturday,
        description="每周第2次运行时间设置",
    )
    run_time_2: Time = Field(
        default=Time(hour=19, minute=0, second=0),
        description="内置的第2场宴会开始时刻，默认19:00；两场宴会也可以配在同一天的不同时刻（各自到点各跑一次）",
    )


class GuildBanquet(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    guild_banquet_time: GuildBanquetTime = Field(default_factory=GuildBanquetTime)
