PR409 unblock evidence, retained independently from the candidate source.

The exact archive approved for public preservation is recovery-20261022.zip,
SHA256 b94ba37ab370115451c3f2224607840918b2fa1ce59694a45c3a2fd6be96c468.
It is evidence only, not a checkpoint, owner transfer, qualification or release.
Its original commit is 7b974fbe722bf749c85381ffbfa01bffa3ca70ee.

Using the unchanged accepted source cba9ff6c653bb53327ba397edf980099af90472a:
python tools/agent_protocol_work_recovery.py verify --archive ARCHIVE --sha256 b94ba37ab370115451c3f2224607840918b2fa1ce59694a45c3a2fd6be96c468
python tools/agent_protocol_work_recovery.py restore --archive ARCHIVE --sha256 b94ba37ab370115451c3f2224607840918b2fa1ce59694a45c3a2fd6be96c468 --destination NEW_DIRECTORY
python NEW_DIRECTORY/verify-originals.py

After normal GitHub push, the branch was independently cloned, the complete
archive re-verified and restored to a fresh directory, and verify-originals.py
passed there. The corresponding host receipts accompany this note.

Clarification: exact connector-decoded logs preserve each returned BOM/CR/LF
sequence. The original #408 and current container strings are LF-only; the
Windows CPU string has mixed CRLF/LF. This is not a claim about the byte layout
of an unavailable GitHub original log ZIP. The complete old local historical
container-observation archive remains unavailable; its recovered transcript
excerpt is explicitly truncated and is never treated as a full raw payload.

The initial automatic approval review rejected public archive egress. The user
then expressly authorized public push of this exact prepared package. It was
published only after that authorization. No release signal or main merge occurred.
