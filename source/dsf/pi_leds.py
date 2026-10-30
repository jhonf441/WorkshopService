"""
Lights on a pin of the Pi (Lights page, advanced, experimental, off by default).

By default every strip is on the Duet and each paint is a set of M150 codes: each one is a call to the board's server.
This module is the other way: a strip (the main one or an additional one) can have its OUTPUT on a pin of the Pi, with
the same zones, colours and effects as a strip on the Duet; the Pi sends the colours itself and nothing goes to the board.

  - strip over SPI: a WS2812 / SK6812 strip on the MOSI pin of an SPI bus. These strips need a precise 800 kHz signal
    that a normal program cannot make on any pin; SPI at 2.4 MHz makes it in hardware (3 SPI bits for each bit of the
    strip). Needs a level shifter 3.3 V to 5 V, the strip on its own 5 V supply and a common ground.

THE PINS OF DSF ARE NEVER USED NOR LISTED: DuetSoftwareFramework talks to the Duet over an SPI bus of the Pi (its
config.json: SpiDevice, with the chip select, MISO, MOSI and clock pins of that bus) and uses a GPIO as transfer-ready
line (TransferReadyPin) and, if set, a reset pin. Sending a strip signal on those pins would corrupt the link with the
board, so the bus of DSF is never opened and its pins are left out of the list.

Cost: a paint is one SPI write of a few hundred bytes (about 1 ms, no call to the board) and only when the frame
changed. Nothing here runs unless an output is set to the Pi; every failure (no device, no permission, busy pin) is kept
as a message for the page and the next try waits a while. It never raises into the status lights loop.
"""
import paths
import json
import os
import re
import subprocess
import threading
import time

SPI_HZ = 2400000
RESET_BYTES = 48              # >= 80 us low at 2.4 MHz (the strip latches the frame)
RETRY_S = 30.0            # after a failure
REFRESH_S = 10.0             # an unchanged frame is sent again after this long (a glitch on the line heals itself)
ORDERS = ("GRB", "RGB", "GRBW", "RGBW", "BRG")
DSF_CONFIG = paths.DSF_CONFIG

# pins of each SPI bus of the Pi 4: (chip select 0, chip select 1, MISO, MOSI, clock)
SPI_PINS = {0: (8, 7, 9, 10, 11), 1: (18, 17, 19, 20, 21)}
SPI_MOSI = {bus: p[3] for bus, p in SPI_PINS.items()}
MOSI_BUS = {pin: bus for bus, pin in SPI_MOSI.items()}
RESERVED = {0: "ID EEPROM", 1: "ID EEPROM", 14: "UART (console)", 15: "UART (console)"}

DEFAULT_OUTPUT = {"kind": "duet", "pin": 20, "order": "GRBW", "brightness": 60}


# ---- what DSF uses ----

_cache_cfg = {}


def _cfg_dsf(route=DSF_CONFIG):
    """config.json of DSF, read again at most every 60 s (the lights loop asks on every tick)."""
    current_time = time.monotonic()
    c = _cache_cfg.get(route)
    if c is not None and current_time - c[0] < 60:
        return c[1]
    try:
        with open(route, encoding="utf-8") as f:
            v = json.load(f)
    except Exception:
        v = {"SpiDevice": "/dev/spidev0.0", "TransferReadyPin": 25}
    _cache_cfg[route] = (current_time, v)
    return v


def bus_dsf(route=DSF_CONFIG):
    m = re.search(r"spidev(\d+)\.", str(_cfg_dsf(route).get("SpiDevice") or ""))
    return int(m.group(1)) if m else 0


def pins_dsf(route=DSF_CONFIG):
    """{gpio: why} of the pins DSF uses: the pins of its SPI bus, its transfer-ready line and any other "...Pin" of its
    config.json. If the file cannot be read the usual ones are assumed (SPI 0 and GPIO25)."""
    cfg = _cfg_dsf(route)
    bus = bus_dsf(route)
    out = {}
    for p, label in zip(SPI_PINS.get(bus, ()), ("CS0", "CS1", "MISO", "MOSI", "SCLK")):
        out[p] = "DSF (SPI %d %s)" % (bus, label)
    for k, v in cfg.items():
        if isinstance(v, int) and not isinstance(v, bool) and k.lower().endswith("pin") and 0 <= v <= 27:
            out[v] = "DSF (%s)" % k
    return out


# ---- configuration ----

def normalize_output(raw):
    """Output of a strip: {"tipo": "duet"} or {"tipo": "pi", "pin", "orden", "brillo"}."""
    r = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_OUTPUT)
    out["kind"] = "pi" if r.get("kind") == "pi" else "duet"
    try:
        out["pin"] = max(2, min(27, int(r.get("pin", DEFAULT_OUTPUT["pin"]))))
    except (TypeError, ValueError):
        pass
    out["order"] = r.get("order") if r.get("order") in ORDERS else DEFAULT_OUTPUT["order"]
    try:
        out["brightness"] = max(1, min(100, int(r.get("brightness", DEFAULT_OUTPUT["brightness"]))))
    except (TypeError, ValueError):
        pass
    return out


def pin_strip_valid(pin, dsf=None, spidev=None):
    """None if a strip can be driven from this pin, else the reason. Never a pin of DSF, never its SPI bus."""
    dsf = pins_dsf() if dsf is None else dsf
    if pin in dsf:
        return dsf[pin]
    bus = MOSI_BUS.get(pin)
    if bus is None:
        return "not an SPI data pin (MOSI)"
    if bus == bus_dsf():
        return "DSF (SPI bus)"
    present = (lambda b: os.path.exists("/dev/spidev%d.0" % b)) if spidev is None else spidev
    if not present(bus):
        return "SPI %d is not enabled in the Pi" % bus
    return None


# ---- encoding of the strip signal over SPI ----

def _table():
    t = []
    for v in range(256):
        bits = 0
        for i in range(7, -1, -1):
            bits = (bits << 3) | (0b110 if (v >> i) & 1 else 0b100)
        t.append(bytes([(bits >> 16) & 255, (bits >> 8) & 255, bits & 255]))
    return t


_LUT = _table()


def pixels(segments, n=None, brightness=100):
    """[(r,u,b,w,p,count), ...] -> pixels (r,g,b,w) 0..255 with the brightness p of each segment (0..255) and the global
    brightness (1..100 %). n = None: as many pixels as the segments say; with n, shorter is dark and longer is cut."""
    out = []
    g = max(1, min(100, int(brightness))) / 100.0
    for t in segments:
        r, u, b, w, p, c = (list(t) + [0] * 6)[:6]
        f = max(0.0, min(1.0, float(p) / 255.0)) * g
        px = (int(r * f), int(u * f), int(b * f), int(w * f))
        out.extend([px] * max(0, int(c)))
    if n is not None:
        out = out[:n]
        out.extend([(0, 0, 0, 0)] * (n - len(out)))
    return out


def encode(pix, order="GRBW"):
    """Pixels -> the bytes to send over SPI. A strip without a white channel gets the white mixed into the colours
    (the same rule the screens use)."""
    order = order if order in ORDERS else "GRBW"
    buf = bytearray()
    for (r, g, b, w) in pix:
        if "W" not in order and w:
            r, g, b = min(255, r + int(w * 0.7)), min(255, g + int(w * 0.7)), min(255, b + int(w * 0.7))
        ch = {"R": r, "G": g, "B": b, "W": w}
        for letter in order:
            buf += _LUT[ch[letter] & 255]
    buf += bytes(RESET_BYTES)
    return bytes(buf)


# ---- pins of the Pi ----

_PINCTRL = re.compile(r"^\s*(\d+):\s+(\S+)\s+(?:\S+\s+)?(\S+)\s+\|\s+(\S+)\s+//\s+(.*)$")


def list_items_pins(raw_text=None, dsf=None, spidev=None):
    """The GPIO 2..27 the Pi can offer, with what each one is doing and what this module can do with it. The pins of
    DSF are NOT in the list. `texto` = the output of `pinctrl get` (tests)."""
    if raw_text is None:
        try:
            raw_text = subprocess.run(["pinctrl", "get"], capture_output=True, text=True, timeout=3).stdout
        except Exception:
            raw_text = ""
    dsf = pins_dsf() if dsf is None else dsf
    out = []
    for line in (raw_text or "").splitlines():
        m = _PINCTRL.match(line)
        if not m:
            continue
        gpio = int(m.group(1))
        if gpio < 2 or gpio > 27 or gpio in dsf:
            continue
        func, label = m.group(2), m.group(5)
        desc = label.split("=", 1)[1].strip() if "=" in label else label
        alt = func.startswith("a")
        used = alt
        reason = desc if alt else ""
        if gpio in RESERVED:
            used, reason = True, RESERVED[gpio]
        led_strip = pin_strip_valid(gpio, dsf, spidev) is None
        out.append({"gpio": gpio, "func": desc, "free": not used, "reason": reason,
                    "strip_spi": led_strip})
    return out


# ---- one strip over SPI ----

class StripSpi:
    def __init__(self, pin):
        self.pin = pin
        self.order = "GRBW"
        self.brightness = 60
        self.lock = threading.Lock()
        self.spi = None
        self.last = None          # last frame sent (bytes)
        self.last_t = 0.0
        self.error = ""
        self.error_t = 0.0
        self.writes = 0
        self.ms = 0.0
        self.testing_until = 0.0

    def _open(self):
        bus = MOSI_BUS[self.pin]
        if bus == bus_dsf():
            raise OSError("the SPI bus of DSF is never used")
        import spidev
        s = spidev.SpiDev()
        s.open(bus, 0)
        s.max_speed_hz = SPI_HZ
        s.mode = 0
        s.bits_per_word = 8
        self.spi = s

    def shut(self):
        try:
            if self.spi is not None:
                self.spi.close()
        except Exception:
            pass
        self.spi = None

    def _write(self, payload, current_time):
        try:
            if self.spi is None:
                self._open()
            t0 = time.monotonic()
            for i in range(0, len(payload), 4000):
                piece = payload[i:i + 4000]
                if hasattr(self.spi, "writebytes2"):
                    self.spi.writebytes2(piece)
                else:
                    self.spi.xfer2(list(piece))
            self.ms = (time.monotonic() - t0) * 1000.0
            self.last, self.last_t = payload, current_time
            self.writes += 1
            self.error = ""
            return True
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            self.error_t = current_time
            self.shut()
            return False

    def paint(self, segments, current_time=None):
        """Send the frame of the strip (all its zones, in order). True if it was written."""
        current_time = time.monotonic() if current_time is None else current_time
        if current_time < self.testing_until:
            return False
        if self.error and current_time - self.error_t < RETRY_S:
            return False
        payload = encode(pixels(segments, None, self.brightness), self.order)
        with self.lock:
            if payload == self.last and current_time - self.last_t < REFRESH_S:
                return False
            return self._write(payload, current_time)

    def power_off(self, n=1):
        with self.lock:
            self.testing_until = 0.0
            self._write(encode([(0, 0, 0, 0)] * max(1, n), self.order), time.monotonic())

    def probe(self, n, seconds=4):
        """A moving colour on the n LEDs for a few seconds; the next paint puts the normal frame back."""
        seconds = max(1, min(15, int(seconds)))
        n = max(1, min(300, int(n)))
        t_end = time.monotonic() + seconds
        self.testing_until = t_end

        def execute():
            step = 0
            f = self.brightness / 100.0
            while time.monotonic() < t_end:
                pix = []
                for k in range(n):
                    h = (k * 6 + step * 8) % 256
                    r, g, b = (h if h < 128 else 255 - h) // 2, ((h + 85) % 256) // 4, ((h + 170) % 256) // 4
                    pix.append((int(r * f), int(g * f), int(b * f), 0))
                with self.lock:
                    self._write(encode(pix, self.order), time.monotonic())
                step += 1
                time.sleep(0.06)
            self.testing_until = 0.0
            self.last = None
        threading.Thread(target=execute, name="pi-leds-test", daemon=True).start()
        return {"ok": True, "seconds": seconds}

    def status(self):
        return {"pin": self.pin, "error": self.error or None, "writes": self.writes, "ms": round(self.ms, 2)}


# ---- the strips that have their output on the Pi (by pin) ----

STRIPS = {}
_lock = threading.Lock()


def configure_strips(wanted):
    """deseadas = {pin: {"orden", "brillo"}} for every strip whose output is the Pi. Strips that are no longer wanted
    are closed. A pin that cannot drive a strip (a pin of DSF, no SPI) is ignored."""
    with _lock:
        for pin in list(STRIPS):
            if pin not in wanted:
                STRIPS.pop(pin).shut()
        for pin, c in wanted.items():
            if pin_strip_valid(pin) is not None:
                continue
            t = STRIPS.get(pin)
            if t is None:
                t = STRIPS[pin] = StripSpi(pin)
            order, brightness = c.get("order", "GRBW"), c.get("brightness", 60)
            if (t.order, t.brightness) != (order, brightness):
                t.last = None
            t.order, t.brightness = order, brightness


def paint(pin, segments, current_time=None):
    t = STRIPS.get(pin)
    return t.paint(segments, current_time) if t is not None else False


def power_off_all():
    for t in list(STRIPS.values()):
        t.power_off()


def states():
    return [t.status() for t in STRIPS.values()]
