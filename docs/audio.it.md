# Profili audio locali

Il profilo audio è un job locale esplicito per una DocumentVersion esatta. Provelume non scandisce
microfoni, raccolte di registrazioni o flussi live. L'ispettore limitato riconosce WAV, FLAC, MP3,
M4A/AAC e OGG con Opus o Vorbis. In S04 viene decodificato solo WAV PCM16LE mono o stereo; le altre
celle restano di sola ispezione e dichiarano forma d'onda e trascrizione non disponibili.

    provelume audio-support INSTANCE
    provelume audio-queue INSTANCE VERSION_ID --language auto --threads 2
    provelume audio-run INSTANCE JOB_ID
    provelume audios INSTANCE

L'audio PCM produce `waveform.json` con al massimo 2.000 punti interi picco/RMS. Una ricetta intera
deterministica lo ricampiona in PCM16LE mono a 16 kHz. Container, codec, canali, frequenza, durata,
avvisi e hash della ricetta restano attribuiti all'Originale esatto e immutabile.

## ASR locale opzionale

S04 seleziona soltanto `whisper.cpp` 1.9.2 esterno e il modello multilingue
`ggml-tiny-q5_1`. Configurare esplicitamente tutti e quattro i valori prima di avviare Provelume:

    PROVELUME_WHISPER_CPP_PATH=/percorso/assoluto/a/whisper-cli
    PROVELUME_WHISPER_CPP_VERSION=1.9.2
    PROVELUME_WHISPER_CPP_SHA256=<sha256-del-binario-esatto>
    PROVELUME_WHISPER_MODEL_PATH=/percorso/assoluto/a/ggml-tiny-q5_1.bin

Il modello deve avere esattamente 32.152.673 byte e SHA-256
`818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7`. Anche il binario deve
corrispondere al digest configurato. Componenti mancanti o diversi restano visibilmente non
disponibili; installer e runtime non li scaricano né li aggiornano.

`transcript.json`, `transcript.txt` inerte e `time-map.json` conservano timestamp di segmenti e
parole qualificate, confidenza e avvisi. Ogni intervallo temporale riapre l'evidenza nello stesso
Originale esatto. Il testo è un'osservazione derivata incerta, non un'affermazione verificata né
un'identità del partecipante. Identità dei parlanti e diarizzazione sono assenti.

Usare `audio-cancel` e `audio-retry` per il recupero dei job, e `audio-remove` / `audio-rebuild` per
il ciclo di vita derivato. Backup e trasferimento portatile conservano job, bundle e cronologia di
rimozione senza cambiare Originali, conoscenza canonica o dati provider.

Servizi vocali remoti, acquisizione live, modifica della sorgente, sintesi, classificazione,
download di modelli e fallback di rete non fanno parte di questo profilo. Vedere
[ADR 0024](adr/0024-bounded-local-audio-profiles.md) e la [guida inglese](audio.md).
