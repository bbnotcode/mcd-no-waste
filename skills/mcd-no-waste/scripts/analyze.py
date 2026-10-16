#!/usr/bin/env python3
"""Read official MCP response envelopes on stdin; emit a minimal safe summary."""
import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')


def envelope(value):
    if not isinstance(value, dict):
        raise ValueError('响应必须是JSON对象')
    if 'structuredContent' in value:
        value = value['structuredContent']
    if not isinstance(value, dict) or value.get('code') not in (200, '200') or value.get('success') is False:
        raise ValueError('接口未返回成功状态，不能作为空数据处理')
    data = value.get('data')
    if not isinstance(data, dict):
        raise ValueError('响应缺少data对象')
    return data


def parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)
    except ValueError:
        return None


def classify(coupon, now):
    exact = parse_date(coupon.get('tradeEndDateTime'))
    raw_day = coupon.get('tradeEndDate')
    day = parse_date(raw_day)
    # A malformed precise time must not silently become a confident date-only result.
    if coupon.get('tradeEndDateTime') and exact is None:
        return '时间待确认', None, False
    if exact and day and exact.date() != day.date():
        return '时间待确认', None, False
    end = exact or day
    if end is None:
        return '时间待确认', None, False
    precise = exact is not None
    if (precise and end <= now) or (not precise and end.date() < now.date()):
        return '已到期', end, precise
    days = (end.date() - now.date()).days
    return ('今天到期' if days == 0 else '未来3天到期' if days <= 3 else '以后到期'), end, precise


def analyze(payload, now):
    if now.tzinfo is None:
        raise ValueError('查询时间必须带时区')
    now = now.astimezone(TZ)
    pages = payload.get('coupons')
    pages = pages if isinstance(pages, list) else [pages]
    if not pages or len(pages) > 5:
        raise ValueError('需要1至5页卡包响应')
    data_pages = [envelope(page) for page in pages]
    account = envelope(payload.get('account'))
    rows, seen, page_numbers, totals = [], set(), set(), set()
    duplicate = False
    for data in data_pages:
        page_numbers.add(int(data['currentPage']))
        totals.add((int(data['totalPages']), int(data['totalCount'])))
        for c in data['coupons']:
            if not isinstance(c, dict):
                raise ValueError('券数据必须是对象')
            identity = c.get('id') or c.get('code')
            if identity and identity in seen:
                duplicate = True
                continue
            if identity:
                seen.add(identity)
            status, end, precise = classify(c, now)
            labels = [t['label'] for t in c.get('tags', []) if isinstance(t, dict) and t.get('label')]
            discount = c.get('discountInfo') or {}
            rows.append({
                'title': c.get('title', '未命名券'), 'status': status,
                'deadline': end.isoformat() if precise and end else end.date().isoformat() if end else None,
                'deadline_precision': 'second' if precise else 'date' if end else 'unknown',
                'validity_text': c.get('datetimeText'), 'conditions': labels,
                'channel_note': c.get('toastText'),
                'offer_description': discount.get('discountDesc'), 'offer_value': discount.get('discountValue'),
                'store_verified': False,
            })
    total_pages, total_count = next(iter(totals))
    complete = (len(totals) == 1 and not duplicate and len(page_numbers) == len(data_pages)
                and page_numbers == set(range(1, max(total_pages, 1) + 1))
                and len(rows) == total_count)
    rank = {'今天到期': 0, '未来3天到期': 1, '以后到期': 2, '时间待确认': 3, '已到期': 4}
    rows.sort(key=lambda r: (rank[r['status']], r['deadline'] or ''))
    return {
        'queried_at': now.isoformat(), 'coverage_complete': complete,
        'queried_pages': sorted(page_numbers), 'reported_total': total_count,
        'coupons': rows,
        'points': {key: account.get(key) for key in ('availablePoint', 'currentMouthExpirePoint', 'nextMouthExpirePoint')},
        'note': '到期清单不代表当前门店可用；用券价不是节省金额。日期级截止需查看券详情。',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--now', help='带时区的ISO时间；省略时使用当前北京时间')
    args = parser.parse_args()
    try:
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(TZ)
        result = analyze(json.load(sys.stdin), now)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, TypeError, KeyError) as error:
        print('无法分析：' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
