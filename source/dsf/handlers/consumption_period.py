"""
Internal implementation of the API operation(s) energy.period (api_ops.py maps their named
arguments to the one-letter parameters below).

Consumption summary by "buckets" (hours/days/months) for the Tuya-style
view of dwc-src/Consumption.vue (card with a big number + bar chart +
date navigator + day/month/year tabs) -- unlike
consumption_query.py (raw paginated history + power series of the
whole window), this returns energy (kWh) already aggregated per bucket,
ready to draw bars without the frontend adding up thousands of rows.

Usage: <params> T"day|month|year" R"2026-10-07"
  T = granularity of the period (default "day")
  R = reference date YYYY-MM-DD (default today) -- for "month" the month of
      that date is used, for "year" its year

"""
import json
from datetime import datetime, timedelta

import db
from messages import M

MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _buckets_day(ref):
    begin = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    limits = [begin + timedelta(hours=h) for h in range(25)]
    labels = [f"{h:02d}:00" for h in range(24)]
    tooltips = [f"{h:02d}:00-{(h + 1) % 24:02d}:00" for h in range(24)]
    label = f"{ref.day} {MONTHS[ref.month - 1]}"
    return limits, labels, tooltips, label


def _buckets_month(ref):
    begin = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if begin.month == 12:
        end = begin.replace(year=begin.year + 1, month=1)
    else:
        end = begin.replace(month=begin.month + 1)
    day_count = (end - begin).days
    limits = [begin + timedelta(days=d) for d in range(day_count + 1)]
    labels = [str(d + 1) for d in range(day_count)]
    tooltips = [f"{d + 1} {MONTHS[begin.month - 1]}" for d in range(day_count)]
    label = f"{MONTHS[begin.month - 1]} {begin.year}"
    return limits, labels, tooltips, label


def _buckets_year(ref):
    begin = ref.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    limits = []
    for m in range(1, 14):
        limits.append(begin.replace(month=m) if m <= 12 else begin.replace(year=begin.year + 1, month=1))
    labels = [MONTHS[m - 1] for m in range(1, 13)]
    tooltips = [f"{MONTHS[m - 1]} {begin.year}" for m in range(1, 13)]
    label = str(begin.year)
    return limits, labels, tooltips, label


def run(params, bridge, config):
    period = str(params.get("T", "day")).strip().lower()
    ref_str = str(params.get("R", "")).strip()
    try:
        ref = datetime.strptime(ref_str, "%Y-%m-%d") if ref_str else datetime.now()
    except ValueError:
        return json.dumps({"error": M("consumption_period_invalid_r_date_use_yyyy_mm")})

    if period == "month":
        limits, labels, tooltips, label = _buckets_month(ref)
    elif period == "year":
        limits, labels, tooltips, label = _buckets_year(ref)
    else:
        period = "day"
        limits, labels, tooltips, label = _buckets_day(ref)

    current_time = datetime.now()
    # 2026-10-10: several meters. M"<key>" (without M = the main one) or M"total"
    # (sum of the own-line ones, bucket by bucket).
    import meters
    lst = [m for m in meters.entries() if meters.configured(m)]
    prin = meters.main(lst)
    key = str(params.get("M", "")).strip().lower() or (prin["slot"] if prin else "general")
    if key == "total":
        keys = [m["slot"] for m in meters.of_line_own(lst)] or ([prin["slot"]] if prin else ["general"])
    else:
        keys = [key]
    # kWh per bucket adding counter increases (db.consumption_kwh_buckets): it withstands
    # loose readings at 0 and meter restarts
    series = [db.consumption_kwh_buckets([_iso(t) for t in limits], c) for c in keys]

    buckets = []
    current_index = None
    for i in range(len(labels)):
        vals = [sn[i] for sn in series if sn[i] is not None]
        kwh = round(sum(vals), 4) if vals else None
        buckets.append({"label": labels[i], "tooltip": tooltips[i], "kwh": kwh})
        if limits[i] <= current_time < limits[i + 1]:
            current_index = i

    with_data = [b["kwh"] for b in buckets if b["kwh"] is not None]
    total = round(sum(with_data), 4) if with_data else None

    return json.dumps({
        "period": period,
        "label": label,
        "total_kwh": total,
        "current_index": current_index,
        "buckets": buckets,
        "meter": key,
    })
