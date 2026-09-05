"""Sensitive patterns, and the bound on how far back a stream has to be held.

Every pattern is written with bounded quantifiers so the longest possible match has a
known length. That number, :data:`MAX_MATCH_LENGTH`, is the only thing the streaming
redactor is allowed to hold back, which is what keeps memory flat as a response grows.
"""

from __future__ import annotations

import re
from typing import Final

# The unquoted local part characters RFC 5322 allows, which is a good deal wider than the
# alphanumeric set most matchers use. Missing one of them does not mean missing the whole
# address, it means redacting part of it and leaving the rest in the clear, which reads as a
# working guardrail while it leaks. A quoted local part such as "john doe"@example.com is out
# of scope, because it may contain spaces and the hold window deliberately stops at prose
# whitespace. Backslash and the quote itself are left out for the same reason.
#: Non-ASCII letters, so an internationalised address written out in full rather than in
#: punycode is caught too. An LLM writes bücher.de, not xn--bcher-kva.de.
_IDN_RANGE: Final = r"\u00a1-\uffff"
_EMAIL_LOCAL_CHARS: Final = rf"A-Za-z0-9!#$%&'*+/=?^_`{{|}}~.\-{_IDN_RANGE}"

# Email. Bounded so the worst case match length is computable rather than open ended, and
# bounded at the RFC 5321 limits rather than at convenient smaller numbers, because a tighter
# cap silently misses a legal address instead of over redacting it. The local part maximum is
# 64 octets and a domain label maximum is 63. An address outside those limits is not a legal
# address and is not matched, which is the one boundary this guardrail has and is tested for.
_EMAIL_LOCAL_MAX: Final = 64
_EMAIL_DOMAIN_MAX: Final = 255
_EMAIL_LABEL_MAX: Final = 63
_EMAIL_LABEL_COUNT: Final = 127  # the DNS label ceiling; the 255 char lookahead is the real bound
_EMAIL_TLD_MAX: Final = 24
#: An internationalised domain reaches DNS as an "xn--" label, which carries digits and
#: hyphens that a letters only top level domain class would miss, and a missed address is a
#: leak. The label cap keeps the match length bounded either way.
_EMAIL_TLD: Final = rf"(?:[A-Za-z\u00a1-\uffff]{{2,{_EMAIL_TLD_MAX}}}|xn--[A-Za-z0-9\-]{{2,{_EMAIL_LABEL_MAX - 4}}})"
EMAIL_PATTERN: Final = (
    rf"(?<![{_EMAIL_LOCAL_CHARS}])[{_EMAIL_LOCAL_CHARS}]{{1,{_EMAIL_LOCAL_MAX}}}"
    # The lookahead caps the whole domain at 255 characters, so however many labels the
    # alternation below is allowed to take, the match length stays bounded by the RFC limit.
    rf"@(?=[A-Za-z0-9.\-{_IDN_RANGE}]{{1,{_EMAIL_DOMAIN_MAX}}}(?![A-Za-z0-9.\-{_IDN_RANGE}]))"
    rf"(?:[A-Za-z0-9\-{_IDN_RANGE}]{{1,{_EMAIL_LABEL_MAX}}}\.){{1,{_EMAIL_LABEL_COUNT}}}"
    rf"{_EMAIL_TLD}(?![A-Za-z0-9\-{_IDN_RANGE}])"
)
_EMAIL_MAX_LENGTH: Final = _EMAIL_LOCAL_MAX + 1 + _EMAIL_DOMAIN_MAX

# US social security number, dashed, spaced, or bare. The negative lookaheads drop the
# ranges the Social Security Administration never issues, which cuts false positives.
SSN_PATTERN: Final = r"\b(?!000|666|9\d\d)\d{3}(?P<ssn_sep>[- ]?)(?!00)\d{2}(?P=ssn_sep)(?!0000)\d{4}\b"
_SSN_MAX_LENGTH: Final = 11

# Credit card: 13 to 19 digits, optionally grouped by a single space or dash. A candidate
# is only redacted once it passes the Luhn checksum, see :func:`luhn_ok`.
_CARD_MIN_DIGITS: Final = 13
_CARD_MAX_DIGITS: Final = 19
CARD_PATTERN: Final = rf"\b(?:\d[ \-]?){{{_CARD_MIN_DIGITS - 1},{_CARD_MAX_DIGITS - 1}}}\d\b"
_CARD_MAX_LENGTH: Final = _CARD_MAX_DIGITS * 2 - 1

#: The longest a single match can be. The redactor never holds back more than this.
MAX_MATCH_LENGTH: Final = max(_EMAIL_MAX_LENGTH, _SSN_MAX_LENGTH, _CARD_MAX_LENGTH)

#: What every match is replaced with.
REDACTED: Final = "[REDACTED]"

#: One pass over the text. Email first so an address containing digits is not split.
PATTERN: Final = re.compile(rf"(?P<email>{EMAIL_PATTERN})|(?P<card>{CARD_PATTERN})|(?P<ssn>{SSN_PATTERN})")

#: ASCII characters that can appear inside a match. Used to avoid cutting a stream mid token,
#: so it has to be the union of every pattern's character set, the wide local part included.
CONSTITUENT: Final = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" + "!#$%&'*+/=?^_`{|}~.-@"
)

#: Anything from this code point up is treated as part of a token as well, matching the
#: internationalised ranges the email pattern accepts.
IDN_FIRST_CODEPOINT: Final = 0xA1


def is_constituent(char: str) -> bool:
    """True when a character could sit inside a match, so a cut must not land next to it."""
    return char in CONSTITUENT or ord(char) >= IDN_FIRST_CODEPOINT


def luhn_ok(digits: str) -> bool:
    """Return True when the digit string satisfies the Luhn checksum."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def replacement_for(match: re.Match[str]) -> str:
    """What a matched candidate becomes. Returning the original text means leave it alone.

    Emails and SSNs are taken at face value. A card number has a checksum, so it is used and
    a 16 digit invoice number that fails Luhn is left alone rather than mangled.
    """
    if match.group("card") is None:
        return REDACTED
    return _redact_card_run(match.group(0))


def _redact_card_run(text: str) -> str:
    """Redact the card number inside a run of digits, which may hold more than the card.

    A run like ``4111 1111 1111 1111 123`` is a card followed by a security code, and the run
    as a whole fails Luhn, so checking only the whole run would let the card through intact.
    Cards are written in groups, so the candidates are the runs of whole groups, longest
    first, which finds the card in ``4111 1111 1111 1111 123`` and in ``123 4111 1111 1111
    1111`` alike.

    Sliding an arbitrary window instead would be worse, not better. Luhn accepts about one in
    ten random digit strings, so measured on three ordinary sixteen digit numbers, adding
    even the prefix and suffix windows partly redacted two of them. The checksum would stop
    meaning anything and the guardrail would start corrupting invoice and order numbers.

    Two residuals, named here rather than left to be discovered. A card written with no
    separator at all and a security code stuck straight onto it is one group, fails Luhn, and
    is left alone. A digit run longer than nineteen has no boundary a match can end on, so the
    pattern does not match it at all. Both are pinned by tests.
    """
    digits = [(index, char) for index, char in enumerate(text) if char.isdigit()]
    group_starts = [0] + [k for k in range(1, len(digits)) if digits[k][0] != digits[k - 1][0] + 1]
    group_bounds = [*group_starts, len(digits)]

    windows = [
        (group_bounds[first], group_bounds[last] - group_bounds[first])
        for first in range(len(group_starts))
        for last in range(first + 1, len(group_bounds))
    ]
    for start, length in sorted(windows, key=lambda window: (-window[1], window[0])):
        if not _CARD_MIN_DIGITS <= length <= _CARD_MAX_DIGITS:
            continue
        window = digits[start : start + length]
        if luhn_ok("".join(char for _, char in window)):
            return text[: window[0][0]] + REDACTED + text[window[-1][0] + 1 :]
    return text
