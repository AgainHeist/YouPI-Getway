"""HTTP Range file responses (needed for video seeking on Android Chrome)."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

CHUNK = 1024 * 256
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def range_response(request: Request, path: Path, *, filename: str | None = None, inline: bool = True) -> StreamingResponse:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")
    size = path.stat().st_size
    media_type = mimetypes.guess_type(filename or path.name)[0] or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{filename or path.name}"',
        "Cache-Control": "private, max-age=0, no-store",
    }
    range_header = request.headers.get("range") or request.headers.get("Range")
    start, end = 0, size - 1
    status = 200
    if range_header:
        match = _RANGE_RE.search(range_header)
        if match:
            raw_start, raw_end = match.group(1), match.group(2)
            if raw_start:
                start = int(raw_start)
                end = int(raw_end) if raw_end else size - 1
            elif raw_end:  # suffix range: bytes=-N
                start = max(0, size - int(raw_end))
            end = min(end, size - 1)
            if start > end or start >= size:
                raise HTTPException(
                    status_code=416,
                    detail="Requested range not satisfiable",
                    headers={"Content-Range": f"bytes */{size}"},
                )
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1
    headers["Content-Length"] = str(length)

    def iterator():
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                data = fh.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(iterator(), status_code=status, media_type=media_type, headers=headers)
