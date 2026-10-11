"""Bounded inline raster photos; SVG and arbitrary URLs are not accepted."""
import base64
import binascii


def validate_photo(value: str) -> str:
    try:
        header, encoded = value.split(',', 1)
        signatures = {
            'data:image/png;base64': lambda data: data.startswith(b'\x89PNG\r\n\x1a\n'),
            'data:image/jpeg;base64': lambda data: data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'),
            'data:image/webp;base64': lambda data: data[:4] == b'RIFF' and data[8:12] == b'WEBP',
        }
        if header not in signatures:
            raise ValueError('Use a PNG, JPEG, or WebP photo')
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > 2 * 1024 * 1024:
            raise ValueError('Photo must be no larger than 2 MB')
        if not signatures[header](data):
            raise ValueError('Photo content does not match its image type')
        return header + ',' + base64.b64encode(data).decode('ascii')
    except (binascii.Error, ValueError) as exc:
        raise ValueError(str(exc)) from exc
