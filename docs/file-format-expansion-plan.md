# Data Quality Agent: file-format expansion plan

Prepared October 25, 2026. **Implementation update:** CSV, TSV, XLSX, flat JSON, and JSONL/NDJSON ingestion are now implemented with local preview, worksheet selection, preserved originals, and integrity-bound import metadata. Outputs remain CSV plus audit/validation files. TSV/XLSX exports and phases C–E below remain proposals. The remainder of this document preserves the original design plan, including capabilities beyond the current release.

The recommended next release accepts **CSV, TSV, XLSX, flat JSON, and JSONL**, converts the selected table into a common internal representation, and uses the existing review workflow. Parquet and ODS come next. XML, uploaded SQLite databases, archives, and document extraction follow as separate, bounded additions.

“All formats” is a useful direction, but needs a published support matrix. A spreadsheet contains cells; a JSON file may contain nested objects; a scanned invoice contains pixels. Each needs a different way to identify records and retain their meaning. Supporting an extension also does not mean preserving every feature of that file when exporting.

## What the application already provides

The current engine accepts one UTF-8 CSV, including a BOM, up to **10 MiB and 100,000 data rows**. It retains fields as strings, preserves the original file, checks required values, exact duplicates, unique identifiers, explicit date formats, allowed categories, and spreadsheet-formula risks. Repair and export have separate approvals, and jobs retain names, progress, and local audit evidence.

The main coupling is in `dq_agent/engine.py`: ingestion, reload, staging, and export expect CSV, and validations use string operations. Changing the upload picker alone would not provide reliable support for other formats. The proposed work separates parsing and writing from the existing business rules and workflow.

Business scope also remains explicit: a newly supported file must have a suitable rule specification. Adding Excel support does not automatically create inventory, finance, healthcare, or other domain rules.

## Format choices and priorities

| Priority | Format | Proposed scope | Implementation choice and main qualification |
|---|---|---|---|
| 1 | CSV, TSV, delimiter-based TXT | One rectangular table; explicit delimiter, header row, and encoding when ambiguous | Extend the strict text adapter. Keep malformed rows and duplicate headers as errors; never silently skip them. TXT means delimited data, not arbitrary prose. |
| 2 | XLSX | One user-selected worksheet or range per job | Use `openpyxl` for workbook/cell inspection, then construct the common table. Show hidden sheets, merged cells, formulas, and header choices before import. Export a new data workbook; do not promise preservation of charts, macros, formatting, or all workbook features. [pandas Excel engines](https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.read_excel.html) |
| 3 | JSON / JSONL / NDJSON | Flat record objects; either an array of objects or one object per line | Use Python's JSON parser with explicit handling of numbers, duplicate object keys, and nulls. Initially reject nested arrays/objects with a clear explanation. [Python JSON decoding](https://docs.python.org/3.12/library/json.html) |
| 4 | Parquet | One local file containing flat scalar columns | Use PyArrow to inspect schema and read bounded batches/row groups. Preserve type metadata; nested structs/lists, directories of partitions, and remote storage are later scope. [Arrow Parquet files](https://arrow.apache.org/docs/python/parquet/parquet.html) |
| 5 | ODS; later XLS / XLSB | One selected sheet | ODS can use pandas' `odf` engine; older Excel formats need explicit optional engines such as `xlrd`, `pyxlsb`, or `python-calamine`. Add each only with representative fixtures. Macro-enabled XLSM remains deferred. [Supported Excel engines](https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.read_excel.html) |
| 6 | XML / nested JSON | User-selected record path with a reviewed mapping to columns | Introduce a mapping screen. Do not automatically explode arrays, combine unrelated records, or collapse names that become identical after flattening. Pandas provides controlled JSON normalization with record paths and depth limits. [JSON normalization](https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.json_normalize.html) |
| 7 | SQLite `.sqlite` / `.sqlite3` / verified `.db` | A local uploaded snapshot; one selected ordinary table | Read a private immutable copy with a read-only connection. Use application-generated queries over allowlisted table/column identifiers; no arbitrary SQL, extensions, remote database access, or writes to the uploaded database. [Python SQLite read-only connections](https://docs.python.org/3.12/library/sqlite3.html#how-to-work-with-sqlite-uris) |
| 8 | GZIP / ZIP | A container around an already-supported format | Start with one selected member and no nested archives or automatic table merging. Containers do not add support for otherwise unsupported contents. Bound expanded size and entry count, and prevent path traversal. [ZIP extraction limitations](https://docs.python.org/3.12/library/zipfile.html#decompression-pitfalls) |
| Separate extension | PDF / images / DOCX | Extract candidate tables, show the original evidence, and require extraction review | This is a document-extraction workflow before data-quality validation. Scans require OCR; text extraction alone does not reliably recover tables. Audio/video would require another transcription/extraction product scope. [pypdf extraction limits](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) |

Do not enable executable or object-deserialization uploads such as scripts or pickle files. Password-protected documents and workbooks with macros remain unsupported in the proposed first release.

## Architecture and user journey

The user journey becomes:

**Choose file → inspect format → select the table and import settings → confirm its preview → investigate quality issues → review repairs → approve staged copy → validate → approve export.**

The existing repair and export gates remain. The import screen resolves structural choices before the agent starts, such as which worksheet represents the dataset. A single unambiguous table can use visible defaults; uncertain interpretation needs a user choice.

| Component | Responsibility |
|---|---|
| Format registry | Match an allowed extension with its content signature and parser; produce a clear unsupported or mismatched-format message. |
| Parser adapters | Inspect available tables, read the selected table within limits, and return values, source locations, types, and warnings. Parsers receive local file handles, not user-supplied URLs. |
| Common table contract | Represent stable row/column IDs, values, null state, source types, and provenance consistently across formats. |
| Validation and repair engine | Evaluate the same declared rules and permitted operations against that contract, independent of the original file extension. |
| LangChain / LangGraph | Continue bounded investigation, clarification, persistent state, and guarded writes. The model receives sanitized counts and references; parsers and Python enforce correctness. |
| Export adapters | Write supported output formats to new files, reopen and verify them, and record serialization choices and hashes in the audit. |

A proposed adapter interface has `inspect(source)`, `read_table(selection, options, limits)`, and `write_table(table, output_options)`. Read support and write support are separate capabilities; an input adapter does not automatically qualify as an exporter.

Suggested future modules are `dq_agent/formats/`, a shared dataset/schema module, and an export registry. The current `create(csv_bytes, rules, name=...)` API remains a compatibility wrapper for old callers. New jobs use a versioned import manifest; old CSV jobs keep their existing interpretation, checkpoints, and approval bindings.

## Protecting the meaning of the data

**Keep the uploaded bytes unchanged.** Store the original file under an application-controlled name, retain its original filename only as metadata, and record its checksum. Store parsing choices and the normalized table separately. Do not turn an Excel upload into `source.csv` and discard the workbook.

The common table must not rely on `astype(str)` for every format. It needs to distinguish missing values from empty text, text identifiers from numbers, booleans from their spellings, decimal amounts from binary floats, and dates from timestamps with timezones. A versioned tagged JSONL representation plus a schema/provenance sidecar is a practical initial storage option; an Arrow representation can be evaluated for the typed-data phase. Both should implement the same logical contract.

For the first release, retain the original scalar/type information and derive a documented text view only where the existing customer rules need one. Any interpretation that could change meaning must appear in the import preview. For example:

- A text identifier `00123` stays text. An Excel numeric value `123` displayed with a `00000` format is flagged for an interpretation choice; the parser must not claim that the stored value contained leading zeros.
- A missing JSON key, JSON `null`, and an empty string remain distinguishable even if a required-field rule considers all three missing.
- Preserve decimal precision, large integers, and explicit timezone information. Reject unsupported mixed or nested types instead of silently coercing them.
- Keep original line, record, worksheet/cell, JSON path, or table/key references so a repair preview can point back to its source.
- Do not silently remove blank records, hidden rows, repeated headers, or merged-cell gaps. State the selected range and report structural exclusions.

For JSON, Python offers custom numeric parsing and object-pair hooks; the adapter should use them deliberately to detect duplicate keys and avoid unintended numeric conversion. [Python JSON decoder options](https://docs.python.org/3.12/library/json.html#json.load)

**Spreadsheet formulas need a separate policy from ordinary text.** `openpyxl` does not calculate formulas; cached results may reflect an earlier spreadsheet calculation. The first XLSX adapter should detect formula cells and require a values-only source or explicit handling before treating them as import data. Never execute macros or refresh external links. A new cleaned workbook contains the approved data table, not an implied faithful copy of every original workbook feature. [Formula behavior](https://openpyxl.readthedocs.io/en/stable/simple_formulae.html), [workbook loading and preservation limits](https://openpyxl.readthedocs.io/en/stable/tutorial.html#loading-from-a-file)

## Approvals, limits, and output behavior

Extend new-job repair approval to bind **original hash + import-manifest hash + normalized-table hash + rules hash + exact plan hash**. The manifest includes the parser/version, selected sheet/range/table/path, encoding, delimiter, header, and conversion settings. A changed selection or parser interpretation invalidates the preview and requires fresh approval.

Export approval additionally binds the chosen **output format and serialization settings**, alongside staged data, validation, and audit hashes. Reopen the serialized result and check row counts, values, and supported types before offering downloads. A successful in-memory validation is insufficient if writing the chosen format changes the data.

Keep CSV and the audit JSON/summary as the initial universal outputs. Add TSV and a new XLSX data workbook with the first expansion. Add JSON/JSONL and Parquet exports only with defined null/type policies and round-trip tests. Make any lossy conversion visible; do not label a CSV export as preserving the complete source workbook or database.

Retain the current **10 MiB upload and 100,000-row ceiling** initially. Add explicit limits for column count, total cells, decoded bytes, nesting, archive entries, and parser execution time. Proposed starting limits are 200 columns, 1 million selected cells, 50 MiB decoded data, and a 30-second parser budget, subject to measurement on the target computer. These are design defaults, not demonstrated performance claims. Parsing needs bounded iteration and, for heavier formats, a worker process whose execution can be stopped; a small compressed upload must not imply unlimited memory allocation.

XML needs hardened parsing with external resources and entity processing disabled, plus depth/size limits. Python's documentation recommends `defusedxml` for untrusted XML. Add this protection with the first XLSX adapter too: openpyxl specifically recommends it for XML expansion attacks. ZIP checks also apply to workbook containers; inspect members and enforce expanded-byte budgets before handing them to a parser. [Python XML guidance](https://docs.python.org/3.12/library/xml.html), [openpyxl security guidance](https://openpyxl.readthedocs.io/en/stable/#security), [ZIP resource limitations](https://docs.python.org/3.12/library/zipfile.html#decompression-pitfalls)

## Delivery phases and completion checks

| Phase | Deliverable | Completion condition |
|---|---|---|
| A — Common ingestion foundation | Adapter contracts, versioned manifests, stable source locations, and CSV compatibility | Existing CSV tests and saved-job resume/export tests still pass; no legacy job is silently reparsed. |
| B — Recommended next release | TSV/delimited text, XLSX, flat JSON/JSONL; import preview and table selection; CSV/TSV/XLSX output | The same repairable customer fixture produces equivalent reviewed results in each format; ambiguous structure pauses before repair. |
| C — Typed and alternative tables | Parquet and ODS; explicit null/type metadata; typed output where supported | Decimal, large-integer, boolean, null, date/timezone, and leading-zero fixtures survive the documented round trip. |
| D — Structured containers | Reviewed nested JSON/XML mappings, one SQLite table, and controlled compressed inputs | Mapping choices are hashed; malformed, oversized, unsafe, or unsupported structures fail with actionable messages. |
| E — Document extraction pilot | One narrow document class, such as a consistent invoice table | Extraction accuracy is measured against labeled examples, uncertain cells show source evidence, and user confirmation precedes quality repairs. |

Dependency changes should be optional and pinned to versions tested with the project's existing `pandas>=2.2,<3` range: `openpyxl` plus `defusedxml` for XLSX; `pyarrow` for Parquet; `odfpy` for ODS if using pandas' `odf` engine; reuse hardened XML parsing for the later XML adapter. JSON, CSV, ZIP, and SQLite have standard-library building blocks. Legacy Excel engines are later extras. No installation or version upgrade is part of this plan.

Every adapter needs fixtures for clean data, malformed/truncated input, duplicate/blank headers, encoding failures, empty records, ambiguous dates, missing facts, and boundary-size inputs. Add format-specific tests for multiple/hidden sheets, merged cells, formula caches, formatted identifiers, duplicate JSON keys, nested-array expansion, decimal precision, timezone retention, XML entities, ZIP traversal/expansion, and SQLite read-only behavior. Repeat approval-tampering, idempotency, crash/resume, and outbound-data privacy tests across the adapter boundary.

## Defaults for the next implementation discussion

Proceed with these proposed defaults when shaping the next build; they keep the expansion reviewable without requiring every future format decision immediately.

| Decision | Proposed default | When to revisit |
|---|---|---|
| Most valuable formats | CSV/TSV, XLSX, flat JSON/JSONL | If real files show Parquet or ODS is more common. |
| Unit of work | One selected table per named job | When cross-sheet/table joins become a concrete requirement. |
| Output | New cleaned table plus audit; CSV/TSV/XLSX first | When a consumer requires a typed JSON/Parquet output. |
| Workbook fidelity | Preserve the original; export a new data workbook | If retaining formulas, charts, styles, or macros becomes a separate requirement. |
| Character encoding | UTF-8/BOM by default; explicit alternatives after a preview | When a representative legacy file requires another encoding. |
| Dataset domain | Continue the customer import template and user-supplied rules | When another domain's fields and validation policies are defined. |
| PDFs and images | Separate extraction pilot after structured-file support | When document examples and accuracy requirements are available. |

The most useful inputs before implementation are representative files, the formats used most often, and the required output format. The recommended starting point remains **Phase A followed by Phase B**.
