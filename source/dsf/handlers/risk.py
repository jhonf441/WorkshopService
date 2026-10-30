"""
Internal implementation of the API operation(s) risk.list, risk.start, risk.end (api_ops.py maps their named
arguments to the one-letter parameters below).

Active risk (level 4 of the warning standard): something that leaves the
machine without a protection while it lasts. The LED strip paints it and the
screens show a fixed warning. See dsf/risk_rules.py.

Use: <params> S"start" I"<id>" T"<text>" [E"<English text>"] [D<seconds, default 600>]
     <params> S"end" I"<id>"
     <params>                    -> JSON list of the active ones
T is the Spanish text (or the only one the caller has), E the English one;
the pages show the one of the DWC language.
"""
import json

import messages
import risk_rules


def run(params, bridge, config):
    action = str(params.get("S", "list")).strip().lower()
    ident = str(params.get("I", "")).strip()
    if action in ("start", "start"):
        if not ident:
            return 'Error: missing I"<id>"'
        risk_rules.launch(ident, params.get("T") or params.get("E") or ident, params.get("D") or 600,
                       text_en=params.get("E") or None)
        return f"Active risk: {ident}"
    if action in ("end", "terminar", "end"):
        if not ident:
            return 'Error: missing I"<id>"'
        risk_rules.finish(ident)
        return f"Risk ended: {ident}"
    return json.dumps(messages.localize(risk_rules.active(), messages.current_language()))
