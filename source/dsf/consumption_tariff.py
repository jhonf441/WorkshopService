"""Currency and cost per kWh behind the operations energy.rate_get / energy.rate_set (energy_ops.py registers them; phase 5 of the
redesign, it replaces handlers/consumption_tariff.py).

The currency and the cost per kWh are typed by hand for the "Consumption" tab (dwc-src/Consumption.vue): this does NOT convert currency
or fetch a live rate from anywhere, it is just a label (currency) plus a number (cost per kWh in that currency) that the user already
knows from the bill, multiplied against the kWh of each period (see consumption_period.py) to show an approximate cost. It is kept in
config.json (config["consumption_tariff"]) with the rest of the plugin configuration.
"""
import activity
import machine_profile
from messages import M

CURRENCY_DEFAULT = ""  # no fixed currency: the one of the machine profile, else empty


def _default_currency():
    try:
        return str(machine_profile.load().get("currency") or CURRENCY_DEFAULT)
    except Exception:
        return CURRENCY_DEFAULT


def rate(config):
    """{"currency", "value_kwh"} as saved (the currency of the machine profile when none was saved)."""
    tariff = config.get("consumption_tariff", {})
    return {
        "currency": tariff.get("currency") or _default_currency(),
        "value_kwh": tariff.get("value_kwh", 0.0),
    }


def save_rate(bridge, config, *, currency, value):
    """Saves the currency (upper case; empty means the one of the profile) and the cost per kWh (never below 0), notes it in Activity
    and returns the new state."""
    currency = str(currency).strip().upper() or _default_currency()
    try:
        value = max(0.0, float(value))
    except (TypeError, ValueError):
        value = 0.0
    config["consumption_tariff"] = {"currency": currency, "value_kwh": value}
    bridge.save_config()
    activity.log_event(bridge, "config", M("tariff_updated", value=value, currency=currency))
    return rate(config)
