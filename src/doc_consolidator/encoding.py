"""Decoding bytes, where the careful-looking option destroys the evidence.

The spec's worst input includes "broken encoding". The instinct is `errors="replace"`, which
looks like the safe, defensive choice. It is the one option from which there is no recovery.

    b"caf\\xe9".decode("utf-8", errors="replace")  ->  "caf\\ufffd"

The byte 0xE9 is gone. Not misread -- gone. Nothing downstream can tell whether it was
e-acute, a truncated multi-byte sequence, or binary noise.

Whereas being WRONG keeps everything:

    "café".encode("utf-8").decode("cp1252")  ->  "cafÃ©"       (no exception raised)
    "cafÃ©".encode("cp1252").decode("utf-8")  ->  "café"       (recovered exactly)

Mojibake is an injective map on the bytes it accepts, so it is invertible. Replacement is
not. **The lossy handler is the "safe" one, and the wrong one is recoverable.**

This is the same shape as InitiativeHub's ambiguous dates -- a value that fails loudly is
safer than one that succeeds quietly -- and it is worth saying that plainly rather than
presenting it as new. What is different here is that the number of competing readings is
COUNTABLE (see `candidate_decodings`) and the damage is REVERSIBLE, which is a stronger
position than that project could reach.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

# Legacy single-byte codecs that accept almost any byte sequence. The list is short and
# deliberate: each is a plausible historical default for documents in a Western enterprise,
# and every one of them will decode arbitrary bytes without complaint.
LEGACY_CODECS = ("cp1252", "latin-1", "cp1251", "mac-roman")

REPLACEMENT = "\ufffd"

# Characters that appear when UTF-8 bytes are decoded as a single-byte codec. These are the
# lead bytes of multi-byte UTF-8 sequences reinterpreted as Latin-1/cp1252 text.
MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "Ã¢", "Ð", "Ñ", "å", "æ")


class Decoding(StrEnum):
    """How much we trust the characters we produced."""

    CLEAN = "clean"
    """Valid UTF-8, and no sign of a previous mis-decode."""

    MOJIBAKE = "mojibake"
    """Valid UTF-8 whose content looks like text that was already mis-decoded once. The
    bytes are intact and the damage is REVERSIBLE."""

    AMBIGUOUS = "ambiguous"
    """Not valid UTF-8. Several legacy codecs accept it and disagree about the result, and
    nothing in the bytes says which was meant."""

    LOSSY = "lossy"
    """No codec accepted it. Characters were replaced and the original bytes are gone."""


class DecodeResult(BaseModel):
    """Text, plus what had to be assumed to get it."""

    model_config = ConfigDict(frozen=True)

    text: str
    decoding: Decoding
    codec_used: str
    candidates: int = 1
    """Distinct strings the competing codecs produced. >1 means the choice was a guess."""

    replacements: int = 0
    recoverable: bool = True
    """False only for LOSSY. This is the field that matters: it says whether a downstream
    reader has any route back to the author's intent."""

    detail: str = ""

    @property
    def is_certain(self) -> bool:
        return self.decoding is Decoding.CLEAN


def candidate_decodings(
    raw: bytes, codecs: tuple[str, ...] = LEGACY_CODECS
) -> dict[str, str]:
    """Every codec that accepts these bytes, and what each produces.

    The point of returning them all is that the count is the measurement. When four codecs
    accept the same bytes and produce three different strings, "we decoded the file" is not
    a statement about the file.
    """
    out: dict[str, str] = {}
    for codec in codecs:
        try:
            out[codec] = raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return out


def no_undecodable_bytes() -> tuple[int, int]:
    """(single byte values latin-1 rejects, total). Returns (0, 256).

    Derived rather than asserted, because the consequence is the sharpest thing in this
    module: ISO-8859-1 is a total map from all 256 byte values to code points, so **no byte
    sequence is undecodable**. `Decoding.LOSSY` is therefore unreachable through
    `decode_bytes` with the default codec list.

    Which means every `errors="replace"` in a codebase is a CHOICE to discard information
    that could have been kept, not a necessity forced by bad input. The portfolio contains
    one: CertValidator's `read_text_file` reads with `errors="replace"`.
    """
    rejected = 0
    for value in range(256):
        try:
            bytes([value]).decode("latin-1")
        except UnicodeDecodeError:
            rejected += 1
    return rejected, 256


def _roundtrips(text: str) -> str | None:
    """The text one mis-decoding earlier, or None if it was not mis-decoded."""
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return None
    try:
        recovered = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return None if recovered == text else recovered


def mojibake_lines(text: str) -> list[int]:
    """Indices of lines that are individually mojibake.

    Scanned per line because the whole-text round trip requires EVERY character to be
    mojibake, and one correctly-encoded character defeats it. Verified on the corpus: a
    document whose heading is mojibake and whose next line contains a correct 'é' fails the
    whole-text test at that byte, because re-encoding U+00E9 as cp1252 gives 0xE9 and 0xE9
    is not a valid UTF-8 lead byte.

    A partially mis-decoded document -- someone repaired one field and not the rest -- is
    the common real case, and the whole-text test reports it as clean.
    """
    return [
        i for i, line in enumerate(text.splitlines()) if _roundtrips(line) is not None
    ]


def looks_like_mojibake(text: str) -> tuple[bool, str]:
    """Whether any part of this text was already decoded once as a single-byte codec.

    The test is the round trip, not the marker list: re-encode as cp1252 and decode as
    UTF-8. If that succeeds AND changes the text, the original bytes were UTF-8 all along.
    A marker check alone would fire on legitimate text containing 'Ã'.

    Applied to the whole text first, then per line, so a partial case is still caught.
    """
    whole = _roundtrips(text)
    if whole is not None:
        return True, f"all of it; recoverable to {whole[:40]!r}"

    affected = mojibake_lines(text)
    if not affected:
        return False, ""

    total = len(text.splitlines())
    sample = _roundtrips(text.splitlines()[affected[0]]) or ""
    return True, (
        f"{len(affected)} of {total} lines; the whole-text round trip FAILS because the "
        f"rest is correctly encoded, so a single check would call this clean. Line "
        f"{affected[0]} recovers to {sample[:40]!r}"
    )


def repair_mojibake(text: str) -> str | None:
    """Undo one round of mis-decoding, or None if nothing here is mojibake.

    Applied ONCE, and line by line so a partially affected document is partially repaired.
    Repeated application can keep "succeeding" on text that was never mojibake, so the
    inverse is not iterated to a fixed point.
    """
    whole = _roundtrips(text)
    if whole is not None:
        return whole
    affected = set(mojibake_lines(text))
    if not affected:
        return None
    return "\n".join(
        (_roundtrips(line) or line) if i in affected else line
        for i, line in enumerate(text.splitlines())
    )


def decode_bytes(
    raw: bytes, codecs: tuple[str, ...] = LEGACY_CODECS
) -> DecodeResult:
    """Decode, and say what had to be assumed.

    `errors="replace"` is used only as the LAST resort, and when it is used the result says
    so and sets `recoverable=False`. That flag is the whole reason this function exists
    instead of a call to `.decode()`.

    With the default `codecs` that last resort is UNREACHABLE -- latin-1 accepts every byte
    sequence, so `candidate_decodings` is never empty. See `no_undecodable_bytes`. The
    parameter exists so a caller restricting the list can still reach the branch, and so a
    test can demonstrate what it costs rather than leaving it as dead code.
    """
    if not raw:
        return DecodeResult(text="", decoding=Decoding.CLEAN, codec_used="utf-8")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        candidates = candidate_decodings(raw, codecs)
        if not candidates:
            text = raw.decode("utf-8", errors="replace")
            return DecodeResult(
                text=text,
                decoding=Decoding.LOSSY,
                codec_used="utf-8/replace",
                candidates=0,
                replacements=text.count(REPLACEMENT),
                recoverable=False,
                detail=(
                    f"no codec accepted these bytes ({exc.reason}); "
                    f"{text.count(REPLACEMENT)} characters were replaced and the original "
                    "bytes are unrecoverable"
                ),
            )
        distinct = len(set(candidates.values()))
        # cp1252 first if it accepted, since it is the most common historical default for
        # documents of this kind. Stated as a preference, not as a detection.
        codec = "cp1252" if "cp1252" in candidates else sorted(candidates)[0]
        return DecodeResult(
            text=candidates[codec],
            decoding=Decoding.AMBIGUOUS,
            codec_used=codec,
            candidates=distinct,
            recoverable=True,
            detail=(
                f"not valid UTF-8 ({exc.reason}); {len(candidates)} legacy codecs accepted "
                f"it producing {distinct} distinct strings, and {codec} was PREFERRED "
                "rather than detected"
            ),
        )

    is_mojibake, note = looks_like_mojibake(text)
    if is_mojibake:
        return DecodeResult(
            text=text,
            decoding=Decoding.MOJIBAKE,
            codec_used="utf-8",
            recoverable=True,
            detail=f"valid UTF-8, but the content was already mis-decoded once; {note}",
        )

    return DecodeResult(text=text, decoding=Decoding.CLEAN, codec_used="utf-8", detail=note)


def compare_handlers(raw: bytes) -> dict[str, tuple[str, bool]]:
    """The three ways to handle undecodable bytes, and which keeps the information.

    Returns {handler: (text, recoverable)}. Exists so the asymmetry can be printed rather
    than described: the handler that never raises is the one that cannot be undone.
    """
    out: dict[str, tuple[str, bool]] = {}

    replaced = raw.decode("utf-8", errors="replace")
    out["utf-8 + replace"] = (replaced, raw == replaced.encode("utf-8"))

    ignored = raw.decode("utf-8", errors="ignore")
    out["utf-8 + ignore"] = (ignored, raw == ignored.encode("utf-8"))

    try:
        wrong = raw.decode("cp1252")
        out["cp1252 (wrong)"] = (wrong, raw == wrong.encode("cp1252"))
    except UnicodeDecodeError:
        out["cp1252 (wrong)"] = ("<raised>", True)

    return out
