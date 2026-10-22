# Native helper tests

Run the shutdown memory checks with the DCMTK revision pinned in the Makefile:

```sh
make -C getdcmtags memorycheck
```

This builds a glibc debug image with DCMTK's oficonv backend. Valgrind checks
the real helper, including normal shutdown, an error after character-set
selection, bookkeeper notification, and the storescp reception hook. Memory
errors return status 99, distinct from the helper's expected error status 1.
The reception test checks the helper's recorded exit status as well as its tags;
a successful DICOM transfer alone does not establish that the hook succeeded.

`test_latin1.dcm` and `test_utf8.dcm` are synthetic Explicit VR Little Endian
DICOM files generated with pydicom. They share the existing test series UID and
contain only synthetic identifiers and names (`Müller^Synthetic` in Latin-1 and
`山田^Synthetic` in UTF-8). Tests require only Python's standard library.

The release builder and standalone image also run the native tests without
Valgrind. For an individual build, run:

```sh
python3 test.py /absolute/path/to/getdcmtags /absolute/path/to/dcmtk
# Add --valgrind for an unstripped glibc build and its debug DCMTK libraries.
```

The checked-in release helper is a static Linux x86-64 executable. When
rebuilding it on another architecture, explicitly select `linux/amd64` for
Docker builds and runs and pass the Makefile's `DCMTK_REF` build argument.
Rebuild the helper before building receiver images, which copy the bundled
executable rather than compiling its source.
