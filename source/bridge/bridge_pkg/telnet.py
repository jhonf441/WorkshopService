"""The Telnet layer of a connection (RFC 854 / 855 / 1143)."""


class TelnetFilter:
    """The Telnet layer of the connection (RFC 854 / 855 / 1143), kept minimal: the bridge never starts a negotiation, so a plain TCP program
    (cutting software, a script, an ESP32) sees nothing new; a real Telnet client (PuTTY, telnet, nc -t) sends its option requests and the
    bytes of them used to land inside the first line, in front of the first G-code.
      - IAC IAC is the literal byte 255; IAC <command> and IAC SB ... IAC SE are removed from the data;
      - every option is refused: DO x -> IAC WONT x, WILL x -> IAC DONT x (each answer once per option, so two refusing ends never loop);
      - NUL bytes are removed (the NVT sends CR NUL for a bare Enter) and CR LF / CR / LF all end a line."""

    IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240

    def __init__(self):
        self.state = "data"      # data | iac | opt | sb | sb_iac
        self.verb = 0
        self.refused = set()

    def feed(self, data):
        """bytes from the socket -> (bytes for the application, bytes to answer on the socket)"""
        out, reply = bytearray(), bytearray()
        for b in data:
            st = self.state
            if st == "data":
                if b == self.IAC:
                    self.state = "iac"
                elif b != 0:
                    out.append(b)
            elif st == "iac":
                if b == self.IAC:
                    out.append(b)
                    self.state = "data"
                elif b in (self.WILL, self.WONT, self.DO, self.DONT):
                    self.verb = b
                    self.state = "opt"
                elif b == self.SB:
                    self.state = "sb"
                else:
                    self.state = "data"   # NOP, AYT, IP, BRK, GA...: nothing to do
            elif st == "opt":
                key = (self.verb, b)
                if self.verb in (self.WILL, self.DO) and key not in self.refused:
                    self.refused.add(key)
                    reply += bytes((self.IAC, self.DONT if self.verb == self.WILL else self.WONT, b))
                self.state = "data"
            elif st == "sb":
                if b == self.IAC:
                    self.state = "sb_iac"
            else:   # sb_iac
                self.state = "data" if b == self.SE else ("sb" if b == self.IAC else "sb")
        return bytes(out), bytes(reply)
