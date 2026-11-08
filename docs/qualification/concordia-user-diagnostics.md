# Concordia: diagnostics for the maintainer's post-release checks

The maintainer's manual production-PC checks are deferred until the completed
official 0.15 release. No intermediate installation is requested. Automatic
source/package/CI checks retain their own requirements; a deferred manual row
remains NOT_RUN and does not erase an earlier automatic failure.

The candidate already contains these local diagnostic paths:

| Where | Available observations |
| --- | --- |
| Panel → Startup details | Last startup attempt's phases, closed error codes, elapsed milliseconds and observed exit codes. Available even when the service cannot start. |
| Panel → Startup details → Copy diagnostics | Structured JSON of that same reviewed trace and embedded build identity. The trace is scrollable; copying starts no new check and makes no network request. |
| Installed launcher `--diagnostics-file <selected-file>` | General shell/build/settings diagnostics. A newly launched process does not recover a previous launcher's in-memory startup trace. |
| Management → Maintenance → Diagnostics | Existing reviewed, content-free ZIP export of build/resources/scheduler/maintenance/operation-summary observations to an explicitly selected local destination. |
| AI model progress / operation details | Existing closed native stages, error codes and retained attempt outcomes. These are separate from the maintenance bundle's status summaries. |

If startup fails after installing the official release, keep the Panel open,
open Startup details and choose Copy diagnostics. Paste the JSON into a local
file or the support conversation. No system Python or source checkout is needed.
The copied report belongs to the attempt observed when the dialog opened; a
subsequent startup cannot silently replace its contents. The clipboard is changed
only by the explicit copy action. If it is unavailable, the trace remains readable.

The trace contains at most the existing last 32 events and labels that coverage as
a bounded tail. It contains no Instance/document path, document content, key,
bootstrap proof, process command line, environment value or raw exception/stderr.
There is no automatic upload or persistent history of previous Panel sessions.
Build metadata identifies the package; the report is not an integrity certificate
or a successful health test. Unknown and failed states keep their meaning.

The repository's independent Actions artifact-verification block is unchanged.
Adding these user diagnostics neither reads those artifacts nor waives a release
gate. Publication, installation on the maintainer's PC and the later manual
observations remain distinct steps.
