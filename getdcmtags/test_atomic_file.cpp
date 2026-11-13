// test_atomic_file.cpp
// ====================
// Standalone test for publishFile() (atomic_file.h). It does not link DCMTK, so it builds and
// runs with nothing but a C++17 compiler:
//
//   g++ -std=c++17 -Wall -Wextra -o test_atomic_file test_atomic_file.cpp && ./test_atomic_file
//
// The contract the router depends on: the name a reader parses appears complete or not at all,
// and a publish that fails leaves neither the target nor a scratch file behind.

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

#include "atomic_file.h"

namespace fs = std::filesystem;

static int failures = 0;

static void check(bool condition, const std::string& what)
{
    if (!condition)
    {
        std::cout << "  FAIL: " << what << std::endl;
        failures++;
    }
}

class TempDir
{
public:
    TempDir()
    {
        char tmpl[] = "/tmp/atomic_file_test_XXXXXX";
        const char* created = mkdtemp(tmpl);
        if (created == nullptr)
        {
            std::cout << "FATAL: cannot create temp directory" << std::endl;
            exit(1);
        }
        path_ = created;
    }
    ~TempDir() { fs::permissions(path_, fs::perms::all); fs::remove_all(path_); }
    const fs::path& path() const { return path_; }
    fs::path file(const std::string& name) const { return path_ / name; }
    std::vector<std::string> entries() const
    {
        std::vector<std::string> names;
        for (const auto& entry : fs::directory_iterator(path_)) names.push_back(entry.path().filename().string());
        return names;
    }

private:
    fs::path path_;
};

static std::string readFile(const fs::path& p)
{
    std::ifstream in(p, std::ios::binary);
    std::ostringstream content;
    content << in.rdbuf();
    return content.str();
}

// Any leftover scratch file means a publish that failed did not clean up after itself.
static bool hasScratch(const TempDir& dir)
{
    const std::string suffix = SCRATCH_SUFFIX;
    for (const auto& name : dir.entries())
    {
        if (name.size() >= suffix.size() && name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0)
            return true;
    }
    return false;
}

static const char* PAYLOAD = "{\n  \"SeriesInstanceUID\": \"1.2.3\",\n}\n";

static void test_publish_is_complete_and_leaves_no_scratch()
{
    std::cout << "test_publish_is_complete_and_leaves_no_scratch" << std::endl;
    TempDir dir;
    fs::path target = dir.file("1.2.3#img_001.tags");

    check(publishFile(target.string(), PAYLOAD), "publishFile() succeeds");
    check(readFile(target) == PAYLOAD, "target holds the complete payload");
    check(dir.entries() == std::vector<std::string>{target.filename().string()}, "nothing but the target remains");

    // The mode is whatever fopen("w+") used to produce (0666 & ~umask), so the processing
    // containers keep being able to read what the receiver wrote.
    mode_t mask = umask(0);
    umask(mask);
    struct stat st;
    check(stat(target.c_str(), &st) == 0 && (st.st_mode & 0777) == (0666 & ~mask), "mode follows the umask");
}

// A publish that cannot write must leave no target and no scratch file, and must not damage a
// target that already exists.
static void test_failed_publish_leaves_nothing_behind()
{
    std::cout << "test_failed_publish_leaves_nothing_behind" << std::endl;
    TempDir dir;

    check(!publishFile((dir.path() / "does-not-exist" / "x.tags").string(), PAYLOAD),
          "publishFile() fails when the directory is missing");
    check(!fs::exists(dir.path() / "does-not-exist"), "the missing directory was not created");
    check(dir.entries().empty(), "nothing at all was left behind");

    fs::path target = dir.file("1.2.3#img_002.tags");
    check(publishFile(target.string(), PAYLOAD), "first publish succeeds");
    check(publishFile(target.string(), "{}\n"), "replacing a published file succeeds");
    check(readFile(target) == "{}\n", "the new payload is published in one piece");

    // The rename() half can fail too: renaming onto a directory is not a replacement. (A
    // read-only directory would be the other way in, but these tests may run as root, which
    // ignores directory modes.)
    fs::path obstacle = dir.file("series#img.tags");
    fs::create_directory(obstacle);
    check(!publishFile(obstacle.string(), "junk"), "publishFile() reports that it cannot rename onto a directory");
    check(!hasScratch(dir), "no scratch file left behind");

    // A directory that cannot be searched has to fail as a bool, not as std::filesystem_error.
    // Root ignores directory modes, so this only exercises anything for an unprivileged run.
    if (geteuid() != 0)
    {
        fs::path locked = dir.file("locked");
        fs::create_directory(locked);
        fs::permissions(locked, fs::perms::none);
        check(!publishFile((locked / "series#img.tags").string(), "junk"), "an unsearchable directory fails cleanly");
        fs::permissions(locked, fs::perms::all);
    }
    else
    {
        std::cout << "  (unsearchable-directory check skipped: running as root)" << std::endl;
    }
}

// Two receivers publishing at the same time must not collide on the scratch name.
static void test_repeated_publishes_do_not_collide()
{
    std::cout << "test_repeated_publishes_do_not_collide" << std::endl;
    TempDir dir;
    for (int i = 0; i < 50; i++)
    {
        check(publishFile(dir.file("series#same.tags").string(), std::string("payload ") + std::to_string(i)),
              "publish #" + std::to_string(i));
    }
    check(readFile(dir.file("series#same.tags")) == "payload 49", "the last publish wins, intact");
    check(!hasScratch(dir), "no scratch files left behind");
}

// Long DICOM file names: the scratch name is short by design, so NAME_MAX is not an issue.
static void test_long_target_names()
{
    std::cout << "test_long_target_names" << std::endl;
    TempDir dir;
    fs::path target = dir.file(std::string(220, 'x') + ".tags");
    check(publishFile(target.string(), PAYLOAD), "publish succeeds for a long target name");
    check(readFile(target) == PAYLOAD, "long-named target holds the payload");
}

// Readers key on the extension. A scratch file left by a killed receiver must carry the suffix
// every reader already ignores (common/json_io.TMP_SUFFIX -> is_write_temp_file) and must never
// look like the file the router parses.
static void test_scratch_name_is_ignored_by_readers()
{
    std::cout << "test_scratch_name_is_ignored_by_readers" << std::endl;
    check(std::string(SCRATCH_SUFFIX) == ".json.tmp", "suffix matches common/json_io.TMP_SUFFIX");
    check(std::string(SCRATCH_SUFFIX) != ".tags", "a scratch file is never a tags file");
}

int main()
{
    struct { const char* name; void (*fn)(); } tests[] = {
        {"publish is complete and leaves no scratch", test_publish_is_complete_and_leaves_no_scratch},
        {"failed publish leaves nothing behind", test_failed_publish_leaves_nothing_behind},
        {"repeated publishes do not collide", test_repeated_publishes_do_not_collide},
        {"long target names", test_long_target_names},
        {"scratch name is ignored by readers", test_scratch_name_is_ignored_by_readers},
    };

    for (const auto& test : tests)
    {
        int before = failures;
        test.fn();
        if (failures == before) std::cout << "  PASS" << std::endl;
    }

    if (failures)
    {
        std::cout << failures << " check(s) FAILED" << std::endl;
        return 1;
    }
    std::cout << "all publishFile checks passed" << std::endl;
    return 0;
}
