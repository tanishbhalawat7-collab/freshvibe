"""Find, label and normalise dates in OCR text from product packaging.

Rules this module follows:
  * every date-like string is reported, with the label it belongs to
    (expiry / mfg / packed / unlabeled) -- unlabeled dates are never
    promoted to expiry dates;
  * the raw OCR text of each match is preserved;
  * dates are validated against the calendar;
  * month-only dates keep month precision (no invented day);
  * ambiguous numeric dates (03/04/2026) are flagged, not silently guessed;
  * "Best before 12 months from manufacture" style shelf-life statements are
    turned into a *derived* expiry only when the base date was actually read.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
MON_RE = r"(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUNE?|JULY?|AUG(?:UST)?|SEPT?(?:EMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"

# --- labels ---------------------------------------------------------------
LABELS: list[tuple[str, str]] = [
    # expiry
    ("expiry", r"DATE\s*OF\s*EXP(?:IRY)?"),
    ("expiry", r"EXP(?:IRY|IRES|IRATION)?\.?\s*(?:DATE|DT\.?)?"),
    ("expiry", r"E\.\s*X\.\s*P\.?"),
    ("expiry", r"BEST\s*BEFORE(?:\s*END)?"),
    ("expiry", r"BEST\s*BY"),
    ("expiry", r"BBE"),
    ("expiry", r"B\.?B\.?(?=\s*[:\-]?\s*\d)"),
    ("expiry", r"USE\s*(?:BY|BEFORE)"),
    ("expiry", r"CONSUME\s*(?:BY|BEFORE)"),
    ("expiry", r"VALID\s*(?:TILL|UNTIL|UPTO|UP\s*TO)"),
    ("expiry", r"SELL\s*BY"),
    # manufacture
    ("mfg", r"DATE\s*OF\s*(?:MFG|MANUFACTURE|MANUFACTURING|MFD)"),
    ("mfg", r"MANUFACTUR(?:ED|ING|E)\s*(?:ON|DATE|DT)?"),
    ("mfg", r"M\.?\s*F\.?\s*[GDC]\.?\s*(?:DATE|DT\.?|ON)?"),
    ("mfg", r"PROD(?:UCTION|UCED)?\.?\s*(?:DATE|DT|ON)"),
    ("mfg", r"DOM"),
    # packed
    ("packed", r"DATE\s*OF\s*PACK(?:ING|AGING|ED)?"),
    ("packed", r"PACK(?:ED|ING|AGED)\s*(?:ON|DATE|DT)?"),
    ("packed", r"PKD\.?\s*(?:ON|DATE)?"),
    ("packed", r"PKG\.?\s*(?:DATE|DT)?"),
]
LABEL_RE = re.compile(
    "|".join(f"(?P<l{i}>(?<![A-Z]){p}(?![A-Z]))" for i, (_, p) in enumerate(LABELS))
)
BATCH_RE = re.compile(
    r"(?<![A-Z])(?:BATCH\s*(?:NO|NUMBER|#)?|B\.\s*NO|B\s*NO|LOT\s*(?:NO|NUMBER|#)?|B\.?N\.)\s*[.:#\-]*\s*"
    r"(?P<val>[A-Z0-9][A-Z0-9/\-]{1,19})"
)
SHELF_RE = re.compile(
    r"(?:BEST\s*BEFORE|USE\s*(?:WITHIN|BEFORE|BY)|CONSUME\s*WITHIN|EXPIRY|EXPIRES|SHELF\s*LIFE|BB)"
    r"[^0-9]{0,20}?(?P<n>\d{1,3})\s*(?P<unit>MONTHS?|MTHS?|MOS?|DAYS?|YEARS?|YRS?)"
    r"(?:\s*(?:FROM|AFTER|OF)\s*(?P<base>MFG|MFD|MANUFACTUR\w*|PACK\w*|PKD|PKG|PRODUCTION|DATE\s*OF\s*\w+))?"
)

CONFUSABLE = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "!": "1",
                            "S": "5", "Z": "2", "B": "8", "G": "6", "T": "7"})


@dataclass
class DateCandidate:
    raw: str
    value: str            # YYYY-MM-DD (day precision) or YYYY-MM (month precision)
    iso: str              # always YYYY-MM-DD (first of month for month precision)
    precision: str        # day | month
    kind: str             # expiry | mfg | packed | unlabeled
    label: str | None
    line: str
    line_index: int
    confidence: float
    ambiguous: bool = False
    derived: bool = False
    notes: list[str] = field(default_factory=list)
    support: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


def _year(y: str) -> int | None:
    if len(y) == 2:
        return 2000 + int(y)
    if len(y) == 4:
        return int(y)
    return None


def _valid(y: int, m: int, d: int | None) -> bool:
    if not (2000 <= y <= 2100 and 1 <= m <= 12):
        return False
    if d is None:
        return True
    return 1 <= d <= calendar.monthrange(y, m)[1]


def _digitize(line: str) -> tuple[str, int]:
    """Fix letter/digit OCR confusions inside numeric-looking tokens only.
    Returns the corrected line (same length) and the number of corrections."""
    fixes = 0
    out = []
    for tok in re.split(r"(\s+|:)", line):
        core = tok.strip(".,:;")
        digits = sum(c.isdigit() for c in core)
        if core and digits >= 2 and digits / len(core) >= 0.5 and re.fullmatch(r"[0-9OQDILSZBGT|!/.\-]+", core):
            # month names must survive (e.g. "DEC" in 12-DEC-2026 is not here: it has no digits)
            new = tok.translate(CONFUSABLE)
            fixes += sum(a != b for a, b in zip(tok, new))
            out.append(new)
        else:
            out.append(tok)
    return "".join(out), fixes


def normalize_line(line: str) -> str:
    s = line.upper()
    s = s.replace("–", "-").replace("—", "-").replace("\\", "/")
    s = re.sub(r"[‘’'`]", "'", s)
    s = re.sub(r"(?<=\d)\s*([/.\-])\s*(?=\d)", r"\1", s)  # "12 / 05 / 2026" -> "12/05/2026"
    return s


# Patterns in priority order. Each returns (y, m, d|None, flags)
_SEP = r"[/.\-]"
PATTERNS = [
    ("ymd", re.compile(rf"(?<!\d)(?P<y>20\d{{2}}){_SEP}(?P<m>\d{{1,2}}){_SEP}(?P<d>\d{{1,2}})(?!\d)")),
    ("ym", re.compile(rf"(?<![\d/.\-])(?P<y>20\d{{2}})[/\-.](?P<m>\d{{1,2}})(?![\d/.\-]*\d)")),
    ("dmy_named", re.compile(rf"(?<!\d)(?P<d>\d{{1,2}})(?:ST|ND|RD|TH)?[\s\-/.]*(?P<mon>{MON_RE})[\s\-/.,']*(?P<y>\d{{4}}|\d{{2}})(?!\d)")),
    ("mdy_named", re.compile(rf"(?<![A-Z])(?P<mon>{MON_RE})[\s\-/.]*(?P<d>\d{{1,2}})(?:ST|ND|RD|TH)?,\s*(?P<y>\d{{4}})(?!\d)")),
    ("my_named", re.compile(rf"(?<![A-Z])(?P<mon>{MON_RE})[\s\-/.,']*(?P<y>20\d{{2}}|\d{{2}})(?!\d)")),
    ("numeric3", re.compile(rf"(?<![\d/.\-])(?P<a>\d{{1,2}})(?P<s1>{_SEP})(?P<b>\d{{1,2}})(?P=s1)(?P<y>\d{{4}}|\d{{2}})(?![\d/.\-]*\d)")),
    ("my_numeric4", re.compile(rf"(?<![\d/.\-])(?P<m>\d{{1,2}})[/\-.](?P<y>20\d{{2}})(?![\d/.\-]*\d)")),
    ("my_numeric2", re.compile(r"(?<![\d/.\-])(?P<m>[01]\d)[/\-](?P<y>\d{2})(?![\d/.\-]*\d)")),
]


def _parse_match(kind: str, m: re.Match, order: str) -> tuple[int, int, int | None, list[str], bool] | None:
    notes: list[str] = []
    amb = False
    g = m.groupdict()
    if kind == "ymd":
        y, mo, d = int(g["y"]), int(g["m"]), int(g["d"])
    elif kind in ("dmy_named", "mdy_named"):
        y = _year(g["y"])
        mo = MONTHS[g["mon"][:4] if g["mon"].startswith("SEPT") else g["mon"][:3]]
        d = int(g["d"])
        if len(g["y"]) == 2:
            notes.append("two-digit year")
    elif kind == "my_named":
        y = _year(g["y"])
        mo = MONTHS[g["mon"][:4] if g["mon"].startswith("SEPT") else g["mon"][:3]]
        d = None
        if len(g["y"]) == 2:
            notes.append("two-digit year")
    elif kind == "numeric3":
        a, b, y = int(g["a"]), int(g["b"]), _year(g["y"])
        if len(g["y"]) == 2:
            notes.append("two-digit year")
        first = (a, b) if order == "DMY" else (b, a)  # (day, month)
        second = (b, a) if order == "DMY" else (a, b)
        if y and _valid(y, first[1], first[0]):
            d, mo = first
            if a != b and a <= 12 and b <= 12:
                amb = True
                notes.append(f"ambiguous day/month - read as {order}")
        elif y and _valid(y, second[1], second[0]):
            d, mo = second
            notes.append(f"only valid as {'MDY' if order == 'DMY' else 'DMY'}")
        else:
            return None
    elif kind == "ym":
        y, mo, d = int(g["y"]), int(g["m"]), None
    elif kind in ("my_numeric4", "my_numeric2"):
        y, mo, d = _year(g["y"]), int(g["m"]), None
        if kind == "my_numeric2":
            notes.append("MM/YY format")
    else:
        return None
    if y is None or not _valid(y, mo, d):
        return None
    return y, mo, d, notes, amb


def _find_labels(line: str) -> list[tuple[int, int, str, str]]:
    out = []
    for m in LABEL_RE.finditer(line):
        for name, val in m.groupdict().items():
            if val:
                kind = LABELS[int(name[1:])][0]
                out.append((m.start(), m.end(), kind, val.strip()))
                break
    return out


def _line_dates(norm: str, order: str, rejected: list | None = None):
    taken: list[tuple[int, int]] = []
    found = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(norm):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            parsed = _parse_match(kind, m, order)
            if not parsed:
                if rejected is not None and kind in ("ymd", "numeric3", "dmy_named"):
                    rejected.append(m.group(0))
                continue
            taken.append((s, e))
            found.append((s, e, kind, parsed, m.group(0)))
    found.sort(key=lambda x: x[0])
    return found


def extract(lines: list[tuple[str, float]], date_order: str = "DMY", today: date | None = None) -> dict:
    """lines: list of (text, confidence 0..1) in reading order."""
    today = today or date.today()
    cands: list[DateCandidate] = []
    batches: list[dict] = []
    shelf: list[dict] = []
    pending_label: tuple[str, str] | None = None  # label alone on the previous line
    rejected: list[str] = []

    for idx, (raw_line, conf) in enumerate(lines):
        if not raw_line.strip():
            continue
        up = normalize_line(raw_line)
        norm, fixes = _digitize(up)
        norm = normalize_line(norm)
        labels = _find_labels(up)
        dates = _line_dates(norm, date_order, rejected)

        for bm in BATCH_RE.finditer(up):
            val = bm.group("val").strip("-/")
            if len(val) >= 2 and re.search(r"\d", val) and not re.fullmatch(MON_RE, val):
                batches.append({"value": val, "raw": bm.group(0).strip(), "line": raw_line.strip(),
                                "confidence": round(min(conf, 0.99), 2)})
        nxt = normalize_line(lines[idx + 1][0]) if idx + 1 < len(lines) else ""
        for sm in SHELF_RE.finditer(up + " " + nxt):
            if sm.start() >= len(up):
                continue
            unit = sm.group("unit")
            shelf.append({
                "n": int(sm.group("n")),
                "unit": "month" if unit.startswith("M") else "day" if unit.startswith("D") else "year",
                "base": ("packed" if sm.group("base") and sm.group("base").startswith(("PACK", "PKD", "PKG"))
                         else "mfg"),
                "raw": sm.group(0), "line": raw_line.strip(), "confidence": conf,
            })

        if not dates:
            # remember a lone label ("EXP:") so the next line's date can use it
            if labels and labels[-1][1] >= len(up.rstrip(" :.-")) - 1:
                pending_label = (labels[-1][2], labels[-1][3])
            else:
                pending_label = None if not labels else pending_label
            continue

        # pairing: "MFG/EXP: 01/25 12/26" -> labels all before the first date, same count
        paired: dict[int, tuple[str, str]] = {}
        before_first = [l for l in labels if l[1] <= dates[0][0] + 1]
        if len(dates) > 1 and len(before_first) == len(dates) and len(labels) == len(before_first):
            for (ds, *_), lab in zip(dates, before_first):
                paired[ds] = (lab[2], lab[3])

        prev_end = 0
        if conf < 0.4:
            dates = []  # very low-confidence OCR line: too unreliable to report
        for ds, de, pkind, (y, mo, d, notes, amb), rawtxt in dates:
            label = paired.get(ds)
            if label is None:
                # nearest label that ends between the previous date and this one
                near = [l for l in labels if prev_end <= l[1] <= ds + 1]
                if near:
                    label = (near[-1][2], near[-1][3])
                elif ds == dates[0][0] and pending_label:
                    label = pending_label
                    notes = notes + ["label on previous line"]
            prev_end = de
            kind = label[0] if label else "unlabeled"
            precision = "day" if d is not None else "month"
            value = f"{y:04d}-{mo:02d}-{d:02d}" if d else f"{y:04d}-{mo:02d}"
            iso = f"{y:04d}-{mo:02d}-{(d or 1):02d}"

            c = max(0.05, min(conf, 0.99))
            if label:
                c = min(0.99, c + 0.05)
            if amb:
                c -= 0.12
            if "two-digit year" in notes:
                c -= 0.03
            if "MM/YY format" in notes:
                c -= 0.08
            local_fixes = sum(a != b for a, b in zip(up[ds:de], norm[ds:de]))
            if local_fixes:
                c -= 0.06 * local_fixes
                notes = notes + [f"{local_fixes} OCR character correction(s)"]
            # plausibility
            dt = date(y, mo, d or 1)
            if kind in ("mfg", "packed") and dt > today + timedelta(days=31):
                notes.append("manufacture date is in the future - check")
                c -= 0.3
            if kind == "expiry" and dt.year > today.year + 15:
                notes.append("expiry more than 15 years away - check")
                c -= 0.3
            cands.append(DateCandidate(
                raw=raw_line[ds:de].strip() if len(raw_line) == len(up) else rawtxt,
                value=value, iso=iso, precision=precision, kind=kind,
                label=label[1] if label else None, line=raw_line.strip(), line_index=idx,
                confidence=round(max(0.0, c), 3), ambiguous=amb, notes=notes,
            ))
        pending_label = None

    out = _resolve(cands, batches, shelf)
    out["rejected"] = sorted(set(rejected))
    if rejected:
        out["issues"].append(
            f"Unreadable/invalid date(s): {', '.join(sorted(set(rejected)))}. Capture another, sharper image."
        )
    return out


def merge_passes(results: list[dict]) -> dict:
    """Combine the extraction results of several OCR passes. A date read the
    same way by multiple passes gets a confidence boost."""
    by_key: dict[tuple, DateCandidate] = {}
    batches, shelf = [], []
    for r in results:
        for c in r["all_dates"]:
            cand = DateCandidate(**c)
            key = (cand.value, cand.kind)
            if key in by_key:
                cur = by_key[key]
                cur.support += 1
                cur.confidence = round(min(0.99, max(cur.confidence, cand.confidence) + 0.05), 3)
            else:
                by_key[key] = cand
        batches += r["batch_candidates"]
        shelf += r["shelf_life"]
    # a date seen labelled in one pass and unlabeled in another: keep the labelled one
    labelled_vals = {v for (v, k) in by_key if k != "unlabeled"}
    cands = [c for (v, k), c in by_key.items() if not (k == "unlabeled" and v in labelled_vals)]
    cands = [c for c in cands if not c.derived]
    out = _resolve(cands, batches, shelf, already_merged=True)
    rej = sorted({x for r in results for x in r.get("rejected", [])})
    # only complain about invalid strings if no pass produced a usable expiry
    if rej and not out["expiry"]:
        out["issues"].append(f"Unreadable/invalid date(s): {', '.join(rej)}. Capture another, sharper image.")
    out["rejected"] = rej
    return out


def _add_months(y: int, m: int, n: int) -> tuple[int, int]:
    t = y * 12 + (m - 1) + n
    return t // 12, t % 12 + 1


def _resolve(cands: list[DateCandidate], batches: list[dict], shelf: list[dict],
             already_merged: bool = False) -> dict:
    cands.sort(key=lambda c: (c.line_index, c.raw))
    issues: list[str] = []

    def pick(kind: str) -> DateCandidate | None:
        group = [c for c in cands if c.kind == kind and not c.derived]
        if not group:
            return None
        values = {c.value for c in group}
        best = max(group, key=lambda c: (c.confidence, c.support))
        if len(values) > 1:
            issues.append(f"Several different {kind} dates were read: {', '.join(sorted(values))}.")
            best = DateCandidate(**{**best.to_dict(), "confidence": round(best.confidence - 0.3, 3),
                                    "notes": best.notes + ["conflicting readings"]})
        return best

    mfg = pick("mfg")
    packed = pick("packed")
    expiry = pick("expiry")

    # Shelf-life statement -> derived expiry, only from a base date that was actually read
    if shelf and (expiry is None or expiry.confidence < 0.6):
        explicit = expiry
        s = max(shelf, key=lambda x: x["confidence"])
        base = (packed or mfg) if s["base"] == "packed" else (mfg or packed)
        if base:
            y, m = int(base.value[:4]), int(base.value[5:7])
            notes = [f"derived: {s['raw'].strip()} + {base.kind} date {base.value}"]
            if s["unit"] in ("month", "year"):
                ny, nm = _add_months(y, m, s["n"] * (12 if s["unit"] == "year" else 1))
                if base.precision == "day":
                    dd = min(int(base.value[8:10]), calendar.monthrange(ny, nm)[1])
                    dt = date(ny, nm, dd) - timedelta(days=1)
                    value, prec = dt.isoformat(), "day"
                else:
                    # "best before N months" from a month-only date: end of month N-1 later
                    ny, nm = _add_months(ny, nm, -1)
                    value, prec = f"{ny:04d}-{nm:02d}", "month"
            else:
                if base.precision != "day":
                    value = prec = None
                    issues.append("Shelf life is given in days but the base date has no day.")
                else:
                    dt = date.fromisoformat(base.value) + timedelta(days=s["n"])
                    value, prec = dt.isoformat(), "day"
            if value:
                expiry = DateCandidate(
                    raw=s["raw"].strip(), value=value, iso=value if prec == "day" else value + "-01",
                    precision=prec, kind="expiry", label="shelf life", line=s["line"],
                    line_index=base.line_index, confidence=round(min(base.confidence, s["confidence"]) - 0.05, 3),
                    derived=True, notes=notes,
                )
                cands.append(expiry)
                if explicit and explicit.confidence > expiry.confidence:
                    expiry = explicit

    # Cross-checks
    ref = mfg or packed
    if expiry and ref and expiry.iso <= ref.iso:
        issues.append(f"Expiry ({expiry.value}) is not after the {ref.kind} date ({ref.value}).")
        expiry = DateCandidate(**{**expiry.to_dict(), "confidence": round(expiry.confidence - 0.4, 3),
                                  "notes": expiry.notes + ["earlier than manufacture date"]})
    unl = [c for c in cands if c.kind == "unlabeled"]
    if not expiry and unl:
        issues.append(
            f"Found {len(unl)} date(s) without an EXP/MFG label ({', '.join(c.value for c in unl)}). "
            "They are not assumed to be expiry dates - confirm which one is the expiry or capture the label too."
        )

    # batch: de-duplicate, keep highest confidence
    bmap: dict[str, dict] = {}
    for b in batches:
        if b["value"] not in bmap or b["confidence"] > bmap[b["value"]]["confidence"]:
            bmap[b["value"]] = b
    blist = sorted(bmap.values(), key=lambda b: -b["confidence"])

    return {
        "expiry": expiry.to_dict() if expiry else None,
        "mfg": mfg.to_dict() if mfg else None,
        "packed": packed.to_dict() if packed else None,
        "batch": blist[0] if blist else None,
        "all_dates": [c.to_dict() for c in cands],
        "batch_candidates": blist,
        "shelf_life": shelf,
        "issues": issues,
    }


def end_of_period(iso: str, precision: str) -> date:
    d = date.fromisoformat(iso)
    if precision == "month":
        return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    return d
