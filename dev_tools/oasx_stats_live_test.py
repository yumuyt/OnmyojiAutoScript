"""统计接口（阶段 3）实测：造一份符合本仓库格式的日志 → 真实 HTTP 校验（含 SSE）"""
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import requests

B = 'http://127.0.0.1:22289'
LOG = Path.cwd() / 'log'
LOG.mkdir(exist_ok=True)
today = datetime.now().strftime('%Y-%m-%d')
SCRIPT = 'statstest'
log_file = LOG / f'{today}_{SCRIPT}.txt'

ok = 0
fail = []


def check(name, condition, extra=''):
    global ok
    if condition:
        ok += 1
        print('  [OK] ' + name + ('  ' + extra if extra else ''))
    else:
        fail.append(name)
        print('  [FAIL] ' + name + ('  ' + extra if extra else ''))


def info(msg):
    return f'2026-09-24 20:00:00.000 |            script.py:0000 |     INFO | {msg}'


BANNER = '━' * 80
BATTLE_BANNER = '─' * 30 + ' General battle start ' + '─' * 30


def record(stamp, msg):
    return f'2026-09-24 {stamp} |            script.py:0000 |     INFO | {msg}'


content = '\n'.join([
    BANNER, '─' * 30 + ' START ' + '─' * 30, BANNER,
    record('20:09:59.000', 'Begin task'),
    # --- 运行 1：Alchemy，两场战斗（每场中间都有带时间戳的战斗过程日志，模拟真实日志）
    record('20:10:00.000', 'Scheduler: Start task `Alchemy`'),
    BANNER, BATTLE_BANNER, BANNER,
    record('20:10:01.000', 'Battle process line A'),
    record('20:10:05.000', 'Battle done'),
    record('20:11:00.000', 'Some middle line'),
    BANNER, BATTLE_BANNER, BANNER,
    record('20:12:00.000', 'Battle process line B'),
    record('20:12:08.000', 'Battle done'),
    record('20:15:00.000', 'Scheduler: End task `Alchemy`'),
    # --- 运行 2：Orochi，没有战斗
    record('20:20:00.000', 'Scheduler: Start task `Orochi`'),
    record('20:21:30.000', 'Scheduler: End task `Orochi`'),
    '',
])
log_file.write_text(content, encoding='utf-8')

print('== 1. 日期列表 ==')
r = requests.get(B + f'/stats/{SCRIPT}/dates', timeout=15)
check('HTTP 200', r.status_code == 200, str(r.status_code))
body = r.json()
check('包含今天', today in body['dates'], json.dumps(body, ensure_ascii=False)[:80])

print('== 2. 统计快照 ==')
r = requests.get(B + f'/stats/{SCRIPT}', params={'date': today}, timeout=15)
check('HTTP 200', r.status_code == 200, str(r.status_code))
s = r.json()
check('总任务次数=2', s['total_task_run_count'] == 2, str(s['total_task_run_count']))
check('总战斗次数=2', s['total_battle_count'] == 2, str(s['total_battle_count']))
check('总时长=390s', abs(s['total_runtime_seconds'] - 390.0) < 0.5, str(s['total_runtime_seconds']))
alchemy = s['tasks'].get('Alchemy')
orochi = s['tasks'].get('Orochi')
check('Alchemy 有统计', alchemy is not None)
check('Alchemy 时长=300s', alchemy and abs(alchemy['total_duration_seconds'] - 300.0) < 0.5,
      str(alchemy and alchemy['total_duration_seconds']))
check('Alchemy 战斗 2 场，均时 6.0s',
      alchemy and alchemy['battle']['count'] == 2 and abs(alchemy['battle']['avg_duration_seconds'] - 6.0) < 0.01,
      json.dumps(alchemy['battle'], ensure_ascii=False) if alchemy else '')
check('Alchemy runs 明细 1 条且字段齐全',
      alchemy and len(alchemy['runs']) == 1 and {'start_time', 'end_time', 'duration_seconds', 'battle'} <= set(alchemy['runs'][0]))
check('Orochi 时长=90s 且无战斗',
      orochi and abs(orochi['total_duration_seconds'] - 90.0) < 0.5 and orochi['battle'] is None,
      json.dumps(orochi, ensure_ascii=False)[:120] if orochi else '')

print('== 3. 边界 ==')
r = requests.get(B + f'/stats/{SCRIPT}', params={'date': '2026-13-99'}, timeout=15)
check('非法日期 -> 422', r.status_code == 422, str(r.status_code))
r = requests.get(B + f'/stats/{SCRIPT}', params={'date': '2020-01-01'}, timeout=15)
check('没有日志的日期 -> 全 0', r.status_code == 200 and r.json()['total_task_run_count'] == 0, str(r.status_code))
r = requests.get(B + f'/stats/{SCRIPT}/stream', params={'date': '2020-01-01'}, timeout=15)
check('非今天的 SSE -> 400', r.status_code == 400, str(r.status_code))

print('== 4. 统计 SSE（先拿首帧，再追加一次任务运行）==')
events = []
updates = []
with requests.get(B + f'/stats/{SCRIPT}/stream', params={'date': today}, stream=True, timeout=40) as resp:
    check('HTTP 200 + text/event-stream', resp.status_code == 200 and 'text/event-stream' in resp.headers.get('content-type', ''),
          resp.headers.get('content-type', ''))
    buf = ''
    started = time.time()
    for chunk in resp.iter_content(chunk_size=256, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk
        while '\n\n' in buf:
            raw, buf = buf.split('\n\n', 1)
            name = next((l.split(':', 1)[1].strip() for l in raw.splitlines() if l.startswith('event:')), '')
            payload = next((l.split(':', 1)[1].strip() for l in raw.splitlines() if l.startswith('data:')), '{}')
            events.append(name)
            if name == 'update':
                updates.append(json.loads(payload))
                if len(updates) == 1:
                    check('首帧 update 带总数', updates[0]['total_task_run_count'] == 2, str(updates[0]['total_task_run_count']))
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(record('20:30:00.000', 'Scheduler: Start task `DailyTrifles`') + '\n')
                        f.write(record('20:31:00.000', 'Scheduler: End task `DailyTrifles`') + '\n')
                elif len(updates) == 2:
                    check('追加后收到第二次 update 且总数=3', updates[1]['total_task_run_count'] == 3,
                          str(updates[1]['total_task_run_count']))
                    check('changed_tasks 只带变化的任务', 'DailyTrifles' in updates[1]['changed_tasks'],
                          ','.join(updates[1]['changed_tasks'].keys()))
        if len(updates) >= 2 or time.time() - started > 20:
            break
check('先收到 ready/update 事件', bool(events), ','.join(events[:4]))
check('收到两次 update', len(updates) >= 2, f'{len(updates)} 次')

# ---------------------------------------------------------------- 清理
log_file.unlink(missing_ok=True)
shutil.rmtree(LOG / 'error', ignore_errors=True) if False else None

print()
print(f'通过 {ok} 项，失败 {len(fail)} 项' + (' -> ' + ', '.join(fail) if fail else ''))
raise SystemExit(1 if fail else 0)
