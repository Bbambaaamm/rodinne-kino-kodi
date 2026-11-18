"""Check for menu pixels in a PNG produced by Kodi's screenshot writer."""
import struct
import zlib

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def has_menu_detail(png):
    if len(png) < 33 or not png.startswith(PNG_SIGNATURE) or png[12:16] != b'IHDR':
        return False
    width, height, depth, color, compression, row_filter, interlace = struct.unpack_from('>IIBBBBB', png, 16)
    channels = {2: 3, 6: 4}.get(color)
    if not channels or depth != 8 or compression or row_filter or interlace:
        return False
    if not width or not height or width * height > 16_777_216:
        return False

    image_data = []
    position = 8
    while position + 12 <= len(png):
        size, kind = struct.unpack_from('>I4s', png, position)
        end = position + 12 + size
        if end > len(png):
            return False
        if kind == b'IDAT':
            image_data.append(png[position + 8:end - 4])
        if kind == b'IEND':
            break
        position = end
    else:
        return False

    stride = width * channels + 1
    expected = stride * height
    try:
        decoder = zlib.decompressobj()
        rows = decoder.decompress(b''.join(image_data), expected + 1)
    except zlib.error:
        return False
    if not decoder.eof or len(rows) != expected:
        return False

    # PNG filters predict each channel independently. A black image has zero
    # RGB residuals even when its alpha channel and row filter bytes are set.
    # Ignore isolated changed rows, such as the small redraw control.
    visible_rows = 0
    for start in range(0, expected, stride):
        row = rows[start + 1:start + stride]
        if any(row[channel::channels].strip(b'\0') for channel in range(3)):
            visible_rows += 1
            if visible_rows >= min(height, 12):
                return True
    return False
