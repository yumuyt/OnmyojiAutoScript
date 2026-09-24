# This Python file uses the following encoding: utf-8
"""
OASX 兼容接口：统计

对应第三方面板 OASX (https://github.com/AzurTian/OASX) 的调用：
  lib/api/api_client_statistics.dart

本文件提供的接口（本仓库上游 runhey/OnmyojiAutoScript 暂无）：
  GET /stats/{script_name}/dates                 有日志的日期列表
  GET /stats/{script_name}?date=YYYY-MM-DD       某天的统计快照
  GET /stats/{script_name}/stream?date=...       今天的统计 SSE（实时刷新）

数据来源：脚本日志 ./log/YYYY-MM-DD_<配置名>.txt，识别以下标记（本仓库既有日志格式）：
  任务开始/结束: script.py  ->  "Scheduler: Start task `X`" / "Scheduler: End task `X`"
  战斗开始:      tasks/Component/GeneralBattle/general_battle.py -> hr 横幅 "General battle start"
  战斗结束:      tasks/Component/GeneralBattle/general_battle.py -> "Battle done"
  时间戳前缀:    "%Y-%m-%d %H:%M:%S.mmm | ... | LEVEL | message"

说明：本文件是**新增**的兼容层，不修改 module/server 下任何上游文件。
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Path as PathParam, Query
from fastapi.responses import StreamingResponse

from module.server.oasx_compat.config_transfer import _validate_config_name

stats_app = APIRouter(prefix='/stats', tags=['oasx-stats'])

TIMESTAMP_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.(\d{3})\s*\|')
TASK_START_RE = re.compile(r'Scheduler: Start task `([^`]+)`')
TASK_END_RE = re.compile(r'Scheduler: End task `([^`]+)`')
BATTLE_START_MARK = 'General battle start'
BATTLE_END_MARK = 'Battle done'
STREAM_POLL_INTERVAL = 2.0
STREAM_HEARTBEAT_INTERVAL = 15.0


# --------------------------------------------------------------------------------- 日志解析
def _log_dir() -> Path:
    return Path.cwd() / 'log'


def _log_path(script_name: str, day: str) -> Path:
    return _log_dir() / f'{day}_{script_name}.txt'


def _iter_records(path: Path) -> Iterator[tuple[datetime | None, str]]:
    """逐行产出 (时间戳, 文本)；横幅等没有时间戳的行时间戳为 None"""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if not line:
                continue
            match = TIMESTAMP_RE.match(line)
            if match:
                try:
                    stamp = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
                    stamp = stamp.replace(microsecond=int(match.group(2)) * 1000)
                except ValueError:
                    stamp = None
                parts = line.split(' | ', 3)
                message = parts[3] if len(parts) > 3 else line
                yield stamp, message.strip()
            else:
                yield None, line.strip()


def _build_stats(script_name: str, day: str) -> dict[str, Any]:
    """解析某一天的脚本日志，产出 StatsResponse 结构"""
    name = _validate_config_name(script_name, allow_template=True)
    path = _log_path(name, day)

    runs: list[dict[str, Any]] = []
    current_task: str | None = None
    current_start: datetime | None = None
    current_battles: list[float] = []
    battle_start: datetime | None = None
    fallback_start: datetime | None = None
    pending_battle = False
    last_stamp: datetime | None = None

    def _close_run(end_time: datetime) -> None:
        nonlocal current_task, current_start, current_battles, pending_battle, battle_start, fallback_start
        if current_task is None or current_start is None:
            return
        durations = [d for d in current_battles if d > 0]
        battle = None
        if current_battles or durations:
            battle = {
                'count': len(current_battles),
                'avg_duration_seconds': round(sum(durations) / len(durations), 2) if durations else 0.0,
            }
        runs.append({
            'task': current_task,
            'start_time': current_start.isoformat(timespec='seconds'),
            'end_time': end_time.isoformat(timespec='seconds'),
            'duration_seconds': round(max((end_time - current_start).total_seconds(), 0.0), 2),
            'battle': battle,
        })
        current_task, current_start, current_battles, pending_battle = None, None, [], False
        battle_start, fallback_start = None, None

    if path.exists():
        for stamp, text in _iter_records(path):
            if stamp is not None:
                if pending_battle and battle_start is None:
                    # 横幅之后的第一条带时间戳的日志 ≈ 战斗真正开始的时刻
                    battle_start = stamp
                    pending_battle = False
                last_stamp = stamp

            if BATTLE_START_MARK in text:
                if current_task is not None:
                    current_battles.append(0.0)
                    battle_start = None
                    pending_battle = True
                    fallback_start = last_stamp
                continue
            if BATTLE_END_MARK in text and current_task is not None:
                if current_battles and stamp is not None:
                    start = battle_start if battle_start is not None else fallback_start
                    if start is not None:
                        current_battles[-1] = max((stamp - start).total_seconds(), 0.0)
                battle_start, pending_battle, fallback_start = None, False, None
                continue

            if stamp is None:
                continue

            match = TASK_START_RE.search(text)
            if match:
                if current_task is not None:
                    _close_run(stamp)
                current_task, current_start, current_battles, battle_start = match.group(1), stamp, [], None
                continue
            match = TASK_END_RE.search(text)
            if match and current_task is not None:
                _close_run(stamp)

    tasks: dict[str, dict[str, Any]] = {}
    for run in runs:
        entry = tasks.setdefault(run['task'], {
            'run_count': 0,
            'total_duration_seconds': 0.0,
            'battle': {'count': 0, 'avg_duration_seconds': 0.0},
            'runs': [],
            '_battle_durations': [],
        })
        entry['run_count'] += 1
        entry['total_duration_seconds'] += run['duration_seconds']
        if run['battle']:
            entry['battle']['count'] += run['battle']['count']
            entry['_battle_durations'].append(run['battle']['avg_duration_seconds'])
        entry['runs'].append({
            'start_time': run['start_time'],
            'end_time': run['end_time'],
            'duration_seconds': run['duration_seconds'],
            'battle': run['battle'],
        })

    for entry in tasks.values():
        entry['total_duration_seconds'] = round(entry['total_duration_seconds'], 2)
        durations = [d for d in entry.pop('_battle_durations') if d > 0]
        if durations:
            entry['battle']['avg_duration_seconds'] = round(sum(durations) / len(durations), 2)
        if entry['battle']['count'] == 0:
            entry['battle'] = None

    return {
        'script_name': name,
        'total_runtime_seconds': round(sum(t['total_duration_seconds'] for t in tasks.values()), 2),
        'total_task_run_count': sum(t['run_count'] for t in tasks.values()),
        'total_battle_count': sum((t['battle'] or {}).get('count', 0) for t in tasks.values()),
        'tasks': tasks,
    }


def _available_dates(script_name: str) -> list[str]:
    name = _validate_config_name(script_name, allow_template=True)
    log_dir = _log_dir()
    if not log_dir.exists():
        return []
    dates = []
    for path in log_dir.glob(f'????-??-??_{name}.txt'):
        day = path.name[:10]
        try:
            datetime.strptime(day, '%Y-%m-%d')
        except ValueError:
            continue
        dates.append(day)
    return sorted(set(dates), reverse=True)


def _parse_day(date_text: str | None) -> str:
    if not date_text:
        raise HTTPException(status_code=422, detail='Invalid date format, expected YYYY-MM-DD')
    try:
        return datetime.strptime(date_text.strip(), '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=422, detail='Invalid date format, expected YYYY-MM-DD')


# --------------------------------------------------------------------------------- 接口
@stats_app.get('/{script_name}/dates')
async def stats_available_dates(script_name: str = PathParam(description='脚本配置名')):
    """有日志的日期列表（新到旧）"""
    name = _validate_config_name(script_name, allow_template=True)
    return {'script_name': name, 'dates': _available_dates(name)}


@stats_app.get('/{script_name}')
async def stats_snapshot(
        script_name: str = PathParam(description='脚本配置名'),
        date_text: str = Query(..., alias='date'),
):
    """某天的统计快照"""
    return _build_stats(script_name, _parse_day(date_text))


def _sse(event: str, data: dict) -> str:
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


async def _stream_events(script_name: str, day: str):
    name = _validate_config_name(script_name, allow_template=True)
    previous: dict[str, Any] = {}
    last_heartbeat = asyncio.get_event_loop().time()
    first = True

    while True:
        path = _log_path(name, day)
        if path.exists():
            stats = _build_stats(name, day)
            tasks = stats['tasks']
            changed = {k: v for k, v in tasks.items() if previous.get(k) != v}
            removed = [k for k in previous if k not in tasks]
            if first or changed or removed:
                yield _sse('update', {
                    'script_name': stats['script_name'],
                    'total_runtime_seconds': stats['total_runtime_seconds'],
                    'total_task_run_count': stats['total_task_run_count'],
                    'total_battle_count': stats['total_battle_count'],
                    'changed_tasks': changed,
                    'removed_tasks': removed,
                })
                previous = tasks
                first = False
                last_heartbeat = asyncio.get_event_loop().time()

        await asyncio.sleep(STREAM_POLL_INTERVAL)
        now = asyncio.get_event_loop().time()
        if now - last_heartbeat >= STREAM_HEARTBEAT_INTERVAL:
            last_heartbeat = now
            yield _sse('heartbeat', {'script_name': name, 'date': day})


@stats_app.get('/{script_name}/stream')
async def stats_stream(
        script_name: str = PathParam(description='脚本配置名'),
        date_text: str = Query(..., alias='date'),
):
    """今天的统计实时流（只支持今天）"""
    day = _parse_day(date_text)
    if day != date_cls.today().strftime('%Y-%m-%d'):
        raise HTTPException(status_code=400, detail="Only today's date supports SSE stream")

    response = StreamingResponse(_stream_events(script_name, day), media_type='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response
