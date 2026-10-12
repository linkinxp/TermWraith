IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
ECHO, SUPPRESS_GO_AHEAD, NAWS = 1, 3, 31


class TelnetFilter:
    """Strips telnet negotiation from a byte stream and answers it.

    Accepts ECHO, SUPPRESS-GO-AHEAD and window size (NAWS); every other option is refused.
    """

    def __init__(self, size=None) -> None:
        self._pending = b""
        self._size = size
        self.naws = False

    def window_packet(self, cols: int, rows: int) -> bytes:
        payload = (cols.to_bytes(2, "big") + rows.to_bytes(2, "big")).replace(b"\xff", b"\xff\xff")
        return bytes([IAC, SB, NAWS]) + payload + bytes([IAC, SE])

    def feed(self, data: bytes) -> tuple[bytes, bytes]:
        data = self._pending + data
        self._pending = b""
        text = bytearray()
        replies = bytearray()
        i = 0
        while i < len(data):
            if data[i] != IAC:
                text.append(data[i])
                i += 1
                continue
            if i + 1 >= len(data):
                self._pending = data[i:]
                break
            cmd = data[i + 1]
            if cmd == IAC:
                text.append(IAC)
                i += 2
            elif cmd in (WILL, WONT, DO, DONT):
                if i + 2 >= len(data):
                    self._pending = data[i:]
                    break
                opt = data[i + 2]
                if cmd == WILL:
                    replies += bytes([IAC, DO if opt in (ECHO, SUPPRESS_GO_AHEAD) else DONT, opt])
                elif cmd == DO and opt == NAWS:
                    self.naws = True
                    replies += bytes([IAC, WILL, NAWS])
                    if self._size is not None:
                        replies += self.window_packet(*self._size())
                elif cmd == DO:
                    replies += bytes([IAC, WILL if opt == SUPPRESS_GO_AHEAD else WONT, opt])
                i += 3
            elif cmd == SB:
                end = data.find(bytes([IAC, SE]), i)
                if end == -1:
                    self._pending = data[i:]
                    break
                i = end + 2
            else:
                i += 2
        return bytes(text), bytes(replies)
