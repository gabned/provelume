# Photo profiles

Photo profiling is an explicit, local job for one exact DocumentVersion; Provelume never scans a
photo library automatically. JPEG, PNG, TIFF and BMP receive bounded dimensions, orientation/color
evidence, EXIF/IPTC/XMP presence and digests, an unverified capture time, and privacy state.

    provelume photo-support INSTANCE
    provelume photo-queue INSTANCE VERSION_ID
    provelume photo-run INSTANCE JOB_ID
    provelume photos INSTANCE

GPS coordinates and device fields are excluded from the record and from default exports. The
Original is never edited. Metadata family digests prove which bytes were observed without exposing
their raw values.

Pillow 12.3.0 is optional and external. If explicitly installed, it creates a first-frame,
orientation-normalized PNG preview with source metadata removed, plus a dHash used only to propose
possible visual similarity. Without it, core metadata remains available and preview/perceptual
support is visibly unavailable. No component is downloaded.

Exact SHA-256 matches and perceptual proposals are separate. Both require human review and neither
can merge or delete anything. Existing OCR page evidence is reused through version-bound anchors.
QR/barcode output remains unavailable unless a separately qualified adapter is supplied; payloads
are represented only by hashes.

WebP, HEIC/HEIF, AVIF and RAW/DNG remain Preserve-only. Face/identity/emotion inference, GPS
sharing, metadata write-back, remote vision and AI are outside this profile.

Use photo-remove and photo-rebuild for the derived lifecycle. Backup and portable transfer include
the same representation; exact Originals and canonical records remain unchanged.
