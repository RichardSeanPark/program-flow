"""Independent market-session views of cumulative program net buy amounts."""
SESSIONS = {
    'NXT_AM': ('NXT', '0800', '0859'),
    'KRX': ('KRX', '0900', '1530'),
    'NXT_PM': ('NXT', '1530', '2000'),
}


def build_sessions(rows):
    result = {}
    for key, (market, start, end) in SESSIONS.items():
        market_rows = sorted((r for r in rows if r['market'] == market), key=lambda r: r['tm'])
        active = [r for r in market_rows if start <= r['tm'][:4] <= end]
        prior = [r for r in market_rows if r['tm'][:4] < start]
        if key == 'NXT_PM' and active and not prior:
            result[key] = {'points': [], 'latest': None, 'reason': '15:30 이전 기준값 없음'}
            continue
        baseline = prior[-1]['net_amt'] if key == 'NXT_PM' and prior else 0
        points = [{'tm': r['tm'], 'net_amt': r['net_amt'] - baseline} for r in active]
        result[key] = {'points': points, 'latest': points[-1]['net_amt'] if points else None,
                       'reason': '' if points else '관측 데이터 없음'}
    return result
