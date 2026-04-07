DCMTK_REF := 969c4b6
IMAGE     := mercure-getdcmtags-build
BINDIR    := ../app/bin
SOURCES   := Dockerfile CMakeLists.txt main.cpp tags_list.h test.py

BINARIES  := $(BINDIR)/getdcmtags $(BINDIR)/storescp $(BINDIR)/dicom.dic

all: $(BINARIES)
	@file $(BINDIR)/getdcmtags
	@file $(BINDIR)/storescp
	@$(BINDIR)/storescp --version 2>&1 | head -3

$(BINARIES) &: $(SOURCES)
	DOCKER_BUILDKIT=1 docker build --build-arg DCMTK_REF=$(DCMTK_REF) --target getdcmtags-builder -t $(IMAGE) .
	docker run $(IMAGE)
	DOCKER_BUILDKIT=1 docker build --build-arg DCMTK_REF=$(DCMTK_REF) --target standalone-test -t $(IMAGE)-standalone .
	docker run $(IMAGE)-standalone
	$(eval CID := $(shell docker ps -lq))
	docker cp $(CID):/build/getdcmtags $(BINDIR)/getdcmtags
	docker cp $(CID):/build/storescp $(BINDIR)/storescp
	docker cp $(CID):/build/dicom.dic $(BINDIR)/dicom.dic
	docker rm $(CID)

.PHONY: all clean
clean:
	rm -f $(BINARIES)
	docker rmi $(IMAGE) 2>/dev/null || true
