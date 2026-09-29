# This Python file uses the following encoding: utf-8
# @brief 阴阳寮活动(道馆/狭间暗域/首领退治/寮宴会)共用的重试窗口
"""
活动开始时刻之后, 只重试 RETRY_WINDOW 这么久; 超出即放弃当天, 排到该活动的下一次。

NOTE 各任务的失败重试此前是"按 failure_interval 无限重试"(或"一直重试到 22:00"),
     统一用这里的窗口限流, 避免活动当天没开时一整天反复空跑。
"""
from datetime import datetime, time, timedelta

# 活动开始后最多重试的时长
RETRY_WINDOW: timedelta = timedelta(hours=1)


def activity_target(now: datetime, run_time: time) -> datetime:
    """当天的活动开始时刻"""
    if isinstance(run_time, str):
        run_time = time.fromisoformat(run_time)
    return now.replace(hour=run_time.hour, minute=run_time.minute,
                       second=run_time.second, microsecond=0)


def in_retry_window(now: datetime, run_time: time, window: timedelta = RETRY_WINDOW) -> bool:
    """距离当天活动开始时刻不超过 window 时返回 True(只有此时才继续重试)

    活动还没到点(now 早于开始时刻)也算在窗口内。
    """
    return now - activity_target(now, run_time) <= window
