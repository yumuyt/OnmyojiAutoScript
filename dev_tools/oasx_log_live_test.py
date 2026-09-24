"""日志接口（阶段 2）实测：造数据 → 真实 HTTP 校验（含 SSE）"""
import base64
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import requests

B = 'http://127.0.0.1:22289'
ROOT = Path.cwd()
LOG = ROOT / 'log'
LOG.mkdir(exist_ok=True)
today = datetime.now().strftime('%Y-%m-%d')

PNG_1PX = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

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


# ---------------------------------------------------------------- 造数据
log_file = LOG / f'{today}_testlog.txt'
lines = [f'line-{i:03d} 测试行 ' + 'x' * (i % 7) for i in range(1, 41)]
log_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
(old_log := LOG / '2020-01-01_testlog.txt').write_text('old-1\nold-2\n', encoding='utf-8')

error_id = str(int(time.time() * 1000))
error_dir = LOG / 'error' / error_id
error_dir.mkdir(parents=True, exist_ok=True)
(error_dir / 'log.txt').write_text('Traceback: boom\n' * 5, encoding='utf-8')
(error_dir / 'shot-1.png').write_bytes(PNG_1PX)

print('== 1. 日志窗口（最新一屏）==')
r = requests.get(B + '/logs/testlog', timeout=15)
check('HTTP 200', r.status_code == 200, str(r.status_code))
data = r.json()
check('返回 40 行', len(data['lines']) == 40, f"实际 {len(data['lines'])}")
check('末行是最新', data['lines'][-1]['text'].startswith('line-040'), data['lines'][-1]['text'][:30])
check('有 older_cursor（因为还有 2020 的旧文件）', bool(data['older_cursor']))
check('line 字段齐全', all(k in data['lines'][0] for k in
                           ('file_name', 'line_no', 'offset', 'byte_length', 'text', 'line_truncated')))
check('limits 回显', data['limits']['limit_lines'] > 0 and data['limits']['max_line_bytes'] > 0)
check('live_cursor 存在', bool(data['live_cursor']))

print('== 2. 限制行数 + 一路向更旧翻页（应跨到 2020 的旧文件）==')
r = requests.get(B + '/logs/testlog', params={'limit_lines': 10}, timeout=15)
page1 = r.json()
check('只返回 10 行', len(page1['lines']) == 10, f"实际 {len(page1['lines'])}")
check('has_older=True', page1['has_older'] is True)

collected = list(page1['lines'])
cursor = page1['older_cursor']
pages = 1
reached_start = False
file_order = ['2026-09-24_testlog.txt', '2020-01-01_testlog.txt']  # 新 -> 旧


def rank(line):
    index = file_order.index(line['file_name']) if line['file_name'] in file_order else 99
    return (-index, line['line_no'])  # 越大越新


while cursor and pages < 10:
    r = requests.get(B + '/logs/testlog', params={'cursor': cursor, 'limit_lines': 10}, timeout=15)
    page = r.json()
    cur_last = page['lines'][-1] if page['lines'] else None
    prev_first = collected[0]
    check(f'第 {pages + 1} 页比上一页更旧',
          cur_last is not None and rank(cur_last) < rank(prev_first),
          f"{cur_last['file_name']}:{cur_last['line_no']} < {prev_first['file_name']}:{prev_first['line_no']}")
    collected = list(page['lines']) + collected
    cursor = page['older_cursor']
    reached_start = page['reached_start']
    pages += 1

files_seen = {line['file_name'] for line in collected}
texts = {line['text'] for line in collected}
check('翻到了 2020 的旧文件', '2020-01-01_testlog.txt' in files_seen, ','.join(sorted(files_seen)))
check('旧文件内容也在里面', {'old-1', 'old-2'} <= texts)
check('最终到达日志起点', reached_start is True)
check('两个文件的 42 行全部收齐', len(collected) == 42, f"实际 {len(collected)}")

print('== 3. 空/异常输入 ==')
r = requests.get(B + '/logs/not_exist_script', timeout=15)
check('不存在的脚本返回空窗口而不是 500', r.status_code == 200 and r.json()['lines'] == [], str(r.status_code))
r = requests.get(B + '/logs/testlog', params={'cursor': 'not-a-cursor'}, timeout=15)
check('非法 cursor -> 400', r.status_code == 400, str(r.status_code))

print('== 4. 路由顺序：/logs/errors 不能被 /logs/{script_name} 抢走 ==')
r = requests.get(B + '/logs/errors', timeout=15)
check('HTTP 200 且是列表结构', r.status_code == 200 and 'items' in r.json(), str(r.status_code))
items = r.json()['items']
check('包含刚造的错误目录', any(i['id'] == error_id for i in items), f"{len(items)} 项")
item = next(i for i in items if i['id'] == error_id)
check('legacy=True（纯时间戳目录）', item['legacy'] is True)
check('image_count=1 / log_size>0', item['image_count'] == 1 and item['log_size'] > 0)

print('== 5. 错误详情与截图 ==')
r = requests.get(B + f'/logs/errors/{error_id}', timeout=15)
detail = r.json()
check('log.txt 内容正确', 'Traceback: boom' in detail['log']['content'])
check('截图列表 1 张', len(detail['images']) == 1, json.dumps(detail['images'][:1], ensure_ascii=False)[:120])
img_url = detail['images'][0]['url']
r = requests.get(B + img_url, timeout=15)
check('截图可下载且是 PNG', r.status_code == 200 and r.content[:8] == b'\x89PNG\r\n\x1a\n', str(r.status_code))
r = requests.get(B + '/logs/errors/..%2F..%2Fconfig', timeout=15)
check('路径穿越被拒', r.status_code in (400, 404), str(r.status_code))
r = requests.get(B + '/logs/errors/99999999999999', timeout=15)
check('不存在的错误目录 -> 404', r.status_code == 404, str(r.status_code))

print('== 6. 实时日志 SSE ==')
events = []
with requests.get(B + '/logs/testlog/stream', params={'limit_lines': 50}, stream=True, timeout=30) as resp:
    check('HTTP 200 + text/event-stream', resp.status_code == 200 and 'text/event-stream' in resp.headers.get('content-type', ''),
          resp.headers.get('content-type', ''))
    buf = ''
    started = time.time()
    appended = False
    for chunk in resp.iter_content(chunk_size=256, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk
        while '\n\n' in buf:
            raw, buf = buf.split('\n\n', 1)
            name = next((l.split(':', 1)[1].strip() for l in raw.splitlines() if l.startswith('event:')), '')
            payload = next((l.split(':', 1)[1].strip() for l in raw.splitlines() if l.startswith('data:')), '{}')
            events.append(name)
            if name == 'ready':
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write('live-appended-line\n')
            if name == 'append':
                body = json.loads(payload)
                check('append 事件带 lines/next_cursor', bool(body.get('lines')) and bool(body.get('next_cursor')))
                check('append 内容是刚追加的行', body['lines'][-1]['text'] == 'live-appended-line',
                      body['lines'][-1]['text'][:40])
                appended = True
        if appended or time.time() - started > 12:
            break
check('先收到 ready 事件', 'ready' in events, ','.join(events[:4]))
check('收到 append 事件', appended, ','.join(events[:6]))

# ---------------------------------------------------------------- 清理造的数据
shutil.rmtree(error_dir, ignore_errors=True)
log_file.unlink(missing_ok=True)
old_log.unlink(missing_ok=True)

print()
print(f'通过 {ok} 项，失败 {len(fail)} 项' + (' -> ' + ', '.join(fail) if fail else ''))
raise SystemExit(1 if fail else 0)
