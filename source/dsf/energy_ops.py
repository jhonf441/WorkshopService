"""API operations of the energy meters: energy.history (consumption_history.py), energy.rate_get and energy.rate_set
(consumption_tariff.py). api_ops.init registers them through build(ctx), like settings_ops. The class, arguments, role
(permissions.py) and flags are the ones they had when they were handlers/consumption_query.py and handlers/consumption_tariff.py.
"""
import consumption_history
import consumption_tariff
from activity_ops import D_FROM, D_LIMIT, D_OFFSET, D_TO
from workshop_api import READ, WRITE, Arg, Op

D_METER = "Key of the meter (empty: the main one, the one that feeds the system); \"total\" adds up the meters on their own line."


def _history(args, c):
    return consumption_history.history(since=args["from"], until=args.get("to", ""), limit=args.get("limit", 50),
                                       offset=args.get("offset", 0), meter=args.get("meter", ""))


def build(ctx):
    """The operations; ctx is api_ops._ctx (bridge, config)."""
    S, I, N = "str", "int", "num"
    a = Arg

    def rate_get(args, c):
        return consumption_tariff.rate(ctx["config"])

    def rate_set(args, c):
        return consumption_tariff.save_rate(ctx["bridge"], ctx["config"], currency=args["currency"], value=args["value"])

    return [
        Op("energy.history", _history, READ,
           {"from": a(S, True, desc=D_FROM), "to": a(S, desc=D_TO), "limit": a(I, min=1, max=200, desc=D_LIMIT), "offset": a(I, min=0, desc=D_OFFSET),
            "meter": a(S, desc=D_METER)},
           "Returns the energy meter readings of a date range, paged, with a summary (kWh, peak and average power) and the power series of the range."),
        Op("energy.rate_get", rate_get, READ, {}, "Returns the currency and the price of one kWh used to show the approximate cost of the energy."),
        Op("energy.rate_set", rate_set, WRITE,
           {"currency": a(S, True, desc="Currency code shown next to the costs, for example USD, EUR, MXN (only a label; empty: the currency of the machine profile, or none)."),
            "value": a(N, True, min=0, desc="Price of one kWh in that currency.")},
           "Saves the currency and the price of one kWh (a label and a number, no conversion). Logged in Activity."),
    ]
