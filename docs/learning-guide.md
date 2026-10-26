# Building Lumen Row: a guided walkthrough

**Data quality. Made clear.** Lumen Row is our local Customer Data Quality Agent.

This guide follows the approved design. The aim is to learn what each part does and why it exists, then follow one CSV from upload to an approved export. You can keep the app in offline mode while learning the workflow; the same approval and persistence code is used by the live model modes.

## 1. Create a separate Python environment

A project depends on reusable libraries. For example, pandas reads data tables and LangGraph runs the workflow. A virtual environment is a folder containing this project's Python packages, which keeps their versions separate from other projects.

We use `.venv` and record the installed versions in `requirements-lock.txt`. `requirements.txt` contains the broader dependency ranges maintained by a developer. The lock file helps another person reproduce the tested environment. `scripts/bootstrap.ps1` prepares the environment; `scripts/start.ps1` starts the app using its interpreter.

**Try it:** run `.\.venv\Scripts\python.exe --version`. That command deliberately selects the project's Python instead of relying on whatever `python` means on the machine.

## 2. Define what a valid import means

“Clean data” is too vague for a program. We first write explicit requirements: a customer ID cannot be empty, dates must use a declared format, and country values must belong to a fixed list.

The JSON import specification stores these rules. Pydantic checks that the rule document itself is well formed before we trust it. For instance, an alias cannot map to a country outside the allowed list. This catches contradictory instructions before data is changed.

**Try it:** read `samples/import_rules.json`. Explain in your own words what the `country` aliases permit and what they do not permit. An alias is permission to convert one known spelling to another; it is not permission to guess a new value.

## 3. Build a reliable data engine

The engine checks a text table. CSV fields are already text; the import adapters also prepare TSV, Excel XLSX, flat JSON, and JSON Lines for the same rules. A text ID such as `001` stays text. The original upload and an import manifest preserve the source types and locations, including distinctions that a plain text table cannot express, such as a missing JSON property versus JSON null.

Before starting an uploaded-file job, the app shows a local preview. For an Excel workbook with several worksheets, you must choose one. The parser rejects unsupported structures such as nested JSON, formulas, and merged spreadsheet cells instead of guessing what the intended table means. Previewing does not call a model or create a saved job. The explicit **Create job and inspect data** action starts the workflow.

All supported inputs currently produce a reviewed CSV plus audit files. The original workbook or JSON remains preserved, but the export does not recreate workbook formatting or typed JSON. The manifest, original upload, normalized table, rules, and plan are checked for changes before an approved write.

A repair operation says exactly what will change: set a field on a specific original row, or remove that row. Date conversions and category aliases come from declared rules. A missing factual value must come from the user. No model-generated Python runs in the engine.

**Try it:** in the workspace's **Try a sample** card, choose **Positive test**. The File step displays **Sample scenario → Positive test — rule-based repairs**. Inspect `samples/customers_positive.csv` and predict the repairs: its eight rows should become seven after the approved duplicate removal, date conversions, and country mappings, with zero blocking issues. Complete Rules and Preview before creating the job. Later, return to Workspace and choose **Negative test** (`samples/customers_negative.csv`): its two rows contain an impossible February 30 date, country `ZZ`, and a missing ID. These need clarification. The original `samples/customers.csv` remains for older examples and tests and still contains a missing ID.

## 4. Preview changes before applying them

A preview applies the proposed operations to an in-memory copy. It shows a before/after difference and calculates whether the proposed result would pass validation. The original file stays unchanged.

We also calculate hashes: short fingerprints of the source, rules, and plan. Approval is tied to those fingerprints. If a proposal or file changes after review, the old approval no longer matches. This protects the meaning of “approve these exact changes.”

**Try it:** alter a proposed repair in the interface. Submit it for a fresh preview and inspect the projected findings before approving it.

## 5. Give the model bounded tools through LangChain

A tool is an ordinary Python function with a name, description, and structured inputs/outputs that a model can call. The live model has four read tools: profile the dataset, inspect rule counts, inspect validation summaries, and inspect candidate repairs.

During the initial investigation, the model sees sanitized summaries and candidate references. It can select an appropriate candidate set or continue inspecting. This path cannot supply arbitrary customer values, execute code, or call the two write tools. The deterministic engine has already checked how each candidate was derived. Optional value suggestions use a separate, explicitly consented request and still cannot write data.

Offline mode uses the deterministic candidates directly. Live Nebius or Fireworks mode adds a genuine LangChain tool-calling loop. Keep this distinction clear when demonstrating the project: offline mode demonstrates workflow correctness, while live mode demonstrates model-led tool use.

**Try it:** inspect `dq_agent/reasoning.py` and locate the four read-tool functions. Then locate the decision limit and the validation of the model's final selection.

## 6. Connect the steps with LangGraph

Think of the workflow as a map. Each node performs one job. An edge says where to go next. A conditional edge checks the result: a clean file can proceed toward export review, while unresolved issues must go back to the user.

The shared state is the job's saved notebook. It holds references, findings, proposals, decisions, status, and errors. SQLite checkpoints save this state as the graph runs. You find the job by its readable name; an internal job ID keeps its saved workflow stable when you rename it. Existing jobs receive automatic names without changing their data or approval checkpoints.

**Try it:** read the node and edge definitions in `dq_agent/workflow.py`, then compare them with the architecture diagram in the approved HTML document.

## 7. Pause for a real human decision

A LangGraph interrupt pauses execution and returns control to the interface. The job can remain paused across app restarts. Resuming supplies an explicit decision; waiting or closing the browser is not approval.

The first approval permits an exact repair plan to be written to a separate staged file. The second approval permits export after validation. A user can revise or cancel rather than approve. A plan that still violates blocking rules cannot become an import-ready export.

The guided correction form reads the same JSON rules as the validator. A field with a date rule gets a calendar; a field with allowed categories gets a dropdown containing those exact values. Other fields remain text, which preserves leading zeros in IDs. Required and uniqueness hints come from the rules too. This works for any configured field name, rather than treating `signup_date` or `country` as special cases.

An impossible or missing date starts with no selected day. Choosing February 28, 2026 produces `2026-02-28` when that is the declared output format; the form shows the exact text before adding it. An unknown category such as `ZZ` likewise starts without a selected country. The controls help you enter a valid value, but they cannot establish which date or country belongs to a real customer.

Expand **Optional: Fix individual fields** to use the guided correction form. Under **Fix a field**, select **Choose a field to fix**, supply **New date** or **New value**, and explain **Why is this correct?** Use **Add correction to draft**, then inspect the before/after preview and remaining issues before submitting the revised plan. Existing corrections offer **Update correction in draft** and **Remove draft correction**. A form entry that has not been added must be added or discarded before approval. Draft entries survive theme changes and navigation within the current browser session; submission saves the proposal across restarts. **Final corrections — editable draft** is always visible for direct edits and explicit record removals. Both paths retain the separate repair and export approvals.

**Prepare AI-assisted draft** prepares rule-backed repairs and possible corrected values in one action. All affected fields are included automatically; there is no field-selection step. For a live job, inspect **Preview data shared with AI** and authorize that exact request before preparing. Only affected values, field names, issue types, and relevant rules are shared; unrelated fields and unsaved edits are excluded. Offline jobs use local rules without calling a model. Existing edits are preserved, and preparing a draft does not submit or approve repairs.

For example, `10/05/2026` can become `2026-10-05` when the rules declare those input and output formats. But `02/30/2026` does not identify an intended real date, `ZZ` does not identify a country, and a missing customer ID cannot safely be assigned the next number. Those cases need a trusted source or a person who knows the correct facts. Passing a format check is different from establishing factual accuracy.

The compact **AI-proposed fixes** table sits immediately above **Final corrections — editable draft**. It shows each affected record and field, current and proposed values, status, and explanation. Choose **Add available suggestions to draft** to copy usable candidates together, then edit the final table and submit it for review. Unknown facts remain blank and marked **Needs your input**. Impossible or ambiguous dates remain **Needs your input**: confirm the intended date from a trusted source, then use the calendar or final corrections table. Only conversions of real dates using declared formats are suggested. The agent also cannot identify a country from `ZZ`, recover a missing customer ID, or infer an email address from syntax rules. Passing rules does not establish factual accuracy. Provider failure leaves manual correction available, and both repair and export approvals remain separate. Each request needs fresh consent. Requests currently cover up to 20 affected cells, with an explicit notice if additional cells need manual review.

**Try it:** create a job named “October customer import” from the positive sample, stop at repair review, restart the app, and reopen it from **Saved reviews** using **Continue review**. Confirm that it still awaits your decision and has not silently applied repairs. Create a separate negative-sample job to see the earlier clarification pause when the system needs facts from you.

## 8. Write once and check again

Writing is more sensitive than reading. The engine verifies the approved hashes before writing, uses a new file instead of overwriting the original, and records the operation. If execution is interrupted, the saved operation and file hashes allow the app to reconcile what happened when it resumes.

The repaired file is validated independently. A proposal that looked sensible is not enough; the output has to pass the rules. The audit records what changed and why, and the summary distinguishes conformance to configured rules from factual correctness.

**Try it:** approve the positive sample's repairs, confirm seven records and zero blocking issues in the staged validation result, then approve export. Compare the downloaded CSV with the original and inspect the audit JSON.

## 9. Add the interface without hiding the workflow

Streamlit turns Python code into a small local web app. The interface gathers files and decisions and displays results; it delegates the actual work to the engine and workflow modules.

Lumen Row starts in **Dark** appearance. The **Appearance** switch at the top lets you choose **Dark** or **Light**. Your chosen appearance carries into the workspace without changing your job or saved progress.

The landing page uses a rounded header and an illustrated data-review workshop to explain the product. The original generated light and dark PNGs remain unchanged. A CSS layer animates uneven incoming record cards, a scanner pulse, and aligned outgoing cards with checkmarks. **Pause animation** and **Resume animation** control the movement; **Motion reduced** appears when the operating system or browser requests reduced motion. This is a visual demonstration, not a running data job. The visual reference and artwork files are credited in the README.

The landing page has no sidebar, upload controls, or data processing. Select **Open workspace** to reach the review hub. **Review my file → Start a review** begins an upload draft; **Try a sample → Positive test** or **Negative test** begins a fictional-data draft. The top navigation provides **Workspace**, **Saved reviews**, **Settings**, and **Back to product**. This keeps learning about the product separate from working on a file.

Setup has three steps: **File**, **Rules**, and **Preview**. Choose the file or sample and worksheet first, then select **Continue to rules**. Choose included or uploaded rules and an optional **Job name**, then select **Continue to preview**. Review the table, conversion notes, rules, and investigation mode before selecting **Create job and inspect data**. The earlier steps run locally without a model call or saved job. You can revise them with **Back to file** or **Back to rules**, or use **Back to workspace** and **Continue draft** to return to the unfinished draft within the current app session.

This separation makes the program easier to understand and test. A UI redesign should not alter the rule that writes need approval. The same workflow can also run under the command-line demonstration and tests.

The optional **Job name** field in Rules lets you choose a unique name of up to 80 characters. A blank name receives an automatic name such as “Customer review 001.” In Workspace or **Saved reviews**, use **Search saved reviews** and the **All reviews**, **Needs attention**, or **Completed** status filters. Open an unfinished job with **Continue review** or a completed one with **View results**. In **Settings**, you can also enter a full name in **Open by job name** and press **Open by name**; capitalization does not matter, and older job IDs still work there. Settings also contains **Investigation mode for new jobs**; saved reviews and resets retain their original mode.

**Try it:** open a saved job, expand **Manage this job**, change **Rename job**, and press **Save name**. Reopen it using its new name and confirm that its progress remains intact. Explain what each approval button authorizes before pressing it.

To repeat the exercise, select **Reset** on a saved-review row or **Reset job** below the active job heading. It opens a new run from the saved job's original file, saved import settings, and rules, using the same investigation provider. The earlier run and results remain available, and approvals must be given again. It does not restart from the corrected output: an older job whose original file had a missing ID will still need that clarification. Create a job from the new positive scenario when you want a repeatable test with all required facts already supplied.

## 10. Handle failures deliberately

Bad inputs should produce an actionable message, not a guessed repair. Temporary model failures receive limited retries. Invalid model responses receive a limited correction opportunity. Repeated investigation must stop instead of looping indefinitely.

A model failure does not mean the file has no issues: Python's local checks run independently, and the interface shows their verified findings. An unavailable count is never displayed as zero. When a job stops during investigation, **Continue with manual corrections** appears if its saved inputs are intact and no write has happened. This works for eligible earlier failed jobs too. It opens the correction editor in the same job without another model request and preserves the original provider mode and failure history. Enter corrections you know, choose **Submit revised plan for review**, then approve the exact repairs and export separately. Manual entry does not bypass either approval.

Trace logging is optional and separate from raw customer state. Only aggregate summaries can be sent to LangSmith. A tracing failure must not change the result or grant approval.

**Try it:** provide an invalid JSON rule document, cancel a review, or select a live provider without configuring credentials. Observe that the failure is visible and no unapproved output is produced.

## 11. Test outcomes that matter

Tests ask meaningful questions: Was the original preserved? Were only approved changes applied? Did a rejected or stale approval block the write? Can a job resume after restarting? Does a missing fact require the user? Are initial investigation messages free of customer values? Does optional value assistance send exactly the selected, previewed content, only after consent, and keep every suggestion subject to review?

The ten-case evaluation uses synthetic files with known expected outputs. Scripted decisions make it repeatable. Timing these scenarios evaluates program execution with supplied decisions, not how quickly a real analyst thinks or how well a live model performs.

**Try it:** run `.\.venv\Scripts\python.exe -m pytest` and `.\.venv\Scripts\python.exe -m dq_agent evaluate --root .eval-data`. Read failures before changing expectations; a failing test may reveal a real requirement that the implementation missed.

## 12. Demonstrate and explain the completed workflow

For a short project video, use the positive scenario to show the repair preview, both approvals, successful validation, and saved progress. Use the negative scenario to demonstrate that missing or invalid facts trigger clarification. Reset a saved job to show a fresh run with the earlier history preserved. Mention the mode you ran and any live provider limitations accurately.

Explain the responsibilities in one sentence each: Python enforces data rules, LangChain connects model and read tools, LangGraph controls decisions and pauses, SQLite preserves progress, and Streamlit lets the analyst review and approve. These pieces together produce an auditable result rather than merely a plausible chat response.

## Check the complete policy

Use `email_columns` to opt into email syntax checks and `conditional_dates` for date bounds that apply to matching records. The new policy sample and rules in `samples/` produce three blockers. The GB minimum is inclusive: January 1, 2027 passes; December 31, 2026 does not. A true but ineligible date must not be moved forward merely to qualify. Confirm the fact or resolve the intake decision. Existing saved jobs retain their original rules, including on reset; use a new job to apply new policies. See the README for the JSON contract and email syntax limits.
