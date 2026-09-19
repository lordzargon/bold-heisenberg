import re
import datetime

def parse_date_to_timestamp(date_val):
    if not date_val:
        return '', 0.0

    if isinstance(date_val, (int, float)):
        ts = float(date_val)
        if ts > 1e11:
            ts = ts / 1000.0
        try:
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.strftime('%d %b %Y'), ts
        except Exception:
            return '', 0.0

    if isinstance(date_val, (datetime.datetime, datetime.date)):
        if isinstance(date_val, datetime.datetime):
            dt = date_val if date_val.tzinfo else date_val.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = datetime.datetime(date_val.year, date_val.month, date_val.day, tzinfo=datetime.timezone.utc)
        return dt.strftime('%d %b %Y'), dt.timestamp()

    if not isinstance(date_val, str):
        return '', 0.0

    date_str = date_val.strip()
    if not date_str:
        return '', 0.0

    if date_str.isdigit():
        ts = float(date_str)
        if ts > 1e11:
            ts = ts / 1000.0
        try:
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.strftime('%d %b %Y'), ts
        except Exception:
            pass

    rel_m = re.search(r'(?:posted\s+)?(?:about\s+)?(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago', date_str, re.IGNORECASE)
    if rel_m:
        val = int(rel_m.group(1))
        unit = rel_m.group(2).lower()
        delta = datetime.timedelta(days=0)
        if unit == 'minute':
            delta = datetime.timedelta(minutes=val)
        elif unit == 'hour':
            delta = datetime.timedelta(hours=val)
        elif unit == 'day':
            delta = datetime.timedelta(days=val)
        elif unit == 'week':
            delta = datetime.timedelta(weeks=val)
        elif unit == 'month':
            delta = datetime.timedelta(days=val * 30)
        elif unit == 'year':
            delta = datetime.timedelta(days=val * 365)
        dt = datetime.datetime.now(datetime.timezone.utc) - delta
        return dt.strftime('%d %b %Y'), dt.timestamp()

    if re.search(r'\byesterday\b', date_str, re.IGNORECASE):
        dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        return dt.strftime('%d %b %Y'), dt.timestamp()

    if re.search(r'\btoday\b', date_str, re.IGNORECASE):
        dt = datetime.datetime.now(datetime.timezone.utc)
        return dt.strftime('%d %b %Y'), dt.timestamp()

    clean = date_str.strip()
    clean = re.sub(r'\s*(UTC|GMT)$', '', clean, flags=re.IGNORECASE).strip()

    def _truncate_fraction(m):
        frac = m.group(1)[:7]
        tz = m.group(2) or ''
        return frac + tz

    clean_iso = re.sub(r'(\.\d+)(Z|[+-]\d{2}:?\d{2})?$', _truncate_fraction, clean)
    clean_iso = clean_iso.replace('Z', '+00:00')

    try:
        dt = datetime.datetime.fromisoformat(clean_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.strftime('%d %b %Y'), dt.timestamp()
    except Exception:
        pass

    iso_clean = re.sub(r'(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$', '', clean)
    formats = [
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
        '%d %b %Y',
        '%d %B %Y',
        '%b %d, %Y',
        '%B %d, %Y',
        '%d/%m/%Y',
        '%m/%d/%Y',
        '%d-%m-%Y',
        '%d-%b-%Y',
        '%b %d %Y'
    ]
    for fmt in formats:
        try:
            target_str = iso_clean[:19] if ('T' in fmt or (' ' in fmt and ':' in fmt)) else iso_clean[:10] if fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y') else clean
            dt = datetime.datetime.strptime(target_str, fmt)
            ts = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
            return dt.strftime('%d %b %Y'), ts
        except Exception:
            continue

    return date_str, 0.0
