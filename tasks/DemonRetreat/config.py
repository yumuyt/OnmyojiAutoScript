# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta
from pydantic import BaseModel, Field, model_validator

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time


class DemonRetreatTime(ConfigBase):
    """内置的退治开打时刻(每周六), 与狭间暗域的 abyss_shadows_time 一样由任务自己用"""

    custom_run_time_saturday: Time = Field(
        default=Time(hour=10, minute=0, second=0),
        description="内置的周六退治开打时刻，默认10:00（游戏里周六10:00~23:00由会长/副会长开），请填你们寮实际开退治的时刻；到点后若进不去，只在其后1小时内按失败间隔重试，超出即当作今天已完成，排到下周六",
    )

    @model_validator(mode='before')
    @classmethod
    def migrate_custom_run_time(cls, data):
        """兼容旧配置: 老版本的字段名是 custom_run_time(单个时间), 迁移到 custom_run_time_saturday"""
        if isinstance(data, dict) and 'custom_run_time' in data:
            data = dict(data)
            legacy = data.pop('custom_run_time')
            data.setdefault('custom_run_time_saturday', legacy)
        return data


class DemonRetreat(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    demon_retreat_time: DemonRetreatTime = Field(default_factory=DemonRetreatTime)
    general_battle: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
