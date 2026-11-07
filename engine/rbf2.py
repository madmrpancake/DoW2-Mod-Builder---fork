"""Retribution RBF variant + fieldnames.flb + attribmegabinary.rb2.

Reverse-engineered 2026-08-11 from Retribution's GameAttrib.sga.

RBF variant ("RBF V0.1", u32@8 = 0x28):
  0x00  8s   magic "RBF V0.1"
  0x08  I    0x28 (constant across all shipped files; meaning unknown)
  0x0C  I    descriptor count D
  0x10  I,I  children table offset, entry count (u32 node indices)
  0x18  I,I  node table offset, node count  (8-byte records!)
  0x20  I,I  data heap offset, heap size
  0x28  I,I  descriptor[0] (count,start)   0x30 I,I descriptor[1]
  0x38  descriptors[2..D-1] (8B each), then children, nodes, heap.
  Node record: u16 type, u16 key_index (into fieldnames.flb), u32 data.
  Types/descriptor semantics identical to classic RBF (engine/rbf.py):
  0=bool 1=float 2=int 3=string(heap off: u32 len+ascii) 4=table(ordinal);
  descriptor count==1 -> start IS child node index.

fieldnames.flb:
  u32 count, count x u32 absolute offsets; each entry: u32 hash + cstring.
  (hash algorithm not identified; existing entries are reused verbatim,
  new field names are refused until the hash is cracked.)

attribmegabinary.rb2:
  u32 magic 0x12345678, u32 count,
  count x (u32 len + path bytes)          -- names, in order
  count x (u32 size + RBF-variant blob)   -- blobs, same order
"""
from __future__ import annotations
import struct
from pathlib import Path

from rbf import RbfNode, BOOL, FLOAT, INT, STRING, TABLE, equal  # noqa: F401

RB2_MAGIC = 0x12345678
VARIANT_CONST = 0x28


class FieldNames:
    def __init__(self, blob: bytes):
        self.blob = blob
        (count,) = struct.unpack_from("<I", blob, 0)
        offs = struct.unpack_from(f"<{count}I", blob, 4)
        self.names: list[str] = []
        self.hashes: list[int] = []
        for o in offs:
            (h,) = struct.unpack_from("<I", blob, o)
            e = blob.index(b"\x00", o + 4)
            self.hashes.append(h)
            self.names.append(blob[o + 4:e].decode("ascii"))
        self.index = {n: i for i, n in enumerate(self.names)}

    def key(self, i: int) -> str:
        return self.names[i]

    def idx(self, name: str) -> int:
        if name not in self.index:
            raise ValueError(
                f"field name {name!r} is not in fieldnames.flb - adding new field "
                "names requires the (unknown) hash algorithm; rename or use existing keys")
        return self.index[name]


def load(blob: bytes, fields: FieldNames) -> RbfNode:
    if blob[:8] != b"RBF V0.1":
        raise ValueError("not an RBF variant blob")
    (const,) = struct.unpack_from("<I", blob, 8)
    (dcount, ch_off, ch_n, nodes_off, nodes_n, heap_off, heap_n,
     d0c, d0s, d1c, d1s) = struct.unpack_from("<11I", blob, 12)
    desc = [(d0c, d0s), (d1c, d1s)]
    for i in range(dcount - 2):
        desc.append(struct.unpack_from("<II", blob, 0x38 + i * 8))
    children = struct.unpack_from(f"<{ch_n}I", blob, ch_off) if ch_n else ()
    raw = [struct.unpack_from("<HHI", blob, nodes_off + i * 8) for i in range(nodes_n)]

    def heap_str(off):
        (n,) = struct.unpack_from("<I", blob, heap_off + off)
        return blob[heap_off + off + 4: heap_off + off + 4 + n].decode("ascii", "replace")

    def kids(ordinal):
        cnt, st = desc[ordinal]
        if cnt == 0:
            return []
        if cnt == 1:
            return [st]
        return list(children[st: st + cnt])

    def build(idx):
        t, k, v = raw[idx]
        key = fields.key(k)
        if t == TABLE:
            n = RbfNode(key, TABLE)
            n.children = [build(c) for c in kids(v)]
            return n
        if t == BOOL:
            return RbfNode(key, BOOL, bool(v))
        if t == FLOAT:
            return RbfNode(key, FLOAT, struct.unpack("<f", struct.pack("<I", v))[0])
        if t == INT:
            return RbfNode(key, INT, struct.unpack("<i", struct.pack("<I", v))[0])
        if t == STRING:
            return RbfNode(key, STRING, heap_str(v))
        raise ValueError(f"unknown node type {t}")

    root = RbfNode("", TABLE)
    root.children = [build(c) for c in kids(0)]
    return root


def save(root: RbfNode, fields: FieldNames) -> bytes:
    from collections import deque
    node_of, order = {}, []
    q = deque(root.children)
    while q:
        n = q.popleft()
        node_of[id(n)] = len(order)
        order.append(n)
        if n.type == TABLE:
            q.extend(n.children)
    table_nodes = [n for n in order if n.type == TABLE]
    ordinal_of = {id(n): i + 1 for i, n in enumerate(table_nodes)}

    children_tab: list[int] = []
    def make_desc(kids_):
        idxs = [node_of[id(c)] for c in kids_]
        if not idxs:
            return (0, 0)
        if len(idxs) == 1:
            return (1, idxs[0])
        st = len(children_tab)
        children_tab.extend(idxs)
        return (len(idxs), st)

    desc = [make_desc(root.children)] + [make_desc(t.children) for t in table_nodes]

    heap = bytearray()
    heap_idx: dict[str, int] = {}
    def hoff(s):
        if s not in heap_idx:
            heap_idx[s] = len(heap)
            b = s.encode("ascii")
            heap.extend(struct.pack("<I", len(b)) + b)
        return heap_idx[s]

    nodes = []
    for n in order:
        k = fields.idx(n.key)
        if n.type == TABLE:
            nodes.append((TABLE, k, ordinal_of[id(n)]))
        elif n.type == BOOL:
            nodes.append((BOOL, k, 1 if n.value else 0))
        elif n.type == FLOAT:
            nodes.append((FLOAT, k, struct.unpack("<I", struct.pack("<f", n.value))[0]))
        elif n.type == INT:
            nodes.append((INT, k, n.value & 0xFFFFFFFF))
        elif n.type == STRING:
            nodes.append((STRING, k, hoff(n.value)))
        else:
            raise ValueError(f"bad node type {n.type}")

    dcount = len(desc)
    ch_off = 0x38 + max(0, dcount - 2) * 8
    nodes_off = ch_off + len(children_tab) * 4
    heap_off = nodes_off + len(nodes) * 8
    d0 = desc[0]
    d1 = desc[1] if dcount > 1 else (0, 0)
    out = bytearray(b"RBF V0.1")
    out += struct.pack("<I", VARIANT_CONST)
    out += struct.pack("<11I", dcount, ch_off, len(children_tab),
                       nodes_off, len(nodes), heap_off, len(heap),
                       d0[0], d0[1], d1[0], d1[1])
    for c, s in desc[2:]:
        out += struct.pack("<II", c, s)
    for c in children_tab:
        out += struct.pack("<I", c)
    for t, k, v in nodes:
        out += struct.pack("<HHI", t, k, v)
    out += heap
    return bytes(out)


class Rb2:
    """attribmegabinary.rb2 container."""

    def __init__(self, names: list[str], blobs: list[bytes]):
        self.names = names
        self.blobs = blobs
        self.index = {n.lower(): i for i, n in enumerate(names)}

    @classmethod
    def parse(cls, d: bytes) -> "Rb2":
        magic, count = struct.unpack_from("<II", d, 0)
        if magic != RB2_MAGIC:
            raise ValueError("not an rb2 container")
        pos = 8
        names = []
        for _ in range(count):
            (n,) = struct.unpack_from("<I", d, pos)
            names.append(d[pos + 4:pos + 4 + n].decode("ascii"))
            pos += 4 + n
        blobs = []
        for _ in range(count):
            (n,) = struct.unpack_from("<I", d, pos)
            blobs.append(d[pos + 4:pos + 4 + n])
            pos += 4 + n
        # footer: closing magic
        if pos + 4 != len(d) or struct.unpack_from("<I", d, pos)[0] != RB2_MAGIC:
            raise ValueError("rb2: missing closing magic")
        return cls(names, blobs)

    def serialize(self) -> bytes:
        out = bytearray(struct.pack("<II", RB2_MAGIC, len(self.names)))
        for n in self.names:
            b = n.encode("ascii")
            out += struct.pack("<I", len(b)) + b
        for blob in self.blobs:
            out += struct.pack("<I", len(blob)) + blob
        out += struct.pack("<I", RB2_MAGIC)
        return bytes(out)

    def tree(self, name: str, fields: FieldNames) -> RbfNode:
        return load(self.blobs[self.index[name.lower()]], fields)

    def replace(self, name: str, tree: RbfNode, fields: FieldNames) -> None:
        self.blobs[self.index[name.lower()]] = save(tree, fields)
