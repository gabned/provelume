# Bounded table and archive profiles

Perceptio adds exactly three local, versioned higher-level profiles: UTF-8/UTF-8-BOM CSV cells,
XLSX sheets and cached cells, and ZIP members. Exact Originals remain authoritative. Profiles are
derived, checksum-bound, removable and rebuildable; they never change a source or canonical record.

## Support matrix

| Profile | Parser | Higher-level evidence | Closed boundary |
| --- | --- | --- | --- |
| `perceptio-csv-cell-v1` | Python 3.12 `csv`, PSF-2.0 | delimiter, displayed values and exact row/column/cell anchors | UTF-8 only; 16 MiB, 5,000 rows, 200 columns and 100,000 cells |
| `perceptio-xlsx-sheet-cell-v1` | Python 3.12 `zipfile` + `xml.etree.ElementTree`, PSF-2.0 | workbook-order sheets, displayed cached values, formula-presence evidence and exact sheet/cell anchors | 64 MiB input; bounded package/XML/sheets/rows/cells; no external relationship, macro or embedded active content |
| `perceptio-zip-member-v1` | Python 3.12 `zipfile`, PSF-2.0 | normalized path, SHA-256, fixed media type, sizes, ratio and exact member anchor | bounded members/bytes/ratio/time; no encryption, symlink, unsafe path, nested expansion or host extraction |

Unsupported encodings and formula-only XLSX cells fail the requested derived operation. Unsafe,
encrypted, corrupt, duplicate/colliding or excessive package members also fail closed. Preservation
of an already acquired Original is independent from the profile result.

## Local operation

The service and CLI expose explicit queue, run, cancel, retry, remove and rebuild actions. For
example:

```console
provelume file-family-queue INSTANCE VERSION_ID perceptio-csv-cell-v1
provelume file-family-run INSTANCE JOB_ID
provelume file-family-profiles INSTANCE
```

The HTTP API and `/file-families` Browser page are read-only. Each displayed cell or archive member
links to its full typed anchor. Values are auto-escaped and JSON outputs are served with `nosniff`
and a restrictive no-script/no-object content policy. Formula text, macros, scripts, HTML and attachments are
never executed. Parsing uses no network, plugin discovery, runtime download or remote inference.

DOCX/presentation, TSV/ODS/JSONL/Parquet, notebooks, EML/PIM, HTML/MHTML/WARC/WACZ, TAR/GZ/7Z,
geospatial and signed-administrative higher-level profiles remain outside S06 and keep their
existing truthful support or later roadmap destination.
