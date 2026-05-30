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

.PHONY: all clean
clean:
	rm -f $(BINDIR)/getdcmtags
	rm -rf $(DCMTKDIR)
	docker rmi $(IMAGE) $(IMAGE)-standalone 2>/dev/null || true
