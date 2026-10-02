# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import Field

from tasks.Component.config_scheduler import Scheduler


class HarvestScheduler(Scheduler):
    """
    收菜的调度器

    NOTE 这里**不再有"每天几点执行"**:
         收菜的时刻是任务的内置时间(见 tasks/Harvest/config.py 的 HarvestTime),
         与寮宴会/狭间暗域一样由任务自己按内置时刻排期,
         调度器只负责"参不参与调度", 不参与算时间(排期时显式传 server=False)。
    """
    enable: bool = Field(default=True, description='enable_help')
    priority: int = Field(default=5, description='priority_help')
