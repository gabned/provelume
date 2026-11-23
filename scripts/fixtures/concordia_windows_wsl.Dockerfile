FROM debian@sha256:7378260c0a098d27ac206225db5e7d92b8c7c84ea7afccc86eeb513756bbd392 AS guest
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        docker.io=26.1.5+dfsg1-9+deb13u1+b1 docker-cli=26.1.5+dfsg1-9+deb13u1+b1 \
        containerd=1.7.24~ds1-6+deb13u1 runc=1.1.15+ds1-2+b4 \
    && rm -rf /var/lib/apt/lists/* \
    && printf '[automount]\nenabled=false\nmountFsTab=false\n[interop]\nenabled=false\nappendWindowsPath=false\n[network]\ngenerateResolvConf=false\n[boot]\nsystemd=false\n' > /etc/wsl.conf \
    && mkdir -m 0700 /run/provelume-concordia \
    && truncate -s 0 /etc/machine-id
ARG FIXTURE_HEAD
RUN printf '%s\n' "$FIXTURE_HEAD" > /etc/provelume-concordia-fixture

FROM debian@sha256:7378260c0a098d27ac206225db5e7d92b8c7c84ea7afccc86eeb513756bbd392 AS builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssh-server=1:10.0p1-7+deb13u4 git gcc make libc6-dev python3 \
        libbz2-1.0 libexpat1 libffi8 libgdbm6t64 liblzma5 libncursesw6 libreadline8t64 libsqlite3-0 zlib1g \
    && rm -f /etc/ssh/ssh_host_* \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory /source
COPY rsync-source.tar.gz /tmp/
RUN tar -xzf /tmp/rsync-source.tar.gz -C /tmp \
    && cd /tmp/rsync-3.5.2 \
    && ./configure --disable-md2man --disable-openssl --disable-xxhash \
        --disable-zstd --disable-lz4 --disable-idn --with-included-popt \
    && make -j2 rsync \
    && install -D -m 0755 rsync /opt/rsync/rsync \
    && rm -rf /tmp/rsync-3.5.2 /tmp/rsync-source.tar.gz
