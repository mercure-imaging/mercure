#!/usr/bin/env python3
"""Generate a minimal DICOM file with a chosen SpecificCharacterSet.

Used to probe the oficonv exit-time use-after-free in getdcmtags (see README
notes on DCMTK >= 3.6.9 OFiconvCleanupHelper).  No pydicom needed.

usage: gen_charset_dcm.py OUT.dcm [--charset 'ISO_IR 100'] [--uids-from NAME]
"""
import argparse
import hashlib
import struct

EXPLICIT_LE = "1.2.840.10008.1.2.1"
SECONDARY_CAPTURE = "1.2.840.10008.5.1.4.1.1.7"
LONG_VRS = {"OB", "OW", "OF", "OD", "OL", "OV", "SQ", "UN", "UT"}


def elem(group, elem, vr, value: bytes):
    """Encode one explicit-VR little-endian element."""
    if len(value) % 2:                       # DICOM requires even length
        value += b"\x00"
    head = struct.pack("<HH", group, elem) + vr.encode()
    if vr in LONG_VRS:
        return head + b"\x00\x00" + struct.pack("<I", len(value)) + value
    return head + struct.pack("<H", len(value)) + value


def uid(seed: str, root: str = "1.2.826.0.1.3680043.9.7548") -> str:
    """Deterministic but unique-looking UID derived from seed."""
    digest = hashlib.sha1(seed.encode()).hexdigest()
    # fold hex into decimal digit groups, keep well under the 64 char limit
    parts = [str(int(digest[i:i + 6], 16)) for i in range(0, 18, 6)]
    return (root + "." + ".".join(parts))[:64]


def build(charset: str, seed: str = "x", pixlen: int = 0, attrs: int = 0,
          rows: int = 0, pattern: bytes = b"\x00", valsize: int = 7) -> bytes:
    sop = uid(seed + "/sop")
    series = uid(seed + "/series")

    # 8-bit bytes are what force a real iconv conversion descriptor:
    # 0xE4 = a-umlaut in Latin-1 / ISO 2022 IR 100.
    patient_name = b"M\xc3cller^Anna"          # Latin-1 'Müller'
    institution = b"Uni\xc3klinikum ^ Gro\xdfh\xc3\xa4ndorf"
    protocol = b"t\xc3\x84st\xff protocol"

    meta = (
        elem(0x0002, 0x0001, "OB", b"\x00\x01")
        + elem(0x0002, 0x0002, "UI", SECONDARY_CAPTURE.encode())
        + elem(0x0002, 0x0010, "UI", EXPLICIT_LE.encode())
        + elem(0x0002, 0x0012, "UI", uid(seed + "/impl").encode())
    )
    meta = elem(0x0002, 0x0000, "UL", struct.pack("<I", len(meta))) + meta

    cs = charset.encode("latin-1")
    if len(cs) % 2:
        cs += b"\x00" if charset else b""      # empty value stays zero-length

    ds = (
        elem(0x0008, 0x0005, "CS", cs)
        + elem(0x0008, 0x0016, "UI", SECONDARY_CAPTURE.encode())
        + elem(0x0008, 0x0018, "UI", sop.encode())
        + elem(0x0008, 0x0060, "CS", b"MR")
        + elem(0x0008, 0x0070, "LO", b"SIEMENS")
        + elem(0x0008, 0x1090, "LO", institution)
        + elem(0x0008, 0x1030, "LO", protocol)
        + elem(0x0010, 0x0010, "PN", patient_name)
        + elem(0x0010, 0x0020, "LO", b"ID\xff4711")
        + elem(0x0020, 0x000D, "UI", series.encode())
        + elem(0x0020, 0x000E, "UI", uid(seed + "/study").encode())
        + elem(0x0020, 0x0011, "IS", b"1")
        + elem(0x0020, 0x0013, "IS", b"1")
    )

    # Filler attributes: many small heap allocations, all freed when main()'s
    # DcmFileFormat is destroyed (i.e. before the oficonv cleanup runs).
    for i in range(attrs):
        tag_elem = 0x1000 + i
        if tag_elem > 0xEFFF:
            break
        body = (b"f%05d" % i).ljust(valsize, b".")[:valsize]
        ds += elem(0x0029, tag_elem, "LO", body)


    if pixlen:
        # 8-bit, 1 sample: pixlen == rows*cols; keep both dims inside US (<=65535)
        rows = 2048
        cols = pixlen // rows
        if cols > 65535:
            rows, cols = 4096, pixlen // 4096
        if cols > 65535:
            cols = 65535
        pixlen = rows * cols
        ds += (
            elem(0x0028, 0x0002, "US", struct.pack("<H", 1))
            + elem(0x0028, 0x0004, "CS", b"MONO2")
            + elem(0x0028, 0x0010, "US", struct.pack("<H", rows))
            + elem(0x0028, 0x0011, "US", struct.pack("<H", cols))
            + elem(0x0028, 0x0100, "US", struct.pack("<H", 8))
            + elem(0x0028, 0x0101, "US", struct.pack("<H", 8))
            + elem(0x0028, 0x0102, "US", struct.pack("<H", 7))
            + elem(0x0028, 0x0103, "US", struct.pack("<H", 0))
            + elem(0x7FE0, 0x0010, "OB", (pattern * (pixlen // len(pattern) + 1))[:pixlen])
        )
    return b"\x00" * 128 + b"DICM" + meta + ds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--charset", default="ISO_IR 100")
    ap.add_argument("--seed", default="x")
    ap.add_argument("--pixlen", type=int, default=0)
    ap.add_argument("--attrs", type=int, default=0)
    ap.add_argument("--pattern", default="00")
    ap.add_argument("--valsize", type=int, default=7)
    ap.add_argument("--sq", type=int, default=0, help=argparse.SUPPRESS)
    a = ap.parse_args()
    with open(a.out, "wb") as fp:
        fp.write(build(a.charset, a.seed, a.pixlen, a.attrs,
                       pattern=bytes.fromhex(a.pattern), valsize=a.valsize))
    print(a.out)


if __name__ == "__main__":
    main()
