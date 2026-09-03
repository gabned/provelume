# Profili foto

Il profiling foto è un job esplicito e locale per una sola DocumentVersion: Provelume non esegue
mai una scansione automatica della libreria. JPEG, PNG, TIFF e BMP ricevono dimensioni limitate,
evidenze di orientamento/colore, presenza e digest EXIF/IPTC/XMP, ora di acquisizione non
verificata e stato di privacy.

    provelume photo-support ISTANZA
    provelume photo-queue ISTANZA VERSION_ID
    provelume photo-run ISTANZA JOB_ID
    provelume photos ISTANZA

Le coordinate GPS e i campi del dispositivo sono esclusi dal record e dagli export predefiniti.
L'Originale non viene mai modificato. I digest delle famiglie di metadati provano i byte osservati
senza esporne i valori grezzi.

Pillow 12.3.0 è opzionale ed esterno. Se installato esplicitamente, genera un'anteprima PNG del
primo frame, orientata e senza metadati sorgente, più un dHash usato solo per proporre possibili
somiglianze visive. Se manca, i metadati core restano disponibili e anteprima/evidenza percettiva
risultano visibilmente non disponibili. Nessun componente viene scaricato.

Le corrispondenze esatte SHA-256 e le proposte percettive restano separate. Entrambe richiedono
revisione umana e non possono unire o eliminare nulla. Le evidenze pagina OCR esistenti sono
riutilizzate mediante ancoraggi vincolati alla Versione. QR/codici a barre restano non disponibili
senza un adapter qualificato separatamente; i payload sono rappresentati solo da hash.

WebP, HEIC/HEIF, AVIF e RAW/DNG restano Preserve-only. Inferenza di volto/identità/emozione,
condivisione GPS, riscrittura metadati, visione remota e AI sono fuori dal profilo.

photo-remove e photo-rebuild gestiscono il ciclo dello stato derivato. Backup e trasferimento
portabile includono la stessa rappresentazione; Originali esatti e record canonici non cambiano.
