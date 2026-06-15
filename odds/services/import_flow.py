from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re


ODDS_PATTERN = re.compile(r"(?<![\d.])(?:[1-9]\d*)(?:\.\d{1,3})?(?![\d.])")
SPLIT_PATTERN = re.compile(r"\s*(?:\t|\||,|;)\s*")
APP_LABEL_PATTERN = re.compile(
    r"(?:\bapp\b|ty\s*le\s*app|t[ỷy]\s*l[eệ]\s*app)\D*(?P<odds>[1-9]\d*(?:[\.,]\d{1,3})?)",
    re.IGNORECASE,
)
OUTSIDE_LABEL_PATTERN = re.compile(
    r"(?:ngoai|ngo[aà]i|outside|ty\s*le\s*ngoai|t[ỷy]\s*l[eệ]\s*ngo[aà]i)\D*(?P<odds>[1-9]\d*(?:[\.,]\d{1,3})?)",
    re.IGNORECASE,
)


@dataclass
class PreviewLine:
    row_number: int
    match_name: str
    market_type: str
    selection: str
    handicap: str = ""
    app_odds: Decimal | None = None
    outside_odds: Decimal | None = None
    status: str = "missing_outside_odds"
    warning: str = ""
    error: str = ""
    raw_text: str = ""
    needs_confirmation: bool = False
    confidence: str = "normal"


@dataclass
class ImportPreview:
    raw_app_text: str
    lines: list[PreviewLine] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ready_count(self):
        return sum(1 for line in self.lines if line.status == "ready")

    @property
    def can_save(self):
        return bool(self.lines) and all(line.status == "ready" for line in self.lines)


def parse_decimal(value):
    if value in (None, ""):
        return None
    normalized = str(value).strip().replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def format_decimal(value):
    if value is None:
        return ""
    return f"{value.normalize():f}"


def refresh_preview_status(line: PreviewLine):
    line.error = ""
    line.warning = ""
    if line.needs_confirmation:
        line.status = "needs_confirmation"
        line.error = "Dong paste chua ro mapping, can xac nhan truoc khi luu."
    elif line.app_odds is None or line.app_odds <= Decimal("1"):
        line.status = "invalid"
        line.error = "Ty le app phai lon hon 1."
    elif line.outside_odds is None:
        line.status = "missing_outside_odds"
    elif line.outside_odds <= Decimal("1"):
        line.status = "invalid"
        line.error = "Ty le ngoai phai lon hon 1."
    else:
        line.status = "ready"
        if line.outside_odds >= line.app_odds:
            line.warning = "Canh bao: ty le ngoai lon hon hoac bang ty le app."
    return line


def _extract_app_odds(parts):
    for index in range(len(parts) - 1, -1, -1):
        candidate = parse_decimal(parts[index])
        if candidate is not None and candidate > Decimal("1"):
            return candidate, index
    return None, None


def _extract_labeled_odds(raw_line):
    app_match = APP_LABEL_PATTERN.search(raw_line)
    outside_match = OUTSIDE_LABEL_PATTERN.search(raw_line)
    app_odds = parse_decimal(app_match.group("odds")) if app_match else None
    outside_odds = parse_decimal(outside_match.group("odds")) if outside_match else None
    return app_odds, outside_odds


def _is_labeled_odds_part(part):
    return APP_LABEL_PATTERN.search(part) or OUTSIDE_LABEL_PATTERN.search(part)


def parse_app_odds_text(raw_app_text):
    preview = ImportPreview(raw_app_text=raw_app_text or "")
    source_lines = [line.strip() for line in preview.raw_app_text.splitlines() if line.strip()]
    if not source_lines:
        preview.errors.append("Chua co du lieu ty le app de parse.")
        return preview

    for row_number, raw_line in enumerate(source_lines, start=1):
        parts = [part.strip() for part in SPLIT_PATTERN.split(raw_line) if part.strip()]
        labeled_app_odds, labeled_outside_odds = _extract_labeled_odds(raw_line)
        if len(parts) >= 4:
            app_odds, odds_index = (
                (labeled_app_odds, None)
                if labeled_app_odds is not None
                else _extract_app_odds(parts)
            )
            match_name = parts[0]
            market_type = parts[1]
            selection = parts[2]
            handicap_parts = [
                part
                for idx, part in enumerate(parts[3:])
                if idx + 3 != odds_index and not _is_labeled_odds_part(part)
            ]
            line = PreviewLine(
                row_number=row_number,
                match_name=match_name,
                market_type=market_type,
                selection=selection,
                handicap=" ".join(handicap_parts),
                app_odds=app_odds,
                outside_odds=labeled_outside_odds,
                raw_text=raw_line,
            )
        else:
            odds_matches = list(ODDS_PATTERN.finditer(raw_line))
            app_odds = parse_decimal(odds_matches[-1].group(0)) if odds_matches else None
            text_without_odds = (
                raw_line[: odds_matches[-1].start()] + raw_line[odds_matches[-1].end() :]
                if odds_matches
                else raw_line
            )
            tokens = [token for token in re.split(r"\s{2,}| - | / ", text_without_odds) if token.strip()]
            line = PreviewLine(
                row_number=row_number,
                match_name=tokens[0].strip() if tokens else raw_line,
                market_type=tokens[1].strip() if len(tokens) > 1 else "Can xac nhan",
                selection=tokens[2].strip() if len(tokens) > 2 else "Can xac nhan",
                app_odds=app_odds,
                raw_text=raw_line,
                needs_confirmation=len(tokens) < 3,
                confidence="low",
            )
        preview.lines.append(refresh_preview_status(line))

    return preview


def parse_outside_odds_text(raw_outside_text):
    values = []
    for token in re.split(r"[\s,;|]+", raw_outside_text or ""):
        if not token.strip():
            continue
        values.append(parse_decimal(token))
    return values


def merge_outside_odds(preview: ImportPreview, raw_outside_text):
    values = parse_outside_odds_text(raw_outside_text)
    if not values:
        preview.errors.append("Chua co danh sach ty le ngoai de ghep.")
        return preview
    if len(values) != len(preview.lines):
        preview.errors.append(
            f"So ty le ngoai ({len(values)}) khong khop so dong preview ({len(preview.lines)})."
        )
        return preview
    for line, outside_odds in zip(preview.lines, values, strict=True):
        line.outside_odds = outside_odds
        refresh_preview_status(line)
    return preview
