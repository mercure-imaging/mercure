# syntax=docker/dockerfile:1

# ── Stage 1: DCMTK build (Alpine/musl for safe static linking) ──────────────
# musl's resolver is self-contained (no dlopen for NSS), so the resulting
# static binary works reliably on any Linux distro without SIGSEGV from
# glibc's NSS dlopen when storescp does reverse-DNS on connecting clients.
FROM alpine:3.20 AS dcmtk-builder

ARG DCMTK_REF=DCMTK-3.7.0

RUN apk add --no-cache \
    build-base cmake git \
    openssl-dev openssl-libs-static \
    zlib-dev zlib-static \
    python3

RUN git clone https://github.com/DCMTK/dcmtk.git /deps/dcmtk-src \
    && cd /deps/dcmtk-src \
    && git checkout "${DCMTK_REF}"

RUN --mount=type=cache,target=/deps/dcmtk-build-musl \
    cmake -S /deps/dcmtk-src -B /deps/dcmtk-build-musl \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DCMAKE_INSTALL_PREFIX=/deps/dcmtk-install \
    \
    -DDCMTK_WITH_OPENSSL=ON \
    -DOPENSSL_USE_STATIC_LIBS=ON \
    -DOPENSSL_ROOT_DIR=/usr \
    -DOPENSSL_CRYPTO_LIBRARY=/usr/lib/libcrypto.a \
    -DOPENSSL_SSL_LIBRARY=/usr/lib/libssl.a \
    \
    -DDCMTK_WITH_ZLIB=ON \
    -DZLIB_LIBRARY=/usr/lib/libz.a \
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
    -DDCMTK_MODULES="ofstd;oflog;oficonv;dcmdata;dcmimgle;dcmimage;dcmjpeg;dcmjpls;dcmnet;dcmtls" \
    -DBUILD_APPS=OFF \
    \
    -DCMAKE_EXE_LINKER_FLAGS="-static" \
    -DCMAKE_FIND_LIBRARY_SUFFIXES=".a" \
    \
    -DDCMTK_ENABLE_LFS=lfs \
    && find /deps/dcmtk-build-musl -name 'osconfig.h' -exec \
       sed -i 's/#define PACKAGE_VERSION_SUFFIX "+"/#define PACKAGE_VERSION_SUFFIX " ('"${DCMTK_REF}"')"/' {} + \
    && find /deps/dcmtk-build-musl -name 'osconfig.h' -exec \
       sed -i 's|#define DCM_DICT_DEFAULT_PATH .*|#define DCM_DICT_DEFAULT_PATH "bin/dcmtk/dicom.dic"|' {} + \
    && cmake --build /deps/dcmtk-build-musl --parallel "$(nproc)" \
    && cmake --install /deps/dcmtk-build-musl

# Build DCMTK apps by hand against the installed libs (BUILD_APPS=OFF excluded them)
RUN mkdir -p /build \
    && cd /deps/dcmtk-src/dcmnet/apps \
    && CXXFLAGS="-static -O3 -DNDEBUG" \
       INCLUDES="-I/deps/dcmtk-install/include" \
       LIBDIRS="-L/deps/dcmtk-install/lib" \
       LIBS="-ldcmnet -ldcmtls -ldcmjpeg -ldcmjpls -ldcmimage -ldcmimgle -ldcmdata -loflog -lofstd -loficonv -lijg8 -lijg12 -lijg16 -ldcmtkcharls -lssl -lcrypto -lz -lpthread" \
    && for app in storescp storescu echoscu dcmsend; do \
         g++ $CXXFLAGS $INCLUDES -o /build/$app ${app}.cc $LIBDIRS $LIBS \
         && strip /build/$app; \
       done \
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
# Create bin/dcmtk/ layout so the compiled-in default dict path resolves from CWD
RUN mkdir -p bin && ln -s /build bin/dcmtk
CMD ["sh", "-c", "python3 test.py /app/build/getdcmtags /build && echo '=== All checks passed ==='"]

# ── Alternate debug build: glibc, for Valgrind ──────────────────────────────
# Debug builds use glibc so Valgrind can track allocations inside DCMTK/oficonv:
# memcheck cannot hook musl's mallocng in a fully static binary so heap errors are
# invisible there.
#
# Charset backend and DCMTK revision are kept identical to the release build.
# Modules are trimmed to what getdcmtags needs to keep the build small.
#
#   make memorycheck    # build the glibc debug binary and run Valgrind on it
#                       # (binary is kept at build-debug/getdcmtags for gdb)
#
# DCMTK_REF defaults to the same pinned commit as the release build (see
# Makefile) so the debug binary contains identical DCMTK/oficonv code
FROM ubuntu:24.04 AS memorycheck

ARG DCMTK_REF=969c4b6

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Blobless clone: works for both a tag name and a bare commit SHA (the release
# build pins a SHA), and keeps the layer small.
RUN git clone --filter=blob:none --no-checkout \
        https://github.com/DCMTK/dcmtk.git /deps/dcmtk-src \
    && git -C /deps/dcmtk-src checkout "${DCMTK_REF}" \
    && git -C /deps/dcmtk-src rev-parse HEAD

RUN cmake -S /deps/dcmtk-src -B /deps/dcmtk-build \
    -DCMAKE_BUILD_TYPE=Debug -DBUILD_SHARED_LIBS=OFF -DBUILD_APPS=OFF \
    -DCMAKE_INSTALL_PREFIX=/deps/dcmtk-install \
    -DDCMTK_MODULES="ofstd;oflog;oficonv;dcmdata" \
    -DDCMTK_WITH_OPENSSL=OFF -DDCMTK_WITH_ZLIB=ON \
    -DDCMTK_WITH_PNG=OFF -DDCMTK_WITH_TIFF=OFF -DDCMTK_WITH_XML=OFF \
    -DDCMTK_WITH_SNDFILE=OFF -DDCMTK_WITH_WRAP=OFF -DDCMTK_WITH_DOXYGEN=OFF \
    -DDCMTK_WITH_ICONV=OFF -DDCMTK_WITH_STDLIBC_ICONV=OFF \
    -DDCMTK_ENABLE_CHARSET_CONVERSION=oficonv -DDCMTK_ENABLE_BUILTIN_OFICONV_DATA=ON \
    && cmake --build /deps/dcmtk-build --parallel 4 \
    && cmake --install /deps/dcmtk-build \
    && rm -rf /deps/dcmtk-build /deps/dcmtk-src

WORKDIR /app
COPY CMakeLists.txt main.cpp tags_list.h ./
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug \
    -DCMAKE_PREFIX_PATH=/deps/dcmtk-install \
    -DCMAKE_EXE_LINKER_FLAGS="-L/deps/dcmtk-install/lib" \
    && cmake --build build --parallel 4

# glibc-linked, symbolised getdcmtags with static DCMTK/oficonv inside
CMD ["/app/build/getdcmtags", "--version"]

# ── Alternate build: AddressSanitizer (+ UBSan) ──────────────────────────────
# Complements `memorycheck`: memcheck cannot see stack/global buffer overruns,
# intra-block heap overruns, or use-after-return, and it needs a glibc binary.
# DCMTK/oficonv are instrumented too, so overruns inside DCMTK are attributed
# correctly.  libasan/libubsan are linked statically so the binary runs on the
# host without an ASan runtime.
#
#   make asan        # build, extract to build-asan/, run the scenario suite
#   python3 audit_memory.py --binary build-asan/getdcmtags --tool asan
#
# Note ASan's leak check is on by default; getdcmtags is a short-lived process,
# so leaks are set off by the audit script (ASAN_OPTIONS=detect_leaks=0) and
# leak reporting is left to `make memorycheck`.
FROM ubuntu:24.04 AS asan

ARG DCMTK_REF=969c4b6
ARG SANITIZE="address,undefined -fno-sanitize-recover=address"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --filter=blob:none --no-checkout \
        https://github.com/DCMTK/dcmtk.git /deps/dcmtk-src \
    && git -C /deps/dcmtk-src checkout "${DCMTK_REF}"

RUN cmake -S /deps/dcmtk-src -B /deps/dcmtk-build \
    -DCMAKE_BUILD_TYPE=Debug -DBUILD_SHARED_LIBS=OFF -DBUILD_APPS=OFF \
    -DCMAKE_INSTALL_PREFIX=/deps/dcmtk-install \
    -DCMAKE_C_FLAGS="-O1 -g -fno-omit-frame-pointer -fsanitize=${SANITIZE}" \
    -DCMAKE_CXX_FLAGS="-O1 -g -fno-omit-frame-pointer -fsanitize=${SANITIZE}" \
    -DDCMTK_MODULES="ofstd;oflog;oficonv;dcmdata" \
    -DDCMTK_WITH_OPENSSL=OFF -DDCMTK_WITH_ZLIB=ON \
    -DDCMTK_WITH_PNG=OFF -DDCMTK_WITH_TIFF=OFF -DDCMTK_WITH_XML=OFF \
    -DDCMTK_WITH_SNDFILE=OFF -DDCMTK_WITH_WRAP=OFF -DDCMTK_WITH_DOXYGEN=OFF \
    -DDCMTK_WITH_ICONV=OFF -DDCMTK_WITH_STDLIBC_ICONV=OFF \
    -DDCMTK_ENABLE_CHARSET_CONVERSION=oficonv -DDCMTK_ENABLE_BUILTIN_OFICONV_DATA=ON \
    && cmake --build /deps/dcmtk-build --parallel 4 \
    && cmake --install /deps/dcmtk-build \
    && rm -rf /deps/dcmtk-build /deps/dcmtk-src

WORKDIR /app
COPY CMakeLists.txt main.cpp tags_list.h ./
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug \
    -DCMAKE_PREFIX_PATH=/deps/dcmtk-install \
    -DCMAKE_CXX_FLAGS="-O1 -g -fno-omit-frame-pointer -fsanitize=${SANITIZE}" \
    -DCMAKE_EXE_LINKER_FLAGS="-L/deps/dcmtk-install/lib -fsanitize=${SANITIZE} -static-libasan -static-libubsan" \
    && cmake --build build --parallel 4

CMD ["/app/build/getdcmtags", "--version"]

# ── Stage 3: Verify binaries work without DCMTK installed ───────────────────
# Layout mirrors runtime: CWD has bin/dcmtk/{storescp,storescu,...,dicom.dic}
# and bin/getdcmtags. No DCMDICTPATH is set, so the compiled-in default
# ("bin/dcmtk/dicom.dic") must resolve correctly.
FROM alpine AS standalone-test

RUN apk add --no-cache python3

WORKDIR /app
COPY --from=getdcmtags-builder /build/getdcmtags bin/getdcmtags
COPY --from=getdcmtags-builder /build/storescp /build/storescu /build/echoscu /build/dcmsend /build/dicom.dic bin/dcmtk/
COPY test.py test_dcm ./

CMD ["sh", "-c", "python3 test.py bin/getdcmtags bin/dcmtk && echo '=== Standalone test passed ==='"]
