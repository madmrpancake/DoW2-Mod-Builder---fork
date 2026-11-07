"""SGA v5 archive writer (Dawn of War II / Chaos Rising).

Mirrors the layout conventions observed in Relic's own GameAttrib.sga:
  header(196) | data buffer (from 196) | TOC at end: drives, folders, files, names
  drive record: (path=toc_alias 64s, name 64s, folder_start, folder_end,
                 file_start, file_end, root_folder=0)
  folders: DFS order, full backslash paths, root folder "" at index 0
  files: storage 1 (zlib stream-compress) unless compression doesn't help (0)
  file record: name_off, data_off, comp_len, decomp_len, modified_unix,
               verification(0), storage
  CRITICAL (engine-verified): every file's stored data is PRECEDED by a
  260-byte preamble = filename (256B, null-padded) + u32 CRC32 of the
  DECOMPRESSED data. The record's data_off points PAST the preamble. The
  engine verifies this and crashes on boot without it.
  header_md5 = md5(b"DFC9AF62-FC1B-4180-BC27-11CCE87D3EFF" + toc_bytes)
  file_md5   = md5(b"E01519D6-2DB7-4640-AF54-0A23319C56C3" + bytes[196:EOF])
    (eigen keys + coverage verified against the shipped GameAttrib.sga)
"""
from __future__ import annotations
import hashlib
import os
import struct
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FILE_MD5_EIGEN = b"E01519D6-2DB7-4640-AF54-0A23319C56C3"
HEADER_MD5_EIGEN = b"DFC9AF62-FC1B-4180-BC27-11CCE87D3EFF"


def long_path(p: Path) -> Path:
    r"""Windows can't open paths past 260 characters with normal calls. The
    \\?\ prefix lifts that limit, so deep folders (a builder unpacked several
    levels down, say) still pack correctly."""
    if sys.platform != "win32":
        return p
    s = str(p.resolve())
    if len(s) < 200 or s.startswith("\\\\?\\"):
        return p
    return Path("\\\\?\\" + s)


def build_sga(src_root: str | Path, out_path: str | Path, *,
              archive_name: str, toc_alias: str = "Attrib",
              toc_name: str = "Attributes",
              only: set[str] | None = None,
              skip: set[str] | None = None,
              progress=None) -> dict:
    """Pack every file under src_root into a v5 SGA. Returns a build report.

    only/skip filter the TOP-LEVEL entries of src_root, which lets one output
    folder be split into two archives without copying anything first."""
    src_root = Path(src_root)

    # ---- collect folders (DFS) and files -------------------------------
    folders: list[dict] = []          # {path, sub_start, sub_end, file_start, file_end}
    files: list[dict] = []            # {name, src, folder_index}

    def add_folder(dir_path: Path, rel: str) -> int:
        idx = len(folders)
        folders.append({"path": rel, "sub_start": 0, "sub_end": 0,
                        "file_start": 0, "file_end": 0})
        entries = list(long_path(dir_path).iterdir())
        if not rel:                            # top level only
            if only is not None:
                entries = [e for e in entries if e.name in only]
            if skip is not None:
                entries = [e for e in entries if e.name not in skip]
        subdirs = sorted([p for p in entries if p.is_dir()],
                         key=lambda p: p.name.lower())
        fs = sorted([p for p in entries if p.is_file()],
                    key=lambda p: p.name.lower())
        folders[idx]["_subdirs"] = subdirs
        folders[idx]["_files"] = fs
        return idx

    # BFS layout like Relic: folder list is created so children come after
    # parents; original uses DFS-ish full-path order — we emulate by walking
    # breadth-first per level which also satisfies parent<child ordering.
    queue = [(src_root, "")]
    order: list[tuple[Path, str, int]] = []
    while queue:
        d, rel = queue.pop(0)
        idx = add_folder(d, rel)
        order.append((d, rel, idx))
        for sd in folders[idx]["_subdirs"]:
            sub_rel = f"{rel}\\{sd.name}" if rel else sd.name
            queue.append((sd, sub_rel))

    # fix up ranges now that all folders exist, in creation (BFS) order
    next_child = 1
    for d, rel, idx in order:
        n_sub = len(folders[idx]["_subdirs"])
        folders[idx]["sub_start"] = next_child
        folders[idx]["sub_end"] = next_child + n_sub
        next_child += n_sub
    for d, rel, idx in order:
        folders[idx]["file_start"] = len(files)
        for f in folders[idx]["_files"]:
            files.append({"name": f.name, "src": f, "folder": idx})
        folders[idx]["file_end"] = len(files)

    # ---- name buffer ----------------------------------------------------
    name_buf = bytearray()
    name_off: dict[str, int] = {}

    def nb(s: str) -> int:
        if s not in name_off:
            name_off[s] = len(name_buf)
            name_buf.extend(s.encode("ascii") + b"\x00")
        return name_off[s]

    for fo in folders:
        fo["name_off"] = nb(fo["path"])
    for fi in files:
        fi["name_off"] = nb(fi["name"])

    # ---- data buffer ----------------------------------------------------
    # each file: 260-byte preamble (name[256] + crc32 of DECOMPRESSED bytes),
    # then the (possibly compressed) blob; record data_off points past preamble
    # Compressed on several threads (zlib releases the GIL) and at level 6:
    # level 9 cost several times the time for a fraction of a percent of size
    # on this kind of data. Results are consumed in file order, so the archive
    # is identical whatever order the threads finish in.
    def _pack(fi):
        p = long_path(fi["src"])
        raw = p.read_bytes()
        comp = zlib.compress(raw, 6)
        if len(comp) < len(raw):
            return fi, raw, comp, 1          # stream compress
        return fi, raw, raw, 0               # store

    data = bytearray()
    workers = min(8, (os.cpu_count() or 2))
    done = 0
    batches = [files[i:i + 256] for i in range(0, len(files), 256)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fi, raw, blob, storage in (r for batch in batches
                                       for r in ex.map(_pack, batch)):
            data.extend(fi["name"].encode("ascii")[:255].ljust(256, b"\x00"))
            data.extend(struct.pack("<I", zlib.crc32(raw) & 0xFFFFFFFF))
            fi["data_off"] = len(data)
            fi["comp_len"] = len(blob)
            fi["decomp_len"] = len(raw)
            fi["storage"] = storage
            fi["modified"] = int(long_path(fi["src"]).stat().st_mtime)
            data.extend(blob)
            done += 1
            if progress and (done % 100 == 0 or done == len(files)):
                progress(done, len(files))

    # ---- TOC -------------------------------------------------------------
    toc_hdr_size = 24
    drive_off = toc_hdr_size
    drives_bytes = struct.pack(
        "<64s64s5H",
        toc_alias.encode("ascii"), toc_name.encode("ascii"),
        0, len(folders), 0, len(files), 0)
    folder_off = drive_off + len(drives_bytes)
    folder_bytes = b"".join(
        struct.pack("<IHHHH", fo["name_off"], fo["sub_start"], fo["sub_end"],
                    fo["file_start"], fo["file_end"]) for fo in folders)
    file_off = folder_off + len(folder_bytes)
    file_bytes = b"".join(
        struct.pack("<IIIIIBB", fi["name_off"], fi["data_off"], fi["comp_len"],
                    fi["decomp_len"], fi["modified"], 0, fi["storage"])
        for fi in files)
    names_off = file_off + len(file_bytes)
    toc = (struct.pack("<IHIHIHIH",
                       drive_off, 1,
                       folder_off, len(folders),
                       file_off, len(files),
                       names_off, len(folders) + len(files))
           + drives_bytes + folder_bytes + file_bytes + bytes(name_buf))

    # ---- assemble --------------------------------------------------------
    data_offset = 196
    toc_offset = data_offset + len(data)
    body = bytes(data) + toc
    file_md5 = hashlib.md5(FILE_MD5_EIGEN + body).digest()
    header_md5 = hashlib.md5(HEADER_MD5_EIGEN + toc).digest()
    header = (b"_ARCHIVE" + struct.pack("<HH", 5, 0)
              + file_md5
              + archive_name.encode("utf-16-le").ljust(128, b"\x00")
              + header_md5
              + struct.pack("<IIIIII", len(toc), data_offset, toc_offset, 1, 0, 0))
    assert len(header) == 196, len(header)
    out = header + body
    op = Path(out_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    long_path(op).write_bytes(out)
    return {"files": len(files), "folders": len(folders),
            "bytes": len(out), "toc_size": len(toc), "out": str(out_path)}


if __name__ == "__main__":
    import sys, json
    rep = build_sga(sys.argv[1], sys.argv[2],
                    archive_name=sys.argv[3] if len(sys.argv) > 3 else "ModArchive")
    print(json.dumps(rep, indent=1))
