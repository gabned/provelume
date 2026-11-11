"""Search-only type labels; MIME identities and extraction authority stay separate."""

from __future__ import annotations

_TYPES = {
    "application/pdf": ("pdf", None),
    "text/plain": ("text", None),
    "text/markdown": ("markdown", None),
    "text/x-markdown": ("markdown", None),
    "text/html": ("web", "HTML"),
    "application/json": ("text", "JSON"),
    "application/msword": ("document", "DOC"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "document", "DOCX"),
    "application/vnd.oasis.opendocument.text": ("document", "ODT"),
    "application/rtf": ("document", "RTF"),
    "text/rtf": ("document", "RTF"),
    "text/csv": ("spreadsheet", "CSV"),
    "application/vnd.ms-excel": ("spreadsheet", "XLS"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "spreadsheet", "XLSX"),
    "application/vnd.oasis.opendocument.spreadsheet": ("spreadsheet", "ODS"),
    "application/vnd.ms-powerpoint": ("presentation", "PPT"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "presentation", "PPTX"),
    "application/vnd.oasis.opendocument.presentation": ("presentation", "ODP"),
    "image/jpeg": ("image", "JPEG"),
    "image/png": ("image", "PNG"),
    "image/gif": ("image", "GIF"),
    "image/tiff": ("image", "TIFF"),
    "image/webp": ("image", "WebP"),
    "image/svg+xml": ("image", "SVG"),
    "audio/mpeg": ("audio", "MP3"),
    "audio/wav": ("audio", "WAV"),
    "audio/x-wav": ("audio", "WAV"),
    "audio/flac": ("audio", "FLAC"),
    "audio/ogg": ("audio", "Ogg"),
    "audio/mp4": ("audio", "MP4"),
    "video/mp4": ("video", "MP4"),
    "video/webm": ("video", "WebM"),
    "video/quicktime": ("video", "MOV"),
    "application/zip": ("archive", "ZIP"),
    "application/gzip": ("archive", "gzip"),
    "application/x-7z-compressed": ("archive", "7z"),
    "message/rfc822": ("email", "EML"),
}


def media_type_label(value, translate):
    """Return plain display text, never normalize or replace a MIME value."""
    kind, file_format = _TYPES.get(value, ("other", value))
    label = translate("search.type." + kind)
    return (translate("search.type.format", kind=label, format=file_format)
            if file_format else label)


def type_options(values, selected, translate):
    """Preserve inventory order and a selected type absent from that inventory."""
    options = list(values)
    if selected and selected not in options:
        options.append(selected)
    return [{"value": value, "label": media_type_label(value, translate)}
            for value in options]
