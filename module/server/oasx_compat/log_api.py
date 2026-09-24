# This Python file uses the following encoding: utf-8
"""
OASX 兼容接口：日志

对应第三方面板 OASX (https://github.com/AzurTian/OASX) 的调用：
  lib/api/api_client_logs.dart
  lib/modules/log/script_log_browser_stream.dart（SSE 事件名与字段）

本文件提供的接口（本仓库上游 runhey/OnmyojiAutoScript 暂无）：
  GET /logs/{script_name}?cursor=&limit_lines=&limit_bytes=        日志窗口（可向更旧翻页）
  GET /logs/{script_name}/stream?cursor=&limit_lines=&limit_bytes=  实时日志 SSE
  GET /logs/errors?date=&script_name=&limit=&cursor=               错误日志列表
  GET /logs/errors/{error_id}?log_limit_bytes=                     错误详情（log.txt + 截图列表）
  GET /logs/errors/{error_id}/images/{image_name}                  错误截图（PNG）

日志来源（本仓库既有布局）：
  脚本日志: ./log/YYYY-MM-DD_<配置名>.txt                        （module/logger.py set_file_logger）
  错误目录: ./log/error/<毫秒时间戳>/log.txt + *.png              （script.py save_error_log）

说明：本文件是**新增**的兼容层，不修改 module/server 下任何上游文件。
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path as PathParam, Query
from fastapi.responses import FileResponse, StreamingResponse

from module.server.oasx_compat.config_transfer import _validate_config_name

log_app = APIRouter(prefix='/logs', tags=['oasx-logs'])
# /logs/errors* 必须比 /logs/{script_name} 先注册，否则会被当成脚本名
error_log_app = APIRouter(prefix='/logs', tags=['oasx-logs-errors'])

# --------------------------------------------------------------------------------- 限制常量
DEFAULT_LIMIT_LINES = 500
MAX_LIMIT_LINES = 5000
MIN_LIMIT_BYTES = 1024
DEFAULT_LIMIT_BYTES = 262144
MAX_LIMIT_BYTES = 2 * 1024 * 1024
DEFAULT_STREAM_LIMIT_LINES = 200
MAX_STREAM_LIMIT_LINES = 2000
DEFAULT_STREAM_LIMIT_BYTES = 131072
MAX_STREAM_LIMIT_BYTES = 1024 * 1024
MAX_LINE_BYTES = 4096
DEFAULT_ERROR_LIMIT = 50
MAX_ERROR_LIMIT = 500
MAX_ERROR_LOG_LIMIT_BYTES = 2 * 1024 * 1024
STREAM_POLL_INTERVAL = 1.0
STREAM_HEARTBEAT_INTERVAL = 15.0


# --------------------------------------------------------------------------------- 路径与游标
def _log_dir() -> Path:
    return Path.cwd() / 'log'


def _error_dir() -> Path:
    return _log_dir() / 'error'


def _script_files(script_name: str) -> list[Path]:
    """某个脚本的日志文件，按文件名（含日期）从新到旧"""
    log_dir = _log_dir()
    if not log_dir.exists():
        return []
    name = _validate_config_name(script_name, allow_template=True)
    files = [p for p in log_dir.glob(f'*_{name}.txt') if p.is_file()]
    files.sort(key=lambda p: p.name, reverse=True)
    return files


def _encode_cursor(file_name: str | None, offset: int, line_no: int) -> str:
    raw = json.dumps({'f': file_name, 'o': int(offset), 'l': int(line_no)}, ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode('utf-8')).decode('ascii')


def _decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode('ascii')).decode('utf-8')
        data = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail={'code': 'invalid_cursor', 'message': 'Cursor is invalid'})
    if not isinstance(data, dict) or 'o' not in data:
        raise HTTPException(status_code=400, detail={'code': 'invalid_cursor', 'message': 'Cursor is invalid'})
    return data


def _count_newlines_before(path: Path, offset: int) -> int:
    if offset <= 0:
        return 0
    with open(path, 'rb') as f:
        return f.read(offset).count(b'\n')


def _decode_line(raw: bytes) -> tuple[str, bool]:
    truncated = len(raw) > MAX_LINE_BYTES
    if truncated:
        raw = raw[:MAX_LINE_BYTES]
    return raw.decode('utf-8', errors='replace').rstrip('\r\n'), truncated


def _split_segments(chunk: bytes, start: int) -> list[tuple[int, bytes, bool]]:
    """把字节块切成 (起始偏移, 内容, 是否以换行结尾) 的段；文件末尾的换行不产生空行"""
    pieces = chunk.split(b'\n')
    segments: list[tuple[int, bytes, bool]] = []
    pos = start
    for index, piece in enumerate(pieces):
        has_newline = index < len(pieces) - 1
        if not has_newline and piece == b'':
            break
        segments.append((pos, piece, has_newline))
        pos += len(piece) + (1 if has_newline else 0)
    return segments


def _read_window_from_file(path: Path, end_offset: int, limit_lines: int, limit_bytes: int) -> tuple[list[dict], int]:
    """
    读取以 end_offset 结尾的一段日志（按行向上回退）。

    Returns:
        (lines, start_offset) —— lines 按旧到新排列，start_offset 是第一行的起始偏移
    """
    size = path.stat().st_size
    end_offset = min(max(int(end_offset), 0), size)
    if end_offset == 0:
        return [], 0

    block = min(max(limit_bytes, 64 * 1024), size)
    start = max(0, end_offset - block)
    with open(path, 'rb') as f:
        f.seek(start)
        chunk = f.read(end_offset - start)

    if start > 0:
        cut = chunk.find(b'\n')
        if cut < 0:
            return [], end_offset
        start = start + cut + 1
        chunk = chunk[cut + 1:]

    segments = _split_segments(chunk, start)
    selected: list[tuple[int, bytes, bool]] = []
    total_bytes = 0
    for segment in reversed(segments):
        if len(selected) >= limit_lines:
            break
        if selected and total_bytes + len(segment[1]) > limit_bytes:
            break
        selected.append(segment)
        total_bytes += len(segment[1])
    selected.reverse()
    if not selected:
        return [], end_offset

    first_offset = selected[0][0]
    base_line_no = _count_newlines_before(path, first_offset) + 1
    lines = []
    for index, (offset, raw, has_newline) in enumerate(selected):
        text, truncated = _decode_line(raw)
        lines.append({
            'file_name': path.name,
            'line_no': base_line_no + index,
            'offset': offset,
            'byte_length': len(raw) + (1 if has_newline else 0),
            'text': text,
            'line_truncated': truncated,
            '_complete': has_newline,
        })
    return lines, first_offset


def _strip_internal(lines: list[dict]) -> list[dict]:
    return [{k: v for k, v in line.items() if not k.startswith('_')} for line in lines]


def _empty_window(name: str, limits: dict) -> dict[str, Any]:
    return {
        'script_name': name,
        'window': {'from': None, 'to': None},
        'older_cursor': None,
        'live_cursor': _encode_cursor(None, 0, 0),
        'has_older': False,
        'reached_start': True,
        'limits': limits,
        'lines': [],
    }


def _build_window(script_name: str, cursor: str | None, limit_lines: int, limit_bytes: int) -> dict[str, Any]:
    name = _validate_config_name(script_name, allow_template=True)
    limits = {'limit_lines': limit_lines, 'limit_bytes': limit_bytes, 'max_line_bytes': MAX_LINE_BYTES}

    files = _script_files(name)
    if not files:
        return _empty_window(name, limits)

    decoded = _decode_cursor(cursor)
    if decoded and decoded.get('f'):
        file_name = str(decoded['f'])
        offset = int(decoded.get('o') or 0)
        index = next((i for i, p in enumerate(files) if p.name == file_name), None)
        if index is None:
            index, offset = 0, files[0].stat().st_size
    else:
        index, offset = 0, files[0].stat().st_size

    lines: list[dict] = []
    start_offset = 0
    current = index
    while current < len(files):
        path = files[current]
        # 游标所在文件从游标偏移开始（向更旧）；更旧的文件直接取文件尾部
        end = offset if current == index else path.stat().st_size
        lines, start_offset = _read_window_from_file(path, end, limit_lines, limit_bytes)
        if lines:
            break
        current += 1

    if not lines:
        return _empty_window(name, limits)

    first, last = lines[0], lines[-1]
    previous_exists = start_offset > 0 or current + 1 < len(files)

    newest = files[0]
    return {
        'script_name': name,
        'window': {
            'from': {'file_name': first['file_name'], 'offset': first['offset'], 'line_no': first['line_no']},
            'to': {'file_name': last['file_name'], 'offset': last['offset'], 'line_no': last['line_no']},
        },
        'older_cursor': _encode_cursor(files[current].name, start_offset, first['line_no']) if previous_exists else None,
        'live_cursor': _encode_cursor(newest.name, newest.stat().st_size, last['line_no']),
        'has_older': previous_exists,
        'reached_start': not previous_exists,
        'limits': limits,
        'lines': _strip_internal(lines),
    }


# --------------------------------------------------------------------------------- 日志窗口
@log_app.get('/{script_name}')
async def get_log_window(
        script_name: str = PathParam(description='脚本配置名或日志脚本名'),
        cursor: str | None = Query(default=None),
        limit_lines: int = Query(default=DEFAULT_LIMIT_LINES, ge=1, le=MAX_LIMIT_LINES),
        limit_bytes: int = Query(default=DEFAULT_LIMIT_BYTES, ge=MIN_LIMIT_BYTES, le=MAX_LIMIT_BYTES),
):
    """读取脚本日志窗口（不传 cursor 表示最新一屏）"""
    return _build_window(script_name, cursor, limit_lines, limit_bytes)


# --------------------------------------------------------------------------------- 实时日志 SSE
def _sse(event: str, data: dict) -> str:
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


async def _stream_events(script_name: str, cursor: str | None, limit_lines: int, limit_bytes: int):
    name = _validate_config_name(script_name, allow_template=True)
    decoded = _decode_cursor(cursor)
    files = _script_files(name)

    if decoded and decoded.get('f'):
        file_path = _log_dir() / str(decoded['f'])
        offset = int(decoded.get('o') or 0)
    elif files:
        file_path = files[0]
        offset = file_path.stat().st_size if file_path.exists() else 0
    else:
        file_path = _log_dir() / f'{datetime.now().strftime("%Y-%m-%d")}_{name}.txt'
        offset = 0

    if file_path.exists():
        offset = min(offset, file_path.stat().st_size)

    yield _sse('ready', {'cursor': _encode_cursor(file_path.name, offset, 0)})
    last_heartbeat = asyncio.get_event_loop().time()

    while True:
        await asyncio.sleep(STREAM_POLL_INTERVAL)

        newest = _script_files(name)
        if newest and newest[0].name != file_path.name:
            file_path = newest[0]
            offset = 0
            yield _sse('rotate', {'cursor': _encode_cursor(file_path.name, 0, 0)})

        if file_path.exists():
            size = file_path.stat().st_size
            if size < offset:  # 文件被重建/截断
                offset = 0
                yield _sse('rotate', {'cursor': _encode_cursor(file_path.name, 0, 0)})
            elif size > offset:
                lines, _ = _read_window_from_file(file_path, size, limit_lines, limit_bytes)
                complete = [line for line in lines if line['_complete']]
                fresh = [line for line in complete if line['offset'] >= offset]
                if fresh:
                    offset = fresh[-1]['offset'] + fresh[-1]['byte_length']
                    yield _sse('append', {
                        'lines': _strip_internal(fresh),
                        'next_cursor': _encode_cursor(file_path.name, offset, fresh[-1]['line_no']),
                    })
                    continue

        now = asyncio.get_event_loop().time()
        if now - last_heartbeat >= STREAM_HEARTBEAT_INTERVAL:
            last_heartbeat = now
            yield _sse('heartbeat', {'cursor': _encode_cursor(file_path.name, offset, 0)})


@log_app.get('/{script_name}/stream')
async def get_log_stream(
        script_name: str = PathParam(description='脚本配置名或日志脚本名'),
        cursor: str | None = Query(default=None),
        limit_lines: int = Query(default=DEFAULT_STREAM_LIMIT_LINES, ge=1, le=MAX_STREAM_LIMIT_LINES),
        limit_bytes: int = Query(default=DEFAULT_STREAM_LIMIT_BYTES, ge=MIN_LIMIT_BYTES, le=MAX_STREAM_LIMIT_BYTES),
):
    """订阅脚本最新日志（SSE）"""
    response = StreamingResponse(
        _stream_events(script_name, cursor, limit_lines, limit_bytes),
        media_type='text/event-stream',
    )
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


# --------------------------------------------------------------------------------- 错误日志
def _safe_child_name(value: str, what: str) -> str:
    if not value or value in {'.', '..'} or '/' in value or '\\' in value or ':' in value:
        raise HTTPException(status_code=400, detail={'code': 'invalid_name', 'message': f'Invalid {what}'})
    return value


def _parse_error_dir(directory: Path) -> dict[str, Any] | None:
    """解析一个错误目录；目录名必须是 `<毫秒时间戳>` 或 `<脚本名>_<毫秒时间戳>`"""
    name = directory.name
    script_name: str | None = None
    stamp_text = name
    legacy = True
    if '_' in name:
        head, _, tail = name.rpartition('_')
        if tail.isdigit() and head:
            script_name, stamp_text, legacy = head, tail, False
    if not stamp_text.isdigit():
        return None
    timestamp_ms = int(stamp_text)
    log_file = directory / 'log.txt'
    images = [p for p in directory.glob('*.png') if p.is_file()]
    return {
        'id': name,
        'directory': name,
        'script_name': script_name,
        'timestamp_ms': timestamp_ms,
        'time': datetime.fromtimestamp(timestamp_ms / 1000).astimezone().isoformat(),
        'legacy': legacy,
        'log_size': log_file.stat().st_size if log_file.exists() else 0,
        'image_count': len(images),
    }


def _list_error_items() -> list[dict[str, Any]]:
    root = _error_dir()
    if not root.exists():
        return []
    items = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            parsed = _parse_error_dir(child)
        except OSError:
            continue
        if parsed:
            items.append(parsed)
    items.sort(key=lambda item: item['timestamp_ms'], reverse=True)
    return items


@error_log_app.get('/errors')
async def get_error_logs(
        date_text: str | None = Query(default=None, alias='date'),
        script_name: str | None = Query(default=None),
        limit: int = Query(default=DEFAULT_ERROR_LIMIT, ge=1, le=MAX_ERROR_LIMIT),
        cursor: str | None = Query(default=None),
):
    """错误日志列表（目录时间倒序；cursor 里存的是毫秒时间戳）"""
    normalized_script = (script_name or '').strip() or None
    items = _list_error_items()

    if date_text:
        target = date_text.strip()
        items = [i for i in items if datetime.fromtimestamp(i['timestamp_ms'] / 1000).strftime('%Y-%m-%d') == target]
    if normalized_script:
        items = [i for i in items if i['script_name'] == normalized_script]

    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded:
            items = [i for i in items if i['timestamp_ms'] < int(decoded.get('o') or 0)]

    page = items[:limit]
    has_more = len(items) > limit
    return {
        'date': date_text,
        'script_name': normalized_script,
        'items': page,
        'next_cursor': _encode_cursor(None, page[-1]['timestamp_ms'], 0) if has_more and page else None,
        'has_more': has_more,
    }


@error_log_app.get('/errors/{error_id}')
async def get_error_log_detail(
        error_id: str = PathParam(description='错误目录名（毫秒时间戳或 <脚本名>_<毫秒时间戳>）'),
        log_limit_bytes: int = Query(default=DEFAULT_LIMIT_BYTES, ge=1, le=MAX_ERROR_LOG_LIMIT_BYTES),
):
    """单个错误目录详情"""
    error_id = _safe_child_name(error_id, 'error id')
    directory = _error_dir() / error_id
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail={'code': 'not_found', 'message': f'Error log not found: {error_id}'})

    parsed = _parse_error_dir(directory)
    if parsed is None:
        raise HTTPException(status_code=400, detail={'code': 'invalid_id', 'message': f'Invalid error id: {error_id}'})

    log_file = directory / 'log.txt'
    size = log_file.stat().st_size if log_file.exists() else 0
    content = ''
    truncated = False
    if log_file.exists():
        with open(log_file, 'rb') as f:
            raw = f.read(log_limit_bytes)
        truncated = size > len(raw)
        content = raw.decode('utf-8', errors='replace')

    images = []
    for path in sorted(directory.glob('*.png')):
        if not path.is_file():
            continue
        stat = path.stat()
        images.append({
            'name': path.name,
            'size': stat.st_size,
            'modified_time': datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            'url': f'/logs/errors/{quote(error_id, safe="")}/images/{quote(path.name, safe="")}',
        })

    return {
        'id': parsed['id'],
        'directory': parsed['directory'],
        'script_name': parsed['script_name'],
        'timestamp_ms': parsed['timestamp_ms'],
        'time': parsed['time'],
        'legacy': parsed['legacy'],
        'log': {
            'file_name': 'log.txt',
            'content': content,
            'size': size,
            'limit_bytes': log_limit_bytes,
            'truncated': truncated,
        },
        'images': images,
    }


@error_log_app.get('/errors/{error_id}/images/{image_name}')
async def get_error_log_image(
        error_id: str = PathParam(description='错误目录名'),
        image_name: str = PathParam(description='错误目录下的 PNG 文件名'),
):
    """读取错误截图"""
    error_id = _safe_child_name(error_id, 'error id')
    image_name = _safe_child_name(image_name, 'image name')
    path = _error_dir() / error_id / image_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail={'code': 'not_found', 'message': f'Image not found: {image_name}'})
    return FileResponse(str(path), media_type='image/png')
