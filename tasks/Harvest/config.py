# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import BaseModel, Field

from tasks.Component.config_base import ConfigBase, Time
from tasks.Harvest.config_scheduler import HarvestScheduler


class HarvestTime(ConfigBase):
    """内置的收菜时刻(每天两次)

    与寮宴会(guild_banquet_time)、狭间暗域一样: 到点自动跑, 不依赖调度器的
    "下一次运行时间"/服务时间, 排期时显式传 server=False,
    否则会被改写成"明天 server_update 时刻", 内置时刻就白配了。

    默认每天 00:15 和 20:00 各收一次。
    """

    run_time_1: Time = Field(
        default=Time(hour=0, minute=15, second=0),
        description='harvest_run_time_1_help',
    )
    run_time_2: Time = Field(
        default=Time(hour=20, minute=0, second=0),
        description='harvest_run_time_2_help',
    )


class HarvestConfig(BaseModel):
    # 庭院事务
    enable_courtyard_affairs: bool = Field(default=True, description='harvest_courtyard_affairs_help')
    # 永久勾玉卡
    enable_jade: bool = Field(default=True)
    # 签到
    enable_sign: bool = Field(default=True)
    # 999天的签到福袋
    enable_sign_999: bool = Field(default=True)
    # 邮件
    enable_mail: bool = Field(default=True)
    # 御魂加成
    enable_soul: bool = Field(default=True)
    # 体力
    enable_ap: bool = Field(default=True)


class Harvest(ConfigBase):
    scheduler: HarvestScheduler = Field(default_factory=HarvestScheduler)
    harvest_time: HarvestTime = Field(default_factory=HarvestTime)
    harvest_config: HarvestConfig = Field(default_factory=HarvestConfig)
