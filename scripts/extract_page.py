"""Extract a page range from a PDF into a new PDF.

Usage:
    python scripts/extract_page.py x.pdf 2 4 [out.pdf]

Pages are 1-indexed and inclusive: `2 4` extracts pages 2,3,4 (a 3-page pdf).
"""

import argparse
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def main():
    parser = argparse.ArgumentParser(description="Extract a page range from a PDF")
    parser.add_argument("pdf", type=Path, help="source pdf")
    parser.add_argument("start", type=int, help="first page (1-indexed)")
    parser.add_argument("end", type=int, help="last page (1-indexed, inclusive)")
    parser.add_argument("out", nargs="?", type=Path, default=None, help="output pdf")
    args = parser.parse_args()

    if args.start < 1 or args.end < args.start:
        sys.exit("start/end must satisfy 1 <= start <= end")

    reader = PdfReader(str(args.pdf))
    total = len(reader.pages)
    if args.end > total:
        sys.exit(f"end page {args.end} exceeds pdf page count {total}")

    writer = PdfWriter()
    for i in range(args.start - 1, args.end):
        writer.add_page(reader.pages[i])

    out = args.out or args.pdf.with_name(f"{args.pdf.stem}_p{args.start}-{args.end}.pdf")
    with open(out, "wb") as f:
        writer.write(f)
    print(f"wrote {out} ({args.end - args.start + 1} pages, {out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()