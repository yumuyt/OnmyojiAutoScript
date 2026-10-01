# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta
from pydantic import BaseModel, Field, validator

from tasks.Component.config_base import MultiLine
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, TimeDelta
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig



class MissionsConfig(BaseModel):
    # missions_rule 是"要做哪些任务 + 优先级"的白名单，没写进去的类型不会被做。
    # 任务类型名 = 卡片标题里 '·' 右边那半截（"远远不够·养成" 的类型是 "养成"），
    # 也就是：契灵 / 觉醒一~三 / 御灵一~三 / 御魂一~三 / 养成 / 结伴同行
    missions_rule: MultiLine = Field(default='契灵 > 觉醒三 > 觉醒二 > 觉醒一 > 御灵三 > 御灵二 > 御灵一 > 御魂三 > 御魂二 > 御魂一 > 养成',
                                     description='missions_rule_help')
    setup_when_bondling: bool = Field(default=True, description='setup_when_bondling_help')
    missions_select: str = Field(default='觉醒三',
                                description='指定的任务')

    @validator('missions_rule', pre=True, always=True)
    def mr_validator(cls, v):
        if isinstance(v, str):
            # 旧配置兼容：
            #   御魂五/御魂四 是已经不存在的写法
            #   喂 N 卡任务以前写成 "远远不够"（那其实是左侧自定义任务名，不是任务类型）
            return v.replace('御魂五', '御魂二').replace('御魂四', '御魂一').replace('远远不够', '养成')
        return v


class CollectiveMissions(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    missions_config: MissionsConfig = Field(default_factory=MissionsConfig)





