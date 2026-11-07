"""SGA v5 archive reader (Dawn of War II / Chaos Rising).

Format evidence:
- Verified against GameAttrib.sga from the user's DoW2+CR Steam install.
- Struct layout per ModernMAK Relic-Game-Tool wiki (SGA Archive page) and
  corsix.org/content/sga4to5.

Layout (little-endian):
  0x00  8s   magic b"_ARCHIVE"
  0x08  H    major version (5)
  0x0A  H    minor version (0)
  0x0C  16s  MD5 #1
  0x1C  128s archive name, UTF-16LE, null padded (64 chars)
  0x9C  16s  MD5 #2
  0xAC  I    toc_size
  0xB0  I    data_offset (absolute)
  0xB4  I    toc_offset (absolute)
  0xB8  I    reserved(1), 0xBC I reserved(0), 0xC0 I unknown id -> header is 196 bytes

ToC header (at toc_offset, offsets relative to toc_offset):
  I drive_off, H drive_count
  I folder_off, H folder_count
  I file_off,  H file_count
  I name_off,  H name_count

Drive record (138 bytes): 64s path, 64s name, H folder_start, H folder_end,
  H file_start, H file_end, H root_folder
Folder record (12 bytes): I name_off, H sub_start, H sub_end, H file_start, H file_end
File record v5 (22 bytes): I name_off, I data_off, I comp_len, I decomp_len,
  I modified?, B verify?, B storage_type
Storage: comp_len != decomp_len -> zlib. (v5 has no reliable per-file flag;
  trailing byte observed 0/1/2 correlating with store/stream/buffer.)
"""
from __future__ import annotations
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SgaFile:
    name: str
    folder: str
    data_offset: int
    comp_len: int
    decomp_len: int
    storage: int

    @property
    def path(self) -> str:
        return f"{self.folder}/{self.name}" if self.folder else self.name


@dataclass
class SgaArchive:
    path: Path
    name: str = ""
    files: dict[str, SgaFile] = field(default_factory=dict)
    _data_base: int = 0

    @classmethod
    def open(cls, path: str | Path) -> "SgaArchive":
        """Lazy open: reads only the header + TOC (KBs), never the data buffer.
        File contents are seek-read on demand — a 1 GB archive costs ~nothing
        to open and only the requested files are ever decompressed."""
        path = Path(path)
        fh = open(path, "rb")
        hdr = fh.read(196)
        if hdr[:8] != b"_ARCHIVE":
            fh.close()
            raise ValueError(f"{path}: not an SGA archive")
        major, minor = struct.unpack_from("<HH", hdr, 8)
        if major != 5:
            fh.close()
            raise ValueError(f"{path}: SGA v{major}.{minor}, only v5 supported")
        arc_name = hdr[28:156].decode("utf-16-le").rstrip("\x00")
        toc_size, data_off, toc_off = struct.unpack_from("<III", hdr, 172)
        fh.seek(toc_off)
        toc = fh.read(toc_size)

        (drive_off, drive_n, folder_off, folder_n,
         file_off, file_n, name_off, name_n) = struct.unpack_from("<IHIHIHIH", toc, 0)

        def cstr(rel: int) -> str:
            start = name_off + rel
            end = toc.index(b"\x00", start)
            return toc[start:end].decode("ascii", "replace")

        folders = []
        for i in range(folder_n):
            off = folder_off + i * 12
            nameo, ss, se, fs, fe = struct.unpack_from("<IHHHH", toc, off)
            folders.append((cstr(nameo).replace("\\", "/"), ss, se, fs, fe))
        # file index -> owning folder without O(files*folders) scan
        owner_of = [""] * file_n
        for fpath, ss, se, fs, fe in folders:
            for i in range(fs, fe):
                owner_of[i] = fpath

        arc = cls(path=path, name=arc_name, _data_base=data_off)
        for i in range(file_n):
            off = file_off + i * 22
            nameo, doff, clen, dlen, unk_i, unk_b1, unk_b2 = struct.unpack_from(
                "<IIIIIBB", toc, off)
            f = SgaFile(cstr(nameo), owner_of[i], doff, clen, dlen, unk_b2)
            arc.files[f.path.lower()] = f
        arc._fh = fh
        return arc

    def read(self, virtual_path: str) -> bytes:
        f = self.files[virtual_path.lower().replace("\\", "/")]
        self._fh.seek(self._data_base + f.data_offset)
        blob = self._fh.read(f.comp_len)
        if f.comp_len == f.decomp_len:
            return blob
        return zlib.decompress(blob)

    def close(self):
        if getattr(self, "_fh", None):
            self._fh.close()
            self._fh = None

    def extract_all(self, dest: str | Path) -> int:
        dest = Path(dest)
        n = 0
        for f in self.files.values():
            out = dest / f.path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(self.read(f.path))
            n += 1
        return n


if __name__ == "__main__":
    import sys
    arc = SgaArchive.open(sys.argv[1])
    print(f"{arc.name}: {len(arc.files)} files")
    if len(sys.argv) > 2:
        print("extracted", arc.extract_all(sys.argv[2]))
