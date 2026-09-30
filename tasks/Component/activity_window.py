# This Python file uses the following encoding: utf-8
# @brief 阴阳寮活动(道馆/狭间暗域/首领退治/寮宴会)共用的重试窗口
"""
活动开始时刻前 LEAD_WINDOW ~ 后 RETRY_WINDOW 之间才重试; 超出即放弃当天, 排到该活动的下一次。

NOTE 各任务的失败重试此前是"按 failure_interval 无限重试"(或"一直重试到 22:00"),
     统一用这里的窗口限流, 避免活动当天没开时一整天反复空跑。
NOTE 早于活动时刻太多时窗口直接返回 False(不再是"只要还没到点就算在窗口内"):
     否则任务一旦被提前拉起(暂停很久后重启/通知提前触发/手动运行), 就会从那一刻起
     按失败间隔一直空跑 —— 19:00 的暗域从早上跑起来能空跑到 20:00。
     这种"还没到今天的活动时刻"的情况, 调用方应当直接把任务排到今天的活动时刻。
"""
from datetime import datetime, time, timedelta

# 活动开始后最多重试的时长
RETRY_WINDOW: timedelta = timedelta(hours=1)
# 活动开始前提前多久开始试探(会长/副会长可能比配置的时刻开得早)
LEAD_WINDOW: timedelta = timedelta(minutes=30)


def activity_target(now: datetime, run_time: time) -> datetime:
    """当天的活动开始时刻"""
    if isinstance(run_time, str):
        run_time = time.fromisoformat(run_time)
    return now.replace(hour=run_time.hour, minute=run_time.minute,
                       second=run_time.second, microsecond=0)


def in_retry_window(now: datetime, run_time: time,
                    window: timedelta = RETRY_WINDOW,
                    lead: timedelta = LEAD_WINDOW) -> bool:
    """当天活动时刻前 lead ~ 后 window 之间才返回 True(只有此时才继续重试)

    活动还没到点但已经进入 lead 窗口(默认提前 30 分钟)也算在窗口内;
    再早(比如暂停很久后一大早就被拉起来)返回 False, 由调用方排到今天的活动时刻。
    """
    delta = now - activity_target(now, run_time)
    return -lead <= delta <= window
