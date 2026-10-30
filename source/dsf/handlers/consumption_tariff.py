"""
Internal implementation of the API operation(s) energy.rate_get, energy.rate_set (api_ops.py maps their named
arguments to the one-letter parameters below).

Saves/queries the currency and the cost per kWh that the user types by hand
for the "Consumption" tab (dwc-src/Consumption.vue) -- this does NOT convert
currency or fetch a live rate from anywhere, it is just a label
(currency) + a number (cost per kWh in that currency) that the user already
knows from their bill, used to multiply against the kWh of each period
(day/month/year, see consumption_period.py) and show an approximate cost in
the UI. It is saved in config.json together with the rest of the plugin's
config -- the same pattern as "apagado" in handlers/shutdown.py (read/write a
config key, bridge.save_config(), activity log on the change).

Usage: <params>                            -> query (JSON)
     <params> C"guardar" S"USD" V"0.15"  -> saves currency+value,
                                                            returns the updated JSON
  C = action, "consultar" (default) or "guardar"
  S = currency code (3-4 letters, e.g. USD/EUR/ARS/MXN) -- only a
      display label, not validated against any ISO 4217 list
  V = cost per kWh in that currency (number, e.g. 0.15 or 850.0)

"""
import json

import activity
from messages import M, J, B

CURRENCY_DEFAULT = ""  # no fixed currency: the one of the machine profile, else empty


def _default_currency():
    try:
        import machine_profile
        return str(machine_profile.load().get("currency") or CURRENCY_DEFAULT)
    except Exception:
        return CURRENCY_DEFAULT


def _state(config):
    tariff = config.get("consumption_tariff", {})
    return {
        "currency": tariff.get("currency") or _default_currency(),
        "value_kwh": tariff.get("value_kwh", 0.0),
    }


def run(params, bridge, config):
    action = str(params.get("C", "query")).strip().lower()

    if action == "save":
        currency = str(params.get("S", "")).strip().upper() or _default_currency()
        try:
            value = max(0.0, float(params.get("V", 0)))
        except (TypeError, ValueError):
            value = 0.0

        config["consumption_tariff"] = {"currency": currency, "value_kwh": value}
        bridge.save_config()
        activity.log_event(
            bridge, "config",
            M("tariff_updated", value=value, currency=currency)
        )

    return json.dumps(_state(config))
