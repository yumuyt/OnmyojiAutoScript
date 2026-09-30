# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import time, timedelta

from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler


class Banquet(ConfigBase):
    """八百八狸盛宴 运行参数"""

    # 运行总时长上限（软限制，到点后打完当前这局就收工）
    limit_time: Time = Field(default=Time(minute=30), description='ffs_limit_time_help')
    # 本次运行最多打几局，0 表示不限制（真正的限制是每日消耗上限）
    limit_battle: int = Field(default=0, description='ffs_limit_battle_help')
    # 单局消耗，游戏内「退治」按钮上的 x6
    battle_cost: int = Field(default=6, description='ffs_battle_cost_help')
    # 每日消耗上限，游戏内「每日消耗上限 300/300」里的 300
    daily_cost_limit: int = Field(default=300, description='ffs_daily_cost_limit_help')
    # 防封：点「退治」开始战斗前，随机插入停顿，打散固定节奏
    random_sleep: bool = Field(default=True, description='ffs_random_sleep_help')

    @property
    def limit_time_v(self) -> timedelta:
        if isinstance(self.limit_time, time):
            return timedelta(hours=self.limit_time.hour,
                             minutes=self.limit_time.minute,
                             seconds=self.limit_time.second)
        return self.limit_time


class FightForShikigami(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    banquet: Banquet = Field(default_factory=Banquet)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    general_battle: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
