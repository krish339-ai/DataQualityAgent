# Lumen Row — Customer Data Quality Agent

**Author: Krishna Kallamadi** · [Connect on LinkedIn](https://www.linkedin.com/in/krishna-kishore-kallamadi-a22b498/)

**Data quality. Made clear.**

A local Python application that turns a customer data table into a validated CSV import file. It identifies problems, proposes explicit repairs, asks for missing facts, pauses for approval, validates a separate repaired copy, and requests a second approval before export.

The first format expansion accepts **CSV, TSV, Excel XLSX, flat JSON, and JSON Lines (JSONL/NDJSON)**. Approved output remains CSV plus the audit and validation summary. The [file-format expansion plan](docs/file-format-expansion-plan.md) describes later formats and richer export options.

The application uses **LangGraph** for saved workflow progress and approval pauses, **LangChain** for the live model's read tools, **pandas** for deterministic data operations, and **Streamlit** for the interface. A model never executes code or writes customer data directly.

## Start here

Clone the repository first:

```shell
git clone https://github.com/krish339-ai/DataQualityAgent.git
cd DataQualityAgent
```

Use Python 3.11 or newer. The tested environment uses Python 3.12 on Windows. Run these commands in this project folder:

```powershell
.\scripts\bootstrap.ps1
.\scripts\start.ps1
```

Open the local address printed by Streamlit, normally `http://127.0.0.1:8501`. The app binds to the local computer only.

Lumen Row starts in **Dark** appearance. Use the **Appearance** switch at the top to choose **Dark** or **Light**. The selected appearance carries into the workspace, and switching appearance preserves the job and its progress.

The landing page pairs a rounded header with an illustrated data-review workshop and explains the product. It has no sidebar, upload controls, or data processing. Select **Open workspace** to reach the review hub. **Review my file** starts a guided upload; **Try a sample** starts a draft with fictional data. The top navigation provides **Workspace**, **Saved reviews**, **Settings**, and **Back to product**.

If `python` opens the Windows Store instead of running Python, pass a working interpreter explicitly:

```powershell
.\scripts\bootstrap.ps1 -PythonPath 'C:\path\to\python.exe'
```

Bootstrap creates an isolated `.venv`, installs the recorded dependencies, installs this package, and copies `.env.example` to `.env` only if that file does not exist. It uses a project-local temporary directory during setup; it does not change the global Python installation.

On macOS or Linux, create a Python 3.11+ virtual environment, install the dependencies, and start the app:

```shell
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e .
cp .env.example .env
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

The current release was tested on Windows; the equivalent macOS/Linux commands have not been verified on those operating systems.

Direct commands, without activating an environment:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m dq_agent demo --root .demo-data
.\.venv\Scripts\python.exe -m dq_agent evaluate --root .eval-data
```

The `demo` and `evaluate` commands use synthetic fixtures and scripted human decisions, including approvals. They are automated checks, not authorization to process or approve real customer data. Use the Streamlit review controls for your own CSV.

## Follow the samples through the app

In the workspace's **Try a sample** card, choose **Positive test** or **Negative test**. This opens the **File → Rules → Preview** setup; the **Sample scenario** selector in File lets you change the scenario:

| Scenario | File | Expected behavior |
| --- | --- | --- |
| **Positive test — rule-based repairs** | `samples/customers_positive.csv` | Eight records with an exact duplicate, date formats, and country aliases. The declared repairs produce seven records with zero blocking issues. All required customer IDs are supplied. |
| **Negative test — needs your knowledge** | `samples/customers_negative.csv` | Two records with an impossible February 30 date, unknown country `ZZ`, and a missing customer ID. The workflow pauses for clarification instead of guessing. |

1. Select **Open workspace** on the landing page. For the first run, open **Settings** and keep **Offline demonstration (no model calls)** selected under **Investigation mode for new jobs**. Return to **Workspace** and choose **Positive test**.
2. In File, select **Continue to rules**. Keep the included rules and enter an optional **Job name**, such as “October customer import,” then select **Continue to preview**. Review the table and conversion notes, then select **Create job and inspect data**. A blank name receives a unique automatic name such as “Customer review 001.” Only the final Create action starts the workflow and authorizes local storage of the file and progress.
3. Inspect the original records, detected issues, proposed operations, and before/after preview. Submit any edited plan for review. Saving a proposal does not approve a repair.
4. Approve the exact repair plan. Python writes a separate staged copy and checks every rule again. Any remaining blocking issue prevents export.
5. Confirm that the positive scenario has seven records and zero blocking issues, then explicitly approve export. Download the corrected CSV, audit JSON, and validation summary.
6. Return to **Workspace** and choose **Negative test** to practice clarification. Complete its setup and create the review. Supply facts you know or explicitly choose a row removal, then review the updated plan; cancel if you cannot resolve the records. The system must not invent a valid date, country, or ID.
7. Restart the app and open **Workspace** or **Saved reviews**. Under **Pick up where you left off**, use **Search saved reviews** and the **Review status** filters: **All reviews**, **Needs attention**, or **Completed**. Select **Continue review** for an unfinished job or **View results** for a completed one. For an exact-name lookup, open **Settings**, enter **Open by job name**, and select **Open by name**. Delete a job through its confirmation control when its locally stored files and history are no longer needed.

Before creating a job, **Back to file** and **Back to rules** let you revise the setup. **Back to workspace** keeps the unfinished draft in the current app session; **Continue draft** returns to it. Drafts are separate from saved jobs and have not started model investigation.

These two interactive scenarios are separate from the ten automated evaluation cases. The original `samples/customers.csv` remains for older examples and tests; it includes a missing ID, unlike the new positive fixture.

Job names are unique, with a maximum of 80 characters. Name lookup matches the full name without regard to capitalization. To rename an open job, expand **Manage this job**, edit **Rename job**, and select **Save name**. Existing jobs receive automatic names while retaining their data and approval checkpoints; older job IDs also continue to work in the name field. Renaming changes the display name and preserves the saved workflow.

To repeat a saved job, select **Reset** on its saved-review row or **Reset job** below its open-job heading. This opens a **new run** from that job's original file, saved import settings, and rules, using its original investigation provider. The previous run, history, and results remain saved. The new run inherits no approvals; any repairs and export require fresh decisions. Reset reuses the original input, not the corrected output: an older completed job whose source contained a missing ID can therefore ask for clarification again. To exercise the fully rule-based path, create a job from the new positive scenario.

Equivalent positive-test files in TSV, XLSX, JSON, JSONL, and NDJSON are available in `samples/formats/`. Choose **Start a review** in the **Review my file** card to upload one, select a worksheet when needed, and continue through Rules and Preview. Previewing a file does not create a job or call the model.

The UI labels records from 1. Engine repair plans use zero-based row positions, so engine row `4` means UI record 5. Positions always refer to the original upload, even when other rows will be removed.

The correction form follows the uploaded rules. Date fields use a calendar and show the replacement in the declared output format. Category fields offer only their exact allowed values; other fields use text so identifiers such as `00102` keep their leading zeros. Invalid dates and unknown categories start without a selection. Required and unique-field guidance helps explain what a correction needs to satisfy, while local validation still checks the whole proposal.

Expand **Optional: Fix individual fields** to use the guided correction form. Under **Fix a field**, use **Choose a field to fix**, select **New date** or enter **New value**, and complete **Why is this correct?** Select **Add correction to draft** (or **Update correction in draft**). Review the before/after preview and remaining issue count, then submit the revised plan. Unadded form changes must be added or discarded before submission or approval. Draft edits stay in the current browser session when switching appearance or returning to the workspace; submitting the plan saves the proposal durably. **Final corrections — editable draft** is always visible for direct edits and explicit record removals. Neither editing method approves a write or export.

## Offline and live modes

**Offline** runs the real LangGraph workflow, SQLite persistence, engine, previews, and approval gates. It uses deterministic proposals and makes no language-model requests. This is useful for learning and repeatable validation, but it is not evidence of live model performance.

For model-led investigation, fill in your own `.env` locally, then choose the matching provider in the app:

```dotenv
DQ_PROVIDER=nebius
NEBIUS_API_KEY=your-local-key
NEBIUS_MODEL=a-tool-calling-model-available-in-your-account
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
```

Alternatively set `DQ_PROVIDER=fireworks`, `FIREWORKS_API_KEY`, and `FIREWORKS_MODEL`. Model identifiers are account/provider specific; no paid endpoint is assumed. Never paste credentials into source files, screenshots, or project submissions. `.env` is excluded from Git.

After saving or changing `.env`, restart the Streamlit server so the Python process loads the new settings. Stop the existing server with **Ctrl+C** in its terminal, then run `.\scripts\start.ps1` again. Refresh the app in your browser; a browser refresh alone does not replace the server's loaded environment.

In **Settings**, select **Nebius Token Factory** under **Investigation mode for new jobs**. Return to **Workspace**, choose **Positive test**, and create a **new job** after File, Rules, and Preview to test the live model. Existing jobs retain the provider mode they were created with: reopening or resetting an offline job does not convert it to Nebius when you change Settings or `.env`.

The initial model investigation chooses read tools and selects from locally generated, rule-backed repair candidates. It receives counts and opaque candidate references, not customer values, uploaded filenames, or your replacement values. Python still enforces all rule checks and approvals. Network calls use bounded retries; exhausted or invalid responses pause the job without applying changes. Live provider calls require valid credentials and are not validated by offline tests. The separate, optional value-suggestion feature described below can share selected values only after an explicit payload preview and consent.

A failed model investigation is separate from problems in the data. The job still shows verified local rule findings; if validation cannot be verified, the issue count is shown as unavailable rather than zero. For an eligible investigation failure, select **Continue with manual corrections** to enter known corrections in the same saved job without retrying or calling the model. Submit the revised plan for review, then complete the separate repair and export approvals. The original provider mode and failed investigation history remain recorded. Eligible older jobs stopped during investigation can use this path too; it is unavailable after a write or when the saved inputs cannot be verified.

**Prepare AI-assisted draft** prepares rule-backed repairs and possible corrected values in one action. All affected fields are included automatically; there is no field-selection step. For a live job, inspect **Preview data shared with AI** and authorize that exact request before preparing. Only affected values, field names, issue types, and relevant rules are shared; unrelated fields and unsaved edits are excluded. Offline jobs use local rules without calling a model. Existing edits are preserved, and preparing a draft does not submit or approve repairs.

The compact **AI-proposed fixes** table sits immediately above **Final corrections — editable draft**. It shows each affected record and field, current and proposed values, status, and explanation. Choose **Add available suggestions to draft** to copy usable candidates together, then edit the final table and submit it for review. Unknown facts remain blank and marked **Needs your input**. The model may suggest `2026-02-28` for February 30, but it cannot identify a country from `ZZ` or recover a missing customer ID. Passing rules does not establish factual accuracy. Provider failure leaves manual correction available, and both repair and export approvals remain separate. Each request needs fresh consent. Requests currently cover up to 20 affected cells, with an explicit notice if additional cells need manual review.

## Scope and rules

Choose **Review my file → Start a review** for CSV, TSV, XLSX, JSON, JSONL, or NDJSON. Text files use UTF-8 (including a BOM). Excel imports one selected worksheet; JSON accepts a flat array of record objects, and JSON Lines accepts one flat record object per line. Nested JSON, workbook formulas, merged cells, password-protected workbooks, and macro-enabled Excel files are outside this release.

The local import preview shows the chosen table and conversion notes before a job begins. Values use a text view for the existing customer rules, while the unchanged original file and its import manifest preserve source types and locations. JSON null, a missing property, and empty text can all appear blank in the preview; their original distinctions remain in the manifest. Text identifiers such as `001` retain their leading zeros. A numeric Excel cell whose formatting adds zeros needs an explicit source correction instead of an inferred identifier.

Uploads are limited to **10 MiB, 100,000 data rows, 200 columns, and 1 million cells**. The parsers also bound decoded or expanded content. Approved downloads are a new **CSV**, audit JSON, and validation summary; they do not reproduce workbook styling, multiple worksheets, or typed JSON output. The original uploaded file remains available from the job.

Validation supports required fields, exact duplicate rows, configured unique fields, explicitly declared date formats, and allowed categories with explicit aliases. Type-distinct imported values are not automatically merged just because their text view matches. Conflicting identities need a human decision; there is no fuzzy merging or guessing.

Use `samples/import_rules.json` as a template:

```json
{
  "required_columns": ["customer_id", "name", "signup_date", "country"],
  "unique_columns": ["customer_id"],
  "date_formats": {
    "signup_date": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}
  },
  "categories": {
    "country": {"allowed": ["US", "CA", "GB"], "aliases": {"us": "US", "Canada": "CA", "uk": "GB"}}
  }
}
```

Here `%m/%d/%Y` means month/day/four-digit year. Declare the actual source convention: `03/04/2026` cannot be interpreted safely without one. Alias targets must already be allowed values. Missing required fields, conflicting constraints, invalid dates, and unknown categories are surfaced for correction. Spreadsheet-formula-like content is blocked for export rather than silently rewritten. Passing these rules proves conformance to the specification, not the truth of every customer fact.

## How the parts fit together

```text
File → Rules → Preview
        |
Create job and inspect data
        |
Profile and validate with Python
        |
Investigate with read tools / deterministic offline planner
        |
Clarify missing facts and preview repairs
        |
PAUSE: human approves exact repair plan
        |
Write a separate staged copy and revalidate
        |
PAUSE: human approves validated export
        |
Corrected CSV + audit JSON + summary

SQLite checkpoints preserve progress across pauses and restarts.
Source/rule/plan hashes and an operation ledger guard write approvals.
```

| File | Responsibility |
| --- | --- |
| `app.py` | Uploads, local previews, user decisions, resume controls, downloads. |
| `dq_agent/schemas.py` | Accepted import-rule and repair-operation shapes. |
| `dq_agent/imports.py` | Bounded file readers, worksheet inspection, text previews, and source-type provenance. |
| `dq_agent/engine.py` | Profiling, validation, previews, preserved originals, guarded writes, audit artifacts. |
| `dq_agent/reasoning.py` | Four LangChain read tools, model configuration, bounded tool loop. |
| `dq_agent/workflow.py` | LangGraph nodes, branches, interrupts, and SQLite checkpoints. |
| `dq_agent/job_names.py` | Unique saved-job names, name lookup, renaming, and names for existing jobs. |
| `dq_agent/telemetry.py` | Optional aggregate LangSmith trace summaries. |
| `assets/lumenrow-hero-light.png`, `assets/lumenrow-hero-dark.png` | Original generated workshop artwork for the light and dark landing views. |
| `samples/` | Fictional customer CSV and example import specification. |
| `tests/` | Correctness, approval, persistence, failure, and privacy checks. |
| `docs/learning-guide.md` | Plain-language explanation of each build stage. |
| `docs/Lumen-Row-Project-Documentation.docx` | Editable project report with primer, framework, architecture, examples, prompts, iterations, and learnings. |
| `samples/practice/` | Additional six-record practice file, matching rules, and known fixture answers. |

The landing page's visual direction takes inspiration from [Etail landing page web design 3D animation by Alex Bender for FANCY](https://dribbble.com/shots/25571331-Etail-landing-page-web-design-3D-animation). Lumen Row's light and dark workshop scenes were created with the built-in image generator; the reference artwork is not included. The original PNGs remain unchanged.

A CSS animation layered over the artwork shows uneven incoming record cards, a scanner pulse, and aligned outgoing cards with checkmarks. Use **Pause animation** or **Resume animation** to control the motion. When the operating system or browser requests reduced motion, the control shows **Motion reduced**. This is a visual demonstration of the workflow; it does not run a data job or process customer records.

## Local data and tracing

Jobs normally live under `.data` (override with `DQ_DATA_DIR`); CLI demos/evaluations use the roots shown above. Jobs retain original data, rules, intermediate files, final outputs, and saved workflow state until explicitly deleted. The audit contains local before/after references and values. Do not commit these folders or real customer data. This first version is for a trusted local user; it is not a multi-user service with authentication.

Automatic global LangSmith tracing is disabled because raw graph state can contain customer data. Optional tracing uses `DQ_LANGSMITH_TRACING=true` with `LANGSMITH_API_KEY` and sends only aggregate mode, issue-count, and step-count information. If tracing fails, the local workflow continues and its status remains visible. This is deliberately less detailed than a full prompt/state trace.

## Validation and project handoff

The ten-scenario evaluation covers clean data, duplicate removal, category aliases, date conversions, a user-provided missing value, and mixed cases. It compares the actual output to known expected records and records timings. Dedicated tests check rejected/stale approvals, source preservation, restart recovery, malformed inputs, and bounded model failures. Read the current test/evaluation output before making performance claims. The design's 9/10 within five minutes target includes scripted human decisions; it is not a benchmark of real user deliberation or live-model accuracy.

The [project documentation](docs/Lumen-Row-Project-Documentation.docx) includes the primer, framework, architecture, datasets, coding prompts, iterations, learnings, and a five-minute demo outline. A [PDF copy](docs/Lumen-Row-Project-Documentation.pdf) is available for reading. Upload the editable document to Google Drive and open it with Google Docs; add the shared document URL and your Loom recording URL when ready. The repository is https://github.com/krish339-ai/DataQualityAgent. No form submission is made by setup.

## Fresh Nebius evaluation

A new 14-case study uses the configured `Qwen/Qwen3.5-397B-A17B` model through the actual LangChain/LangGraph workflow. The fictional records and gold answers were fixed before the calls. This is separate from the ten offline scenarios, parser tests, and any research-paper or CMS evaluation.

| Cohort | Cases | Missed issues | Incorrect values proposed | Unnecessary refusals |
| --- | ---: | ---: | --- | --- |
| Declared rules | 4 | 0/7 | All 7 expected rule-backed changes selected | Not applicable |
| Semantic repairs | 4 | 0/7 | 0/7 raw and delivered values | 0/7 answerable cells |
| Exceptions and missing knowledge | 4 | 0/7 | 1/1 date hypothesis disagreed with the hidden source fact | Not applicable; 6 necessary abstentions |
| Full-source coverage | 2 | 2/2 | No replacement values requested | Not applicable |

The issue detector is Python, so issue recall is **system validation coverage**, not LLM detection accuracy. Raw and guarded suggestions are scored separately. The date hypothesis (`2027-02-28`) passed format checks but the fixture ledger specified `2027-03-01`; the evaluator counted that factual mismatch rather than hiding it behind an “unverified” label. The seven answerable semantic corrections were correct, and every one of the fourteen requested value items received a response.

The two coverage probes contain a conditional signup-date restriction and an email syntax requirement that the current rules cannot express. Both reached repair approval despite missing those full-source requirements. The evaluator withheld approval. These remain **known limitations**, not fixed validation features. Complete business-policy coverage requires an explicit source-to-rules review and future schema support.

The evaluator completed eleven repairable fixtures using known reviewer facts, exact expected outputs and both scripted approvals. One excluded-country fixture correctly stayed unresolved. These are human-assisted workflow outcomes, not autonomous factual accuracy. No production prompt or guardrail was changed to improve the measured results.

The [initial results](docs/evaluations/nebius-fresh-v1.json) retain all responses, tool calls, request payloads, token usage and provenance hashes. The final case hit the evaluator's own 75-request ceiling; this is a local budget stop, not a Nebius refusal or provider outage. Its [targeted retry](docs/evaluations/nebius-coverage-retry-v1.json) is reported separately and does not replace the original. The [protocol](evaluations/nebius_fresh_v1/protocol.json) and [labeled corpus](evaluations/nebius_fresh_v1/cases.json) define the denominators and expected answers.

```shell
# Local fixture checks; no model requests
python scripts/evaluate_nebius.py

# Paid live requests on the committed fictional fixtures only
python scripts/evaluate_nebius.py --live --consent-synthetic

# A separately recorded targeted run
python scripts/evaluate_nebius.py --live --consent-synthetic --only coverage_missing_email_constraint

# Offline tests for the evaluator's scoring, privacy and request limit
python -m pytest tests/test_live_evaluation_scoring.py -q
```

Each run writes to a new ignored folder under `tmp/nebius-evaluation/`. Six evaluator tests passed; the earlier 422-test release suite and 10/10 offline results remain separate evidence. One initial pass on fourteen deliberately constructed cases does not establish general reliability or a stable refusal rate. Next steps are independently reviewed datasets, repeated live runs, and implementation of the missing rule types.

## About the author

I'm Krishna Kallamadi, a data enthusiast with 16+ years of experience with various on-prem and cloud databases across healthcare and insurance. I began my career in 2009 and have spent more than a decade supporting mission-critical healthcare databases. My work spans database administration, performance tuning, data analytics, data migration, data engineering, data architecture, cloud engineering, and AI engineering, with a focus on automation and data security.

I've expanded into AI, earning the AWS Certified AI Practitioner certification and building AI-powered database intelligence tools. I'm working toward a future as an AI Data Architect, bringing together database expertise, data engineering, and a security-first approach to intelligent, autonomous platforms.

[Connect on LinkedIn](https://www.linkedin.com/in/krishna-kishore-kallamadi-a22b498/)
