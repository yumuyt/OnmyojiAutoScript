# This Python file uses the following encoding: utf-8
"""
OASX 兼容接口：配置 / 任务的导入导出

对应第三方面板 OASX (https://github.com/AzurTian/OASX) 的调用：
  lib/api/api_client_config_transfer.dart
  lib/api/api_client_task_transfer.dart

本文件提供的接口（本仓库上游 runhey/OnmyojiAutoScript 暂无）：
  GET  /config/export?name=<配置名>                     导出整个配置（脱敏）
  POST /config/import                                   multipart: name + file
  GET  /config/task/export?config_name=&task_name=      导出单个任务（脱敏）
  POST /config/task/import                              multipart: config_name + task_name + (json_text | file)
  GET  /config/task/copy-json?config_name=&task_name=   复制单个任务（未脱敏）

注意：本文件是**新增**的兼容层，不修改 module/server 下任何上游文件。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from module.config.utils import convert_to_underscore, read_file, write_file
from module.logger import logger
from module.server.main_manager import mm

config_transfer_app = APIRouter()

# --------------------------------------------------------------------------------- 常量
CONFIG_NAME_RESERVED_CHARS = set('/\\:*?"<>|')
CONFIG_TASK_EXCLUDED_KEYS = {'config_name', 'running_task'}
REDACT_VALUE = 'XXX'

# 脱敏路径，与 OASX 配套服务端（AzurTian/OnmyojiAutoScript）保持一致的字段集合
REDACT_PATHS = (
    'wanted_quests.wanted_quests_config.invite_friend_name',
    '*.invite_config.friend_list',
    'script.error.notify_config',
    'global_game.server.password',
    'script.device.serial',
    'script.device.handle',
    'script.device.emulatorinfo_name',
    'script.device.emulatorinfo_path',
    'find_jade.sup_account_list_*.account',
    'find_jade.sup_account_list_*.account_alias',
)
REDACT_KEYS = {
    'password',
    'token',
    'access_token',
    'cookie',
    'authorization',
}


# --------------------------------------------------------------------------------- 基础工具
def _config_dir() -> Path:
    return Path.cwd() / 'config'


def _config_path(name: str) -> Path:
    return _config_dir() / f'{name}.json'


def _validate_config_name(name: str, *, allow_template: bool = True) -> str:
    """校验配置名，返回去掉首尾空白后的名字"""
    name = (name or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Config name is required')
    if not allow_template and name == 'template':
        raise HTTPException(status_code=400, detail='Config name template is reserved')
    if '.' in name:
        raise HTTPException(status_code=400, detail='Config name cannot contain dots')
    if any(ch in CONFIG_NAME_RESERVED_CHARS for ch in name):
        raise HTTPException(status_code=400, detail='Config name contains reserved path characters')
    if any(ord(ch) < 32 for ch in name):
        raise HTTPException(status_code=400, detail='Config name contains control characters')
    return name


def _load_config_dict(name: str) -> dict[str, Any]:
    """读取配置文件的 JSON 内容"""
    path = _config_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f'Config not found: {name}')
    try:
        data = read_file(str(path))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f'Config JSON parse failed: {e}') from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail='Config JSON root must be an object')
    return data


def _normalize_task_key(task_name: str) -> str:
    """把任务名统一成配置文件里的 key（大驼峰 -> 下划线）"""
    task_key = convert_to_underscore((task_name or '').strip())
    if not task_key:
        raise HTTPException(status_code=400, detail='Task name is required')
    if task_key in CONFIG_TASK_EXCLUDED_KEYS:
        raise HTTPException(status_code=400, detail=f'Task cannot be transferred: {task_key}')
    return task_key


def _file_response(payload: Any, filename: str) -> Response:
    """把 JSON 内容作为文件下载返回（OASX 按字节读取）"""
    content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False, default=str)
    quoted = quote(filename, safe='')
    return Response(
        content=content.encode('utf-8'),
        media_type='application/json; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"config.json\"; filename*=UTF-8''{quoted}",
            'Cache-Control': 'no-store',
        },
    )


# --------------------------------------------------------------------------------- 脱敏
def _segment_match(key: str, segment: str) -> bool:
    if segment == '*':
        return True
    if segment.endswith('*'):
        return key.startswith(segment[:-1])
    return key == segment


def _redact_by_path(node: Any, segments: list[str]) -> None:
    if not segments or not isinstance(node, dict):
        return
    segment = segments[0]
    is_leaf = len(segments) == 1
    for key, value in node.items():
        if not _segment_match(str(key), segment):
            continue
        if is_leaf:
            node[key] = REDACT_VALUE
        else:
            _redact_by_path(value, segments[1:])


def _redact_by_key(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in REDACT_KEYS:
                node[key] = REDACT_VALUE
            else:
                _redact_by_key(value)
    elif isinstance(node, list):
        for item in node:
            _redact_by_key(item)


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    """返回脱敏后的配置副本，不修改传入对象"""
    redacted = copy.deepcopy(data)
    for rule in REDACT_PATHS:
        _redact_by_path(redacted, rule.split('.'))
    _redact_by_key(redacted)
    return redacted


# --------------------------------------------------------------------------------- 导入辅助
def _fill_from_template(data: dict[str, Any]) -> dict[str, Any]:
    """
    用 config/template.json 补齐导入配置里缺失的键。
    避免外部配置文件少字段时脚本读到残缺配置。
    """
    template = read_file(str(_config_dir() / 'template.json'))
    if not isinstance(template, dict):
        return data

    filled: list[str] = []

    def _fill(target: dict, source: dict, prefix: str) -> None:
        for key, value in source.items():
            path = f'{prefix}.{key}' if prefix else str(key)
            if key not in target:
                target[key] = copy.deepcopy(value)
                filled.append(path)
            elif isinstance(target[key], dict) and isinstance(value, dict):
                _fill(target[key], value, path)

    _fill(data, template, '')
    if filled:
        preview = ', '.join(filled[:10])
        more = '' if len(filled) <= 10 else f' ...(+{len(filled) - 10})'
        logger.warning(f'[OASX] import config filled {len(filled)} missing keys from template: {preview}{more}')
    return data


async def _read_upload(file: UploadFile | None) -> str | None:
    if file is None:
        return None
    raw = await file.read()
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f'Uploaded file must be UTF-8 JSON: {e}') from e


def _parse_json_dict(text: str, what: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f'{what} JSON parse failed: {e}') from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f'{what} JSON root must be an object')
    return data


# --------------------------------------------------------------------------------- 配置：整包
@config_transfer_app.get('/config/export')
async def config_export(name: str):
    """导出整个配置（脱敏）。OASX: GET /config/export?name=xxx"""
    config_name = _validate_config_name(name, allow_template=True)
    data = _load_config_dict(config_name)
    logger.info(f'[OASX] export config {config_name}')
    return _file_response(_redact(data), f'{config_name}.json')


@config_transfer_app.post('/config/import')
async def config_import(name: str = Form(...), file: UploadFile = File(...)):
    """导入配置。OASX: POST /config/import (multipart: name, file)"""
    config_name = _validate_config_name(name, allow_template=False)
    path = _config_path(config_name)
    if path.exists():
        raise HTTPException(status_code=409, detail=f'Config already exists: {config_name}')

    text = await _read_upload(file)
    data = _parse_json_dict(text or '', 'Config')
    data = _fill_from_template(data)
    data['config_name'] = config_name

    write_file(str(path), data)
    mm.add_script_file(config_name)  # 让服务端立刻认识这个新配置
    logger.info(f'[OASX] import config {config_name} -> {path}')
    return {'name': config_name, 'file': f'{config_name}.json'}


# --------------------------------------------------------------------------------- 配置：单任务
def _load_task_fragment(config_name: str, task_name: str) -> tuple[str, str, dict[str, Any]]:
    name = _validate_config_name(config_name, allow_template=True)
    data = _load_config_dict(name)
    task_key = _normalize_task_key(task_name)
    if task_key not in data:
        raise HTTPException(status_code=404, detail=f'Task not found in config: {task_key}')
    value = data[task_key]
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f'Task JSON value must be an object: {task_key}')
    return name, task_key, value


@config_transfer_app.get('/config/task/export')
async def config_task_export(config_name: str, task_name: str):
    """导出单个任务（脱敏）。OASX: GET /config/task/export?config_name=&task_name="""
    name = _validate_config_name(config_name, allow_template=True)
    data = _load_config_dict(name)
    task_key = _normalize_task_key(task_name)
    if task_key not in data:
        raise HTTPException(status_code=404, detail=f'Task not found in config: {task_key}')
    if not isinstance(data[task_key], dict):
        raise HTTPException(status_code=400, detail=f'Task JSON value must be an object: {task_key}')
    redacted = _redact(data)
    logger.info(f'[OASX] export task {task_key} from {name}')
    return _file_response({task_key: redacted[task_key]}, f'{name}-{task_key}.json')


@config_transfer_app.get('/config/task/copy-json')
async def config_task_copy_json(config_name: str, task_name: str):
    """返回单个任务的原始 JSON（未脱敏），供面板内直接复制"""
    name, task_key, value = _load_task_fragment(config_name, task_name)
    logger.info(f'[OASX] copy-json task {task_key} from {name}')
    return {task_key: copy.deepcopy(value)}


@config_transfer_app.post('/config/task/import')
async def config_task_import(
        config_name: str = Form(...),
        task_name: str = Form(...),
        json_text: str | None = Form(None),
        file: UploadFile | None = File(None),
):
    """导入单个任务。OASX: POST /config/task/import (multipart: config_name, task_name, json_text 或 file)"""
    name = _validate_config_name(config_name, allow_template=False)
    data = _load_config_dict(name)
    task_key = _normalize_task_key(task_name)

    if (json_text is None) == (file is None):
        raise HTTPException(status_code=400, detail='Exactly one of json_text or file must be provided')
    if file is not None:
        json_text = await _read_upload(file)

    parsed = _parse_json_dict(json_text or '', 'Task')

    # 兼容三种写法：{task_key: {...}} / 含 task_key 的多个键 / 直接就是任务对象
    if isinstance(parsed.get(task_key), dict):
        task_value = parsed[task_key]
    elif len(parsed) == 1:
        only_key = next(iter(parsed.keys()))
        raise HTTPException(
            status_code=400,
            detail=f'Task JSON key mismatch: expected {task_key}, got {only_key}',
        )
    else:
        task_value = parsed

    if task_key not in data:
        raise HTTPException(status_code=404, detail=f'Task not found in config: {task_key}')

    new_data = copy.deepcopy(data)
    new_data[task_key] = task_value
    write_file(str(_config_path(name)), new_data)
    logger.info(f'[OASX] import task {task_key} -> config {name}')
    return {
        'config_name': name,
        'task_name': task_key,
        'file': f'{name}.json',
        'updated': True,
    }
