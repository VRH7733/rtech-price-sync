"""robots.txt matching per RFC 9309 (supports '*' and '$', longest match wins).

Python's urllib.robotparser does NOT support wildcards, and Moglix's robots.txt relies on
them (e.g. 'Disallow: /*?p='), so we use our own matcher.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit


@dataclass
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern = field(repr=False, default=None)

    def __post_init__(self):
        p = unquote(self.pattern)
        anchored = p.endswith("$")
        if anchored:
            p = p[:-1]
        rx = re.escape(p).replace(r"\*", ".*")
        self.regex = re.compile("^" + rx + ("$" if anchored else ""))


class RobotsRules:
    def __init__(self, text: str, agent_token: str = "rtech-price-sync"):
        self.agent_token = agent_token.lower()
        self.rules: list = []
        self.crawl_delay = None
        self._parse((text or "").lstrip("﻿"))

    def _parse(self, text: str) -> None:
        groups: list = []  # (set(agents), [rules], crawl_delay)
        agents: list = []
        rules: list = []
        delay = None
        in_rules = False

        def close():
            nonlocal agents, rules, delay, in_rules
            if agents:
                groups.append((set(agents), rules, delay))
            agents, rules, delay, in_rules = [], [], None, False

        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if in_rules:
                    close()
                agents.append(value.lower())
            elif key in ("allow", "disallow"):
                in_rules = True
                if value:  # empty Disallow = allow everything
                    rules.append(_Rule(key == "allow", value))
            elif key == "crawl-delay":
                in_rules = True
                try:
                    delay = float(value)
                except ValueError:
                    pass
        close()

        specific = [g for g in groups if self.agent_token in g[0]]
        chosen = specific or [g for g in groups if "*" in g[0]]
        for _, rs, dl in chosen:
            self.rules.extend(rs)
            if dl is not None:
                self.crawl_delay = dl

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        target = unquote((parts.path or "/") + (("?" + parts.query) if parts.query else ""))
        best = None
        for rule in self.rules:
            if rule.regex.match(target):
                key = (len(rule.pattern), rule.allow)  # longest wins; Allow wins ties
                if best is None or key > best[0]:
                    best = (key, rule.allow)
        return True if best is None else best[1]
