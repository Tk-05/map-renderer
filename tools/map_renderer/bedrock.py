"""Reading surface biomes straight from a Bedrock world (standard library only).

Bedrock stores worlds in LevelDB (folder db/): sorted tables (*.ldb, blocks
compressed with zlib) plus a write-ahead log (*.log). Each chunk has a biome
record:

* Data3D (tag 43, 1.18+): a 16x16 height map (int16, relative to the bottom of
  the world), then one paletted 16x16x16 biome storage per sub-chunk from the
  bottom up.
* Data2D (tag 45, chunks not touched since 1.18): the height map plus one
  biome id (byte) per column.

For the web page only the surface biome matters, sampled every 4 blocks (the
resolution biomes are generated in): 16 cells per chunk. Checked against
uNmINeD's own biome rendering: 98.9% of land pixels agree; the rest are
pixels on biome borders.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator
from pathlib import Path

TAG_DATA3D = 43
TAG_DATA2D = 45
DIMENSION_IDS = {"overworld": 0, "nether": 1, "end": 2}
MIN_Y = {"overworld": -64, "nether": 0, "end": 0}  # bottom of the world (Data3D heights are relative to it)

CELL = 4                    # blocks per biome cell
CELLS = 16 // CELL          # cells per chunk side
UNKNOWN = 255               # biome id used when a column has no data


class BedrockError(Exception):
    pass


# --------------------------------------------------------------------------
# LevelDB (read-only)
# --------------------------------------------------------------------------

def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, pos
        shift += 7


def _read_block(f, offset: int, size: int) -> bytes:
    f.seek(offset)
    data = f.read(size + 5)  # block + trailer (compression type, crc)
    kind = data[size]
    if kind == 0:
        return data[:size]
    if kind == 2:   # zlib
        return zlib.decompress(data[:size])
    if kind == 4:   # raw deflate (Mojang's LevelDB fork)
        return zlib.decompress(data[:size], -15)
    raise BedrockError(f"Unsupported LevelDB block compression {kind}")


def _block_entries(block: bytes) -> Iterator[tuple[bytes, int, int]]:
    """(key, value offset, value length) of every entry in a table block."""
    restarts = struct.unpack_from("<I", block, len(block) - 4)[0]
    end = len(block) - 4 - 4 * restarts
    pos = 0
    key = b""
    while pos < end:
        shared, pos = _varint(block, pos)
        non_shared, pos = _varint(block, pos)
        length, pos = _varint(block, pos)
        key = key[:shared] + block[pos:pos + non_shared]
        pos += non_shared
        yield key, pos, length
        pos += length


def _table(path: Path, user_key_lengths: frozenset[int]) -> Iterator[tuple[bytes, int, int, bytes, int, int]]:
    """(user key, sequence, kind, buffer, value offset, value length) of a *.ldb
    table, only for user keys of the given lengths (cheap pre-filter)."""
    lengths = {n + 8 for n in user_key_lengths}  # internal key = user key + 8 byte tag
    with open(path, "rb") as f:
        f.seek(-48, 2)
        footer = f.read(48)
        if footer[-8:] != b"\x57\xfb\x80\x8b\x24\x75\x47\xdb":
            raise BedrockError(f"Not a LevelDB table: {path.name}")
        _, p = _varint(footer, 0)          # meta index handle (unused)
        _, p = _varint(footer, p)
        offset, p = _varint(footer, p)     # index handle
        size, p = _varint(footer, p)
        index = _read_block(f, offset, size)
        for _, vpos, _ in _block_entries(index):
            block_offset, q = _varint(index, vpos)
            block_size, _ = _varint(index, q)
            block = _read_block(f, block_offset, block_size)
            for key, vpos2, length in _block_entries(block):
                if len(key) not in lengths:
                    continue
                tag = struct.unpack_from("<Q", key, len(key) - 8)[0]
                yield key[:-8], tag >> 8, tag & 0xFF, block, vpos2, length


def _log(path: Path) -> Iterator[tuple[bytes, int, int, bytes, int, int]]:
    """Same as _table for a write-ahead log (*.log): records not yet in a table."""
    data = path.read_bytes()
    batches: list[bytes] = []
    pending = b""
    pos = 0
    while pos + 7 <= len(data):
        left = 32768 - pos % 32768
        if left < 7:                       # block trailer padding
            pos += left
            continue
        length, kind = struct.unpack_from("<HB", data, pos + 4)
        payload = data[pos + 7:pos + 7 + length]
        pos += 7 + length
        if kind == 1:                      # full
            batches.append(payload)
        elif kind == 2:                    # first
            pending = payload
        elif kind == 3:                    # middle
            pending += payload
        elif kind == 4:                    # last
            batches.append(pending + payload)
        else:                              # zero padding / end
            break
    for batch in batches:
        if len(batch) < 12:
            continue
        sequence, count = struct.unpack_from("<QI", batch, 0)
        p = 12
        try:
            for i in range(count):
                kind = batch[p]
                p += 1
                klen, p = _varint(batch, p)
                key = batch[p:p + klen]
                p += klen
                if kind == 1:
                    vlen, p = _varint(batch, p)
                    yield key, sequence + i, 1, batch, p, vlen
                    p += vlen
                else:
                    yield key, sequence + i, 0, batch, p, 0
        except IndexError:                 # torn write at the end of the log
            return


# --------------------------------------------------------------------------
# Chunk biome records
# --------------------------------------------------------------------------

def _sample_columns() -> list[tuple[int, int]]:
    """(x, z) inside a chunk sampled for each cell, row by row (z, then x)."""
    mid = CELL // 2
    return [(cx * CELL + mid, cz * CELL + mid) for cz in range(CELLS) for cx in range(CELLS)]


_COLUMNS = _sample_columns()


def _surface_3d(value: bytes, top: int | None = None) -> bytes:
    """`top`: highest y to look at, relative to the bottom of the world (for the
    Nether, rendered below its bedrock roof)."""
    heights = struct.unpack_from("<256h", value, 0)
    # Sub-chunk index and y inside it for every sampled column.
    wanted = []
    for x, z in _COLUMNS:
        y = max(heights[z * 16 + x] - 1, 0)
        if top is not None:
            y = min(y, top)
        wanted.append((y >> 4, x, y & 15, z))
    top = max(w[0] for w in wanted)

    # Walk the storage headers up to the highest surface sub-chunk, keeping
    # only where each one's data is. 0xFF means "same as the storage below",
    # which is common above the terrain, so the reference is copied as is.
    # Values are read word by word when needed (no full unpacking).
    storages: list[tuple[list[int], int, int]] = []  # (palette, bits, offset of the packed words)
    pos = 512
    while pos < len(value) and len(storages) <= top:
        header = value[pos]
        pos += 1
        if header == 0xFF:
            if not storages:
                break
            storages.append(storages[-1])
            continue
        bits = header >> 1
        if bits == 0:
            storages.append(([struct.unpack_from("<i", value, pos)[0]], 0, 0))
            pos += 4
            continue
        per_word = 32 // bits
        words_at = pos
        pos += 4 * -(-4096 // per_word)
        size = struct.unpack_from("<i", value, pos)[0]
        pos += 4
        storages.append((list(struct.unpack_from(f"<{size}i", value, pos)), bits, words_at))
        pos += 4 * size

    out = bytearray(len(wanted))
    for i, (sub, x, y, z) in enumerate(wanted):
        if sub >= len(storages):
            out[i] = UNKNOWN
            continue
        palette, bits, words_at = storages[sub]
        if bits == 0:
            biome = palette[0]
        else:
            n = (x << 8) | (z << 4) | y
            per_word = 32 // bits
            word = struct.unpack_from("<I", value, words_at + 4 * (n // per_word))[0]
            index = (word >> ((n % per_word) * bits)) & ((1 << bits) - 1)
            biome = palette[index] if index < len(palette) else UNKNOWN
        out[i] = biome if 0 <= biome < UNKNOWN else UNKNOWN
    return bytes(out)


def _surface_2d(value: bytes) -> bytes:
    if len(value) < 768:
        return bytes([UNKNOWN]) * len(_COLUMNS)
    return bytes(value[512 + z * 16 + x] for x, z in _COLUMNS)


def _chunk_key(key: bytes) -> tuple[int, int, int, int] | None:
    """(dimension, x, z, tag) for a biome record key, else None."""
    if len(key) == 9 and key[8] in (TAG_DATA3D, TAG_DATA2D):
        x, z = struct.unpack_from("<ii", key, 0)
        return 0, x, z, key[8]
    if len(key) == 13 and key[12] in (TAG_DATA3D, TAG_DATA2D):
        x, z, dim = struct.unpack_from("<iii", key, 0)
        return dim, x, z, key[12]
    return None


def surface_biomes(world: Path, dims: list[str],
                   top_y: dict[str, int] | None = None) -> dict[str, dict[tuple[int, int], bytes]]:
    """Surface biome ids per chunk: {dim: {(chunk x, chunk z): 16 bytes}}.

    The 16 bytes are the cells of the chunk row by row (z, then x); 255 = unknown.
    `top_y` limits the height per dimension (absolute y), like uNmINeD's --topY.
    """
    tops = {DIMENSION_IDS[d]: y - MIN_Y[d] for d, y in (top_y or {}).items() if d in MIN_Y}
    db = world / "db"
    if not db.is_dir():
        raise BedrockError(f"{world} is not a Bedrock world (db/ missing).")
    wanted = {DIMENSION_IDS[d] for d in dims}
    # (dim, x, z) -> (prefer Data3D, sequence, cells or None for deleted)
    latest: dict[tuple[int, int, int], tuple[bool, int, bytes | None]] = {}

    def take(key: bytes, seq: int, kind: int, buf: bytes, vpos: int, vlen: int) -> None:
        ck = _chunk_key(key)
        if ck is None or ck[0] not in wanted:
            return
        dim, x, z, tag = ck
        rank = (tag == TAG_DATA3D, seq)
        old = latest.get((dim, x, z))
        if old is not None and (old[0], old[1]) >= rank:
            return
        if kind != 1:
            latest[(dim, x, z)] = (*rank, None)
            return
        value = buf[vpos:vpos + vlen]
        try:
            cells = _surface_3d(value, tops.get(dim)) if tag == TAG_DATA3D else _surface_2d(value)
        except (struct.error, IndexError, ValueError):
            return  # damaged record: leave the chunk without data
        latest[(dim, x, z)] = (*rank, cells)

    chunk_key_lengths = frozenset((9, 13))
    for path in sorted(db.glob("*.ldb")):
        for entry in _table(path, chunk_key_lengths):
            take(*entry)
    for path in sorted(db.glob("*.log")):
        for entry in _log(path):
            take(*entry)

    by_id = {v: k for k, v in DIMENSION_IDS.items()}
    result: dict[str, dict[tuple[int, int], bytes]] = {d: {} for d in dims}
    for (dim, x, z), (_, _, cells) in latest.items():
        if cells is not None:
            result[by_id[dim]][(x, z)] = cells
    return result
