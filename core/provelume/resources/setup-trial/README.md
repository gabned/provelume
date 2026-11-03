# Synthetic setup resources

The native PDF and the scan's pixels come from the complete public recipe in
https://github.com/gabned/provelume/pull/435#issuecomment-6573511376, independently
reconstructed in comment 6573536197. The recipe SHA-256 is
`b0b33921cd9eae1b2623b10e2f91582856caf36a68a8f234949128a76b930ff4`.
Its original 38,576-byte compressed scan was rejected by the existing OCR
decompression guard during real S07 integration. That failed observation remains
in #438. The new scan stores the identical raster pixels with zlib level 0:
3,869,707 bytes, SHA-256
`cf6f97c71c1f2b3752d37a335e0985edf2104c6b9b0b3fbf9543a3813ae21b97`.
No renderer limit or setting was relaxed. The public generation source is
`scripts/generate_setup_trial_fixtures.py`; it writes three reproducible resources
under ignored `.agent/s07/generated-trial-fixtures`. Only the two PDFs are packaged.

The native PDF has reliable embedded text; the scan has one raster image and no
embedded text. Search tokens occur only in content. The unrelated sentinel is
not packaged or permitted as a trial input. Exact resource sizes and SHA-256
values are checked by the trial input owner before processing.

Resource-byte/structure verification does not qualify ingestion, Original access,
OCR, search, Inbox disposition, the Windows kit or manual usability.
