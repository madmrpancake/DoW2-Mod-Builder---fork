"""RBF (Relic Binary File) v0.1 reader/writer — DoW2/Chaos Rising attribute format.

Reverse-engineered 2026-08-11 from GameAttrib.sga contents (9,028 files,
all round-trip verified). Little-endian throughout.

File layout:
  0x00  12s  magic "RBF V0.10\\0\\0\\0"
  0x0C  I    descriptor count D (= table count + 1; descriptor 0 is the
             virtual root of the file)
  0x10  I,I  keys table offset, key count       (64-byte null-padded ASCII each)
  0x18  I,I  children table offset, entry count (uint32 node indices)
  0x20  I,I  node table offset, node count      (12-byte records)
  0x28  I,I  data heap offset, heap size (bytes)
  0x30  I,I  descriptor[0]  (count, start)  -- root
  0x38  I,I  descriptor[1]  (count, start)
  0x40       descriptors[2..D-1], 8 bytes each, then keys table follows.

Node record: (uint32 type, uint32 key_index, uint32 data)
  type 0 = bool   data = 0/1
  type 1 = float  data = raw IEEE754 bits
  type 2 = int    data = int32
  type 3 = string data = heap offset of (uint32 length + ASCII bytes)
  type 4 = table  data = table ordinal (1-based index into descriptors)

Descriptor (count, start):
  count == 0 -> no children
  count == 1 -> start IS the child's node index (children table not used)
  count >= 2 -> children = children_table[start : start + count]

Canonical writer layout (matches Relic's): BFS node order, ordinals assigned
in node order, multi-child lists appended to the children table in BFS order,
strings appended to heap in node order, keys in first-use order.
"""
from __future__ import annotations
import struct
from pathlib import Path

MAGIC = b"RBF V0.10\x00\x00\x00"

BOOL, FLOAT, INT, STRING, TABLE = range(5)


class RbfNode:
    __slots__ = ("key", "type", "value", "children")

    def __init__(self, key, type_, value=None, children=None):
        self.key = key
        self.type = type_
        self.value = value
        self.children = children if children is not None else []

    def __repr__(self):
        if self.type == TABLE:
            return f"<table {self.key} [{len(self.children)}]>"
        return f"<{('bool','float','int','str')[self.type]} {self.key}={self.value!r}>"

    # ---- dict/JSON conversion -------------------------------------------
    def to_obj(self):
        if self.type == TABLE:
            # keys can repeat inside a table -> keep as list of pairs
            return [c.key, c.to_obj_value()] and [[c.key, c.to_obj_value()] for c in self.children]
        return self.to_obj_value()

    def to_obj_value(self):
        if self.type == TABLE:
            return [[c.key, c.to_obj_value()] for c in self.children]
        if self.type == BOOL:
            return bool(self.value)
        return self.value


def load(path: str | Path | bytes) -> RbfNode:
    d = path if isinstance(path, bytes) else Path(path).read_bytes()
    if d[:12] != MAGIC:
        raise ValueError("not an RBF v0.1 file")
    (dcount, keys_off, keys_n, ch_off, ch_n, nodes_off, nodes_n,
     heap_off, heap_n, d0c, d0s, d1c, d1s) = struct.unpack_from("<13I", d, 12)

    desc = [(d0c, d0s), (d1c, d1s)]
    for i in range(dcount - 2):
        desc.append(struct.unpack_from("<II", d, 0x40 + i * 8))

    keys = [d[keys_off + i*64: keys_off + i*64 + 64].split(b"\x00")[0].decode("ascii")
            for i in range(keys_n)]
    children = struct.unpack_from(f"<{ch_n}I", d, ch_off) if ch_n else ()
    raw_nodes = [struct.unpack_from("<3I", d, nodes_off + i*12) for i in range(nodes_n)]

    def heap_str(off):
        (n,) = struct.unpack_from("<I", d, heap_off + off)
        return d[heap_off + off + 4: heap_off + off + 4 + n].decode("ascii", "replace")

    def child_indices(ordinal):
        cnt, st = desc[ordinal]
        if cnt == 0:
            return []
        if cnt == 1:
            return [st]
        return list(children[st: st + cnt])

    def build(idx):
        t, k, v = raw_nodes[idx]
        key = keys[k]
        if t == TABLE:
            node = RbfNode(key, TABLE)
            node.children = [build(c) for c in child_indices(v)]
            return node
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
    root.children = [build(c) for c in child_indices(0)]
    return root


def save(root: RbfNode, path: str | Path | None = None) -> bytes:
    """Serialize using the canonical (Relic-matching) BFS layout."""
    keys: list[str] = []
    key_idx: dict[str, int] = {}
    nodes: list[tuple[int, int, int]] = []     # placeholders
    children_tab: list[int] = []
    heap = bytearray()
    heap_idx: dict[str, int] = {}
    desc: list[tuple[int, int]] = []           # (count, start)
    table_nodes: list[RbfNode] = []            # by ordinal-1

    def kidx(k):
        if k not in key_idx:
            key_idx[k] = len(keys)
            keys.append(k)
        return key_idx[k]

    def hoff(s):
        if s not in heap_idx:
            heap_idx[s] = len(heap)
            b = s.encode("ascii")
            heap.extend(struct.pack("<I", len(b)) + b)
        return heap_idx[s]

    # BFS: assign node indices level by level; tables get ordinals in node order
    from collections import deque
    node_of: dict[int, int] = {}   # id(RbfNode) -> node index
    order: list[RbfNode] = []
    q = deque(root.children)
    while q:
        n = q.popleft()
        node_of[id(n)] = len(order)
        order.append(n)
        if n.type == TABLE:
            q.extend(n.children)

    ordinal_of: dict[int, int] = {}
    for n in order:
        if n.type == TABLE:
            table_nodes.append(n)
            ordinal_of[id(n)] = len(table_nodes)   # 1-based

    def make_desc(child_list):
        idxs = [node_of[id(c)] for c in child_list]
        if not idxs:
            return (0, 0)
        if len(idxs) == 1:
            return (1, idxs[0])
        start = len(children_tab)
        children_tab.extend(idxs)
        return (len(idxs), start)

    desc.append(make_desc(root.children))          # ordinal 0 = virtual root
    for t in table_nodes:
        desc.append(make_desc(t.children))

    for n in order:
        k = kidx(n.key)
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
    keys_off = 0x40 + max(0, dcount - 2) * 8
    ch_off = keys_off + len(keys) * 64
    nodes_off = ch_off + len(children_tab) * 4
    heap_off = nodes_off + len(nodes) * 12

    d0 = desc[0]
    d1 = desc[1] if dcount > 1 else (0, 0)
    out = bytearray()
    out += MAGIC
    out += struct.pack("<13I", dcount, keys_off, len(keys), ch_off, len(children_tab),
                       nodes_off, len(nodes), heap_off, len(heap),
                       d0[0], d0[1], d1[0], d1[1])
    for c, s in desc[2:]:
        out += struct.pack("<II", c, s)
    for k in keys:
        out += k.encode("ascii").ljust(64, b"\x00")
    for c in children_tab:
        out += struct.pack("<I", c)
    for t, k, v in nodes:
        out += struct.pack("<3I", t, k, v)
    out += heap
    data = bytes(out)
    if path:
        Path(path).write_bytes(data)
    return data


def equal(a: RbfNode, b: RbfNode) -> bool:
    if a.key != b.key or a.type != b.type:
        return False
    if a.type == TABLE:
        return len(a.children) == len(b.children) and all(
            equal(x, y) for x, y in zip(a.children, b.children))
    if a.type == FLOAT:
        return struct.pack("<f", a.value) == struct.pack("<f", b.value)
    return a.value == b.value


# ---- path helpers --------------------------------------------------------
def find(root: RbfNode, path: str):
    """find(root, 'tuning_bag/combat/point_blank_range') -> first match or None"""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    cur = [root]
    for p in parts:
        nxt = []
        for c in cur:
            if c.type == TABLE:
                nxt.extend(ch for ch in c.children if ch.key == p)
        if not nxt:
            return None
        cur = nxt
    return cur[0]


def walk(root: RbfNode, prefix=""):
    for c in root.children:
        p = f"{prefix}/{c.key}" if prefix else c.key
        yield p, c
        if c.type == TABLE:
            yield from walk(c, p)


if __name__ == "__main__":
    import sys, json
    r = load(sys.argv[1])
    json.dump(r.to_obj_value(), sys.stdout, indent=1)


# ---- indexed path addressing ----------------------------------------------
# Keys can repeat among siblings; an indexed path disambiguates with [n]:
#   "wargear/weapons/weapon[1]"  = second 'weapon' child of weapons.
def walk_indexed(root: RbfNode, prefix=""):
    """Yield (indexed_path, node) for every descendant."""
    counts: dict[str, int] = {}
    for c in root.children:
        n = counts.get(c.key, 0)
        counts[c.key] = n + 1
        seg = c.key if n == 0 else f"{c.key}[{n}]"
        p = f"{prefix}/{seg}" if prefix else seg
        yield p, c
        if c.type == TABLE:
            yield from walk_indexed(c, p)


def find_indexed(root: RbfNode, ipath: str):
    """Resolve an indexed path (as produced by walk_indexed)."""
    import re as _re
    cur = root
    for seg in ipath.replace("\\", "/").split("/"):
        if not seg:
            continue
        m = _re.match(r"^(.*?)(?:\[(\d+)\])?$", seg)
        key, idx = m.group(1), int(m.group(2) or 0)
        matches = [c for c in cur.children if c.key == key] if cur.type == TABLE else []
        if idx >= len(matches):
            return None
        cur = matches[idx]
    return cur
