# Profili video locali

La profilazione video è un job locale esplicito per una sola DocumentVersion esatta. I container
candidati sono MP4, MOV, MKV, WebM e AVI, ma la conservazione non promette il supporto generale dei
codec. La matrice chiusa è in `packaging/video/ffmpeg-9.0.1.json`; stream non supportati, cifrati,
corrotti o eccessivi restano conservati e le operazioni superiori risultano non disponibili.

    provelume video-support ISTANZA
    provelume video-queue ISTANZA VERSION_ID --frame-ms 1000 --frame-ms 12000 --language auto
    provelume video-run ISTANZA JOB_ID
    provelume video-profiles ISTANZA

Il job registra stream e capitoli limitati, converte l'evidenza dei sottotitoli qualificati in
WebVTT inerte, riusa il contratto ASR locale S04 su PCM mono transitorio, individua al massimo 64
scene da campioni in scala di grigi 64×36 deterministici e materializza un fotogramma PNG per
scena. L'OCR non è mai continuo: opera soltanto sui timestamp `--frame-ms` ordinati e univoci
forniti esplicitamente, al massimo 16. Sottotitoli, trascrizione, scene e regioni OCR riaprono
ancore temporali o coppie tempo/regione nell'Originale invariato.

## Coppia FFmpeg locale opzionale

S05 seleziona esclusivamente FFmpeg/ffprobe 9.0.1 dal sorgente ufficiale
`ffmpeg-9.0.1.tar.xz`. Impostare esplicitamente tutti i valori:

    PROVELUME_FFMPEG_PATH=/percorso/assoluto/ffmpeg
    PROVELUME_FFPROBE_PATH=/percorso/assoluto/ffprobe
    PROVELUME_FFMPEG_VERSION=9.0.1
    PROVELUME_FFMPEG_SHA256=<sha256-del-binario-ffmpeg-esatto>
    PROVELUME_FFPROBE_SHA256=<sha256-del-binario-ffprobe-esatto>

L'archivio sorgente deve avere esattamente 12.036.420 byte e SHA-256
`cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635`. Entrambi i binari devono
corrispondere ai digest configurati. Wheel Python, distribuzione sorgente e installer Windows non
contengono binari o codec. Il runtime non effettua ricerca nel `PATH`, download, aggiornamento,
fallback remoto o decodifica con protocolli di rete. PyAV e PySceneDetect non sono usati.

`video-cancel` e `video-retry` gestiscono il recupero; `video-remove` / `video-rebuild` gestiscono
lo stato derivato. Backup e trasferimento portabile conservano job e bundle senza cambiare
Originali o conoscenza canonica. `GET /api/v1/video`, `/api/v1/video/support` e la vista Browser
locale `/video` sono in sola lettura; le mutazioni restano locali tramite servizio/CLI.

Il profilo non include videocamere, microfoni o feed live, sorveglianza, aggiramento DRM, media
generativi, inferenza remota, OCR continuo, riassunto/classificazione automatici, identità del
parlante/volto o modifica della sorgente. Vedere [ADR 0025](adr/0025-bounded-local-video-profiles.md)
e la [guida inglese](video.md).
