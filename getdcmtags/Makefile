DCMTK_REF := 969c4b6
IMAGE     := mercure-getdcmtags-build
BINDIR    := ../app/bin
DCMTKDIR  := $(BINDIR)/dcmtk
SOURCES   := Dockerfile CMakeLists.txt main.cpp tags_list.h test.py

DCMTK_APPS := storescp storescu echoscu dcmsend
BINARIES   := $(BINDIR)/getdcmtags $(addprefix $(DCMTKDIR)/,$(DCMTK_APPS) dicom.dic)

all: $(BINARIES)
	@file $(BINDIR)/getdcmtags
	@for b in $(DCMTK_APPS); do file $(DCMTKDIR)/$$b; done
	@for b in $(DCMTK_APPS); do $(DCMTKDIR)/$$b --version 2>&1 | head -1; done

$(BINARIES) &: $(SOURCES)
	mkdir -p $(DCMTKDIR)
	DOCKER_BUILDKIT=1 docker build --build-arg DCMTK_REF=$(DCMTK_REF) --target getdcmtags-builder -t $(IMAGE) .
	docker run --rm $(IMAGE)
	DOCKER_BUILDKIT=1 docker build --build-arg DCMTK_REF=$(DCMTK_REF) --target standalone-test -t $(IMAGE)-standalone .
	docker run --rm $(IMAGE)-standalone
	docker create --name mercure-build-copy $(IMAGE) true
	docker cp mercure-build-copy:/build/getdcmtags $(BINDIR)/getdcmtags
	for b in $(DCMTK_APPS) dicom.dic; do docker cp mercure-build-copy:/build/$$b $(DCMTKDIR)/$$b; done
	docker rm mercure-build-copy

# ── glibc debug build, for Valgrind/gdb ───────────────────────────────────
# See the `memorycheck` stage in the Dockerfile for why it is glibc-shared +
# DCMTK-static.  Valgrind must be run on the host: memcheck cannot hook musl's
# allocator in the shipped fully-static binary.
MEM_IMAGE := mercure-getdcmtags-memorycheck
DEBUGDIR  := build-debug
DEBUGBIN  := $(DEBUGDIR)/getdcmtags

$(MEM_IMAGE): Dockerfile CMakeLists.txt main.cpp tags_list.h
	DOCKER_BUILDKIT=1 docker build --build-arg DCMTK_REF=$(DCMTK_REF) \
	    --target memorycheck -t $(MEM_IMAGE) .

# Pull the symbolised binary out so valgrind/gdb can be used on the host.
$(DEBUGBIN): $(MEM_IMAGE)
	mkdir -p $(@D)
	id=$$(docker create $(MEM_IMAGE)); \
	docker cp $$id:/app/build/getdcmtags $@; \
	docker rm $$id
	@file $@

# Builds the glibc debug binary if needed, then runs Valgrind over it.
# Latin-1 is the charset that leaves a csmapper open at exit; ISO_IR 192 is
# UTF-8->UTF-8 and takes the persistent-mapper fast path, so it is clean by
# design.  Non-zero exit == memory errors found.
# To only (re)build the binary, without running Valgrind:
#   make build-debug/getdcmtags
memorycheck: $(DEBUGBIN)
	@command -v valgrind >/dev/null 2>&1 || { echo "valgrind is not installed"; exit 1; }
	d=$$(mktemp -d); \
	python3 gen_charset_dcm.py $$d/in.dcm --charset 'ISO_IR 100' >/dev/null; \
	cd $$d && DCMDICTPATH=$(abspath $(BINDIR)/dicom.dic) \
	  valgrind --error-exitcode=42 --num-callers=30 --log-file=vg.log \
	  $(abspath $(DEBUGBIN)) in.dcm s_addr s_aet r_aet 127.0.0.1:1 key >/dev/null 2>&1; \
	rc=$$?; \
	echo "--- valgrind: $$(grep -o 'ERROR SUMMARY: [0-9]* error[s]*' vg.log | tail -1)"; \
	grep -m1 -A 24 'Invalid ' vg.log; \
	echo "--- full log: $$d/vg.log"; \
	if [ $$rc -ne 0 ]; then \
	  echo "FAIL: exit-time use-after-free reproduced (~DcmSpecificCharacterSet runs after OFiconv_cleanup)"; \
	  exit 1; \
	fi; \
	echo "PASS: no memory errors"

.PHONY: all memorycheck
clean:
	rm -f $(BINDIR)/getdcmtags
	rm -rf $(DCMTKDIR) $(DEBUGDIR)
	docker rmi $(IMAGE) $(IMAGE)-standalone $(MEM_IMAGE) 2>/dev/null || true
