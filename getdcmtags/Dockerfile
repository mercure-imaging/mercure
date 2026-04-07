# syntax=docker/dockerfile:1

# ── Stage 1: DCMTK build (fully independent of source code) ──────────────────
# This stage has no COPY from the build context, so it is cached permanently
# unless you change the base image, apt packages, or DCMTK version/flags.
FROM ubuntu:20.04 AS dcmtk-builder
ENV DEBIAN_FRONTEND=noninteractive

ARG DCMTK_REF=DCMTK-3.7.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates \
    libssl-dev zlib1g-dev python3 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/DCMTK/dcmtk.git /deps/dcmtk-src \
    && cd /deps/dcmtk-src \
    && git checkout "${DCMTK_REF}"

RUN --mount=type=cache,target=/deps/dcmtk-build \
    cmake -S /deps/dcmtk-src -B /deps/dcmtk-build \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DCMAKE_INSTALL_PREFIX=/deps/dcmtk-install \
    \
    -DDCMTK_WITH_OPENSSL=ON \
    -DOPENSSL_USE_STATIC_LIBS=ON \
    -DOPENSSL_ROOT_DIR=/usr \
    -DOPENSSL_CRYPTO_LIBRARY=/usr/lib/x86_64-linux-gnu/libcrypto.a \
    -DOPENSSL_SSL_LIBRARY=/usr/lib/x86_64-linux-gnu/libssl.a \
    \
    -DDCMTK_WITH_ZLIB=ON \
    -DZLIB_LIBRARY=/usr/lib/x86_64-linux-gnu/libz.a \
    -DZLIB_INCLUDE_DIR=/usr/include \
    \
    -DDCMTK_WITH_ICONV=OFF \
    -DDCMTK_WITH_STDLIBC_ICONV=OFF \
    -DDCMTK_ENABLE_CHARSET_CONVERSION=oficonv \
    -DDCMTK_ENABLE_BUILTIN_OFICONV_DATA=ON \
    \
    -DDCMTK_WITH_SNDFILE=OFF \
    -DDCMTK_WITH_WRAP=OFF \
    -DDCMTK_WITH_DOXYGEN=OFF \
    \
    -DDCMTK_MODULES="ofstd;oflog;oficonv;dcmdata;dcmnet;dcmtls" \
    -DBUILD_APPS=OFF \
    \
    -DCMAKE_EXE_LINKER_FLAGS="-static" \
    -DCMAKE_FIND_LIBRARY_SUFFIXES=".a" \
    && find /deps/dcmtk-build -name 'osconfig.h' -exec \
       sed -i 's/#define PACKAGE_VERSION_SUFFIX "+"/#define PACKAGE_VERSION_SUFFIX " ('"${DCMTK_REF}"')"/' {} + \
    && cmake --build /deps/dcmtk-build --parallel "$(nproc)" \
    && cmake --install /deps/dcmtk-build

# Build storescp by hand against the installed libs (BUILD_APPS=OFF excluded it)
RUN mkdir -p /build \
    && cd /deps/dcmtk-src/dcmnet/apps \
    && g++ -static -O3 -DNDEBUG -o /build/storescp \
       storescp.cc \
       -I/deps/dcmtk-install/include \
       -L/deps/dcmtk-install/lib \
       -ldcmnet -ldcmtls -ldcmdata -loflog -lofstd -loficonv \
       -lssl -lcrypto -lz -lpthread -ldl \
    && strip /build/storescp \
    && cp /deps/dcmtk-src/dcmdata/data/dicom.dic /build/dicom.dic

# ── Stage 2: Build getdcmtags ────────────────────────────────────────────────
FROM dcmtk-builder AS getdcmtags-builder

WORKDIR /app
COPY CMakeLists.txt main.cpp tags_list.h ./
RUN mkdir -p /app/build && cmake -S /app -B /app/build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH=/deps/dcmtk-install \
    -DCMAKE_EXE_LINKER_FLAGS="-static -L/deps/dcmtk-install/lib" \
    -DCMAKE_FIND_LIBRARY_SUFFIXES=".a" \
    && cmake --build /app/build --parallel "$(nproc)" \
    && strip /app/build/getdcmtags \
    && cp /app/build/getdcmtags /build/getdcmtags

COPY test.py test_dcm ./
CMD ["sh", "-c", "python3 test.py /app/build/getdcmtags && echo '=== Verifying binaries ===' && ls -lh /build/getdcmtags /build/storescp && /build/storescp --version && echo '=== All checks passed ==='"]

# ── Stage 3: Verify binaries work without DCMTK installed ───────────────────
FROM alpine AS standalone-test

RUN apk add --no-cache python3

COPY --from=getdcmtags-builder /build/getdcmtags /build/storescp /build/dicom.dic /build/
COPY test.py test_dcm ./

CMD ["sh", "-c", "DCMDICTPATH=/build/dicom.dic python3 test.py /build/getdcmtags && /build/storescp --version && echo '=== Standalone test passed ==='"]
