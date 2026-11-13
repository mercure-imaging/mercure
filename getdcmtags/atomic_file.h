// atomic_file.h
// =============
// Publish a file so no other process sees it half-written.
//
// The router reads a series once its folder goes quiet. fopen("w+") + fprintf() exposes the final
// name while it is still empty, and writes to an open file don't touch the folder's mtime. So a
// slow write, full disk or killed receiver leaves a truncated "*.tags" that the router then parses.
//
// publishFile() writes to a hidden scratch file in the target's directory and rename()s it onto
// the target. Readers see either nothing or the complete file, and the rename bumps the folder
// mtime, which restarts the quiescence window. The scratch suffix matches common/json_io, so
// is_write_temp_file() already skips it.
//
// No fsync, on purpose: it would add a device flush to every C-STORE, and storescp doesn't fsync
// the .dcm either. After a power loss, a torn tags file (JSON, so truncation never parses) makes
// the router log "Invalid tag for series" and leave the series in place. Durability belongs to
// the storage layer.
#ifndef MERCURE_ATOMIC_FILE_H
#define MERCURE_ATOMIC_FILE_H

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <random>
#include <sstream>
#include <string>
#include <system_error>

#include <unistd.h>

// Keep in sync with common/json_io.TMP_SUFFIX.
constexpr const char* SCRATCH_SUFFIX = ".json.tmp";

// Write "payload" to "target" so a reader sees either nothing or the complete file.
// On failure the target is untouched and the scratch file is removed.
inline bool publishFile(const std::string& target, const std::string& payload)
{
    std::filesystem::path directory = std::filesystem::path(target).parent_path();

    // No O_EXCL: pid + 64 random bits make a collision negligible. It must stay that way,
    // because a collision would let one writer publish a file the other is still writing.
    static thread_local std::mt19937_64 gen([] {
        std::random_device rd;
        return (static_cast<uint64_t>(rd()) << 32) | rd();  // rd() yields only 32 bits
    }());

    // Short name keeps clear of NAME_MAX for long DICOM file names.
    std::string scratch;
    std::error_code ec;  // non-throwing: errors surface as the ofstream failing below
    do
    {
        std::ostringstream name;
        name << ".tags-" << getpid() << '-' << std::hex << gen() << SCRATCH_SUFFIX;
        scratch = (directory / name.str()).string();
    } while (std::filesystem::exists(scratch, ec));

    // Mode 0666 & ~umask, as fopen("w+") gave.
    std::ofstream out(scratch, std::ios::binary | std::ios::trunc);
    out.write(payload.data(), static_cast<std::streamsize>(payload.size()));
    out.close();  // without fsync, close is the last place a write error can show up (NFS/CIFS)
    if (out.fail() || std::rename(scratch.c_str(), target.c_str()) != 0)
    {
        std::remove(scratch.c_str());  // may not exist if open failed; that's fine
        return false;
    }
    return true;
}

#endif  // MERCURE_ATOMIC_FILE_H