import re
from functools import lru_cache

_IPV4 = r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b"
_IPV6 = r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}|(?:[0-9A-Fa-f]{0,4}:){1,7}:[0-9A-Fa-f:]*"
_MAC = r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"
_IFACE = r"\b(?:eth|ens|enp|eno|wlan|wlp|ppp|tun|tap|br|bond|vlan|lo)\d+(?:\.\d+)?\b"
_PROTO = r"\b(?:TCP|UDP|ICMP|ICMPv6|ARP|DNS|DHCP|HTTPS?|SSH|TLS|BGP|OSPF|NAT|VLAN|MTU|MAC)\b"
_UP = r"\b(?:up|established|listening|connected|reachable|ok|online|active)\b"
_DOWN = r"\b(?:down|refused|unreachable|timed out|timeout|denied|reset|closed|failed|failure|no route|lost|offline|dropped)\b"
_WARN = r"\b(?:warning|retry|retrying|retransmit\w*|congested|slow|flapping)\b"

RULES = [
    (re.compile(_IPV4), "#6CB6FF"),
    (re.compile(_IPV6), "#6CB6FF"),
    (re.compile(_MAC), "#C792EA"),
    (re.compile(_IFACE), "#C792EA"),
    (re.compile(_PROTO), "#56B6C2"),
    (re.compile(_UP, re.IGNORECASE), "#98C379"),
    (re.compile(_DOWN, re.IGNORECASE), "#E06C75"),
    (re.compile(_WARN, re.IGNORECASE), "#E5C07B"),
]


@lru_cache(maxsize=1024)
def colours_for(line: str) -> tuple[str | None, ...]:
    out: list[str | None] = [None] * len(line)
    for pattern, colour in RULES:
        for match in pattern.finditer(line):
            for i in range(match.start(), match.end()):
                if out[i] is None:
                    out[i] = colour
    return tuple(out)
