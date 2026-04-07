#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sstream>
#include <iomanip>
#include <string>
#include <vector>
#include <utility>
#include <fstream>
#include <filesystem>
#include <cstring>
#include <csignal>
#include <stdexcept>

#include <sys/types.h>
#include <sys/socket.h>
#include <sys/file.h>
#include <fcntl.h>
#include <netdb.h>
#include <arpa/inet.h>

#include "dcmtk/dcmdata/dcpath.h"
#include "dcmtk/dcmdata/dcerror.h"
#include "dcmtk/dcmdata/dctk.h"
#include "dcmtk/ofstd/ofstd.h"
#include "dcmtk/dcmdata/dcspchrs.h"
#include "dcmtk/dcmdata/dctypes.h"

#include "tags_list.h"

#define VERSION "getdcmtags Version 0.76"


struct Config {
    OFString senderAddress;
    OFString senderAET;
    OFString receiverAET;
    std::string bookkeeperAddress;
    std::string bookkeeperToken;
    std::vector<std::pair<OFString, OFString>> forceTags;
    bool tagsStopEarly = false;
    int testInjectError = 0;
};


struct DicomResult {
    OFString specificCharacterSet;
    OFString seriesInstanceUID;
    OFString sopInstanceUID;
    std::vector<std::pair<DcmTagKey, OFString>> mainTags;
    std::vector<std::pair<DcmTagKey, OFString>> additionalTags;
    bool conversionNeeded = false;
};


static DcmSpecificCharacterSet charsetConverter;

#define DO_ERROR(cfg, n) \
    ((cfg).testInjectError == n)


// Escape the JSON values properly to avoid problems if DICOM tags contains invalid characters
// (see https://stackoverflow.com/questions/7724448/simple-json-string-escape-for-c)
std::string escapeJSONValue(const OFString &s)
{
    std::ostringstream o;
    for (auto c = s.begin(); c != s.end(); c++)
    {
        // Convert control characters into UTF8 coded version
        if (*c == '"' || *c == '\\' || ('\x00' <= *c && *c <= '\x1f') || *c == '\x7f')
        {
            o << "\\u" << std::hex << std::setw(4) << std::setfill('0') << (int)*c;
        }
        else
        {
            o << *c;
        }
    }
    return o.str();
}


static std::string urlEncode(const std::string &value)
{
    std::ostringstream o;
    for (unsigned char c : value)
    {
        if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~')
            o << c;
        else
            o << '%' << std::hex << std::uppercase << std::setw(2) << std::setfill('0') << (int)c;
    }
    return o.str();
}


void sendBookkeeperPost(const Config& cfg, OFString filename, OFString fileUID, OFString seriesUID)
{
    // Parse host:port from bookkeeperAddress
    std::string host = cfg.bookkeeperAddress;
    std::string port = "80";
    size_t colonPos = host.rfind(':');
    if (colonPos != std::string::npos)
    {
        port = host.substr(colonPos + 1);
        host = host.substr(0, colonPos);
    }

    struct addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    if (getaddrinfo(host.c_str(), port.c_str(), &hints, &res) != 0 || !res)
    {
        std::cout << "WARNING: Unable to resolve bookkeeper address " << cfg.bookkeeperAddress << std::endl;
        return;
    }

    int sock = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (sock < 0)
    {
        freeaddrinfo(res);
        return;
    }

    if (connect(sock, res->ai_addr, res->ai_addrlen) < 0)
    {
        close(sock);
        freeaddrinfo(res);
        std::cout << "WARNING: Unable to connect to bookkeeper at " << cfg.bookkeeperAddress << std::endl;
        return;
    }
    freeaddrinfo(res);

    std::string body = "filename=" + urlEncode(std::string(filename.c_str())) +
                       "&file_uid=" + urlEncode(std::string(fileUID.c_str())) +
                       "&series_uid=" + urlEncode(std::string(seriesUID.c_str()));

    std::ostringstream req;
    req << "POST /register-dicom HTTP/1.0\r\n"
        << "Host: " << cfg.bookkeeperAddress << "\r\n"
        << "Content-Type: application/x-www-form-urlencoded\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Authorization: Token " << cfg.bookkeeperToken << "\r\n"
        << "\r\n"
        << body;

    std::string reqStr = req.str();
    size_t sent = 0;
    while (sent < reqStr.size()) {
        ssize_t n = send(sock, reqStr.c_str() + sent, reqStr.size() - sent, 0);
        if (n <= 0) break;
        sent += n;
    }

    // Read response (fire-and-forget, but drain to avoid RST)
    char buf[512];
    while (recv(sock, buf, sizeof(buf), 0) > 0) {}

    close(sock);
}


void writeErrorInformation(OFString dcmFile, OFString errorString)
{
    std::cout << errorString << std::endl;
    OFString filename = dcmFile + ".error";
    OFString lock_filename = dcmFile + ".error.lock";
    std::cout << "Writing error information to: " << filename << std::endl;
    // Lock file with flock() to ensure no other process moves the file
    // while the error information is written
    int lock_fd = open(lock_filename.c_str(), O_CREAT | O_WRONLY, 0644);
    if (lock_fd < 0)
    {
        std::cout << "ERROR: Unable to create lock file " << lock_filename << std::endl;
        // If the lock file cannot be created, something is seriously wrong. In this case,
        // it is better to let the received file remain in the incoming folder.
        return;
    }
    if (flock(lock_fd, LOCK_EX) < 0)
    {
        std::cout << "ERROR: Unable to acquire lock on " << lock_filename << std::endl;
        close(lock_fd);
        return;
    }

    errorString = "ERROR: " + errorString;
    FILE *fp = fopen(filename.c_str(), "w+");

    if (fp == nullptr)
    {
        std::cout << "ERROR: Unable to write error file " << filename << std::endl;
    } else {
        fprintf(fp, "%s\n", errorString.c_str());
        fclose(fp);
    }
    // Release and remove lock file
    flock(lock_fd, LOCK_UN);
    close(lock_fd);
    remove(lock_filename.c_str());
}


static void insertTag(FILE* fp, const char* name, const OFString& value, const OFString& dcmFile, const DicomResult& result)
{
    OFString converted;
    if (result.conversionNeeded)
    {
        if (!charsetConverter.convertString(value, converted).good())
        {
            std::cout << "ERROR: Unable to convert charset for tag " << name << std::endl;
            std::cout << "ERROR: Unable to process file " << dcmFile << std::endl;
            throw std::runtime_error("charset conversion failed");
        }
    }
    else
    {
        converted = value;
    }
    fprintf(fp, "\"%s\": \"%s\",\n", name, escapeJSONValue(converted).c_str());
}


static DcmTagKey parseTagKey(const char *tagName)
{
    unsigned int group = 0xffff;
    unsigned int elem = 0xffff;
    if (sscanf(tagName, "%x,%x", &group, &elem) != 2)
    {
        DcmTagKey tagKey;
        /* it is a name */
        const DcmDataDictionary &globalDataDict = dcmDataDict.rdlock();
        const DcmDictEntry *dicent = globalDataDict.findEntry(tagName);
        if (dicent == NULL) {
            tagKey = DCM_UndefinedTagKey;
        } else {
            tagKey = dicent->getKey();
        }
        dcmDataDict.rdunlock();
        return tagKey;
    } else     /* tag name has format "gggg,eeee" */
    {
        if (group > 0xFFFF || elem > 0xFFFF) {
            return DCM_UndefinedTagKey;
        }
        return DcmTagKey(OFstatic_cast(Uint16, group),OFstatic_cast(Uint16, elem));
    }
}


bool readTag(DcmTagKey tag, DcmItem* dataset, OFString& out, OFString path_info) {
    if (!dataset->tagExistsWithValue(tag)) {
        return true;
    }
    OFCondition result = dataset->findAndGetOFStringArray(tag, out);
    if (!result.good())
    {
        OFString errorStr = "Unable to read tag ";
        errorStr.append(tag.toString());
        errorStr.append("\nReason: ");
        errorStr.append(result.text());
        writeErrorInformation(path_info, errorStr);
        return false;
    }
    for (size_t i = 0; i < out.length(); i++)
    {
        switch (out[i])
        {
        case 13:
            out[i] = ';';
            break;
        case 10:
            out[i] = ' ';
            break;
        case 34:
            out[i] = 39;
            break;
        default:
            break;
        }
    }
    return true;
}


static std::string getExePath()
{
    char buf[4096];
    ssize_t len = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
    if (len <= 0) return ".";
    buf[len] = '\0';
    std::string path(buf);
    size_t pos = path.rfind('/');
    return (pos != std::string::npos) ? path.substr(0, pos) : ".";
}


bool readExtraTags(DcmDataset* dataset, OFString path_info, DicomResult& result) {
    std::string filePath = "./dcm_extra_tags";
    std::ifstream inputFile(filePath);
    if (!inputFile.is_open()) {
        filePath = getExePath() + "/dcm_extra_tags";
        inputFile.open(filePath);
    }
    if (inputFile.is_open()) {

        std::string line;
        while (std::getline(inputFile, line)) {
            if (line.empty()) continue;

            OFString out;
            DcmTagKey the_tag = parseTagKey(line.c_str());
            if (the_tag == DCM_UndefinedTagKey) {
                std::cout << "Unknown tag " << line << std::endl;
                return false;
            }
            if (!readTag(the_tag, dataset, out, path_info))
                return false;
            result.additionalTags.push_back(std::make_pair(the_tag, out));
        }
    }
    return true;
}


void writeTagsList(std::vector<std::pair<DcmTagKey, OFString>>& tags, FILE* fp, const OFString& dcmFile, const DicomResult& result) {

    const DcmDataDictionary &globalDataDict = dcmDataDict.rdlock();
    for (const auto& pair : tags)
    {
        const DcmDictEntry *dicent = globalDataDict.findEntry(pair.first, NULL);
        if (dicent == NULL) {
            insertTag(fp, pair.first.toString().c_str(), pair.second, dcmFile, result);
        } else {
            insertTag(fp, dicent->getTagName(), pair.second, dcmFile, result);
        }
    }
    dcmDataDict.rdunlock();
}


bool writeForceTagsList(const std::vector<std::pair<OFString, OFString>>& tags, FILE* fp) {
    for (const auto& pair : tags)
    {
        fprintf(fp, "\"%s\": \"%s\",\n", escapeJSONValue(pair.first).c_str(), escapeJSONValue(pair.second).c_str());
    }
    return true;
}


bool writeTagsFile(OFString dcmFile, OFString originalFile, const Config& cfg, DicomResult& result)
{
    OFString filename = dcmFile + ".tags";
    FILE *fp = fopen(filename.c_str(), "w+");

    if (fp == nullptr)
    {
        std::cout << "ERROR: Unable to write tag file " << filename << std::endl;
        return false;
    }

    try {
        fprintf(fp, "{\n");
        insertTag(fp, "SpecificCharacterSet", result.specificCharacterSet, dcmFile, result);
        insertTag(fp, "SeriesInstanceUID", result.seriesInstanceUID, dcmFile, result);
        insertTag(fp, "SOPInstanceUID", result.sopInstanceUID, dcmFile, result);

        insertTag(fp, "SenderAddress", cfg.senderAddress, dcmFile, result);
        insertTag(fp, "SenderAET", cfg.senderAET, dcmFile, result);
        insertTag(fp, "ReceiverAET", cfg.receiverAET, dcmFile, result);

        writeTagsList(result.mainTags, fp, dcmFile, result);
        writeTagsList(result.additionalTags, fp, dcmFile, result);

        writeForceTagsList(cfg.forceTags, fp);

        fprintf(fp, "\"Filename\": \"%s\"\n", escapeJSONValue(originalFile).c_str());
        fprintf(fp, "}\n");

        fclose(fp);
        return true;
    } catch (const std::runtime_error&) {
        fclose(fp);
        remove(filename.c_str());
        return false;
    }
}

bool createSeriesFolder(const OFString& path, const OFString& seriesUID) {
    OFString effectivePath = path.empty() ? OFString("./") : path;
    OFString fullPath = effectivePath + seriesUID;
    namespace fs = std::filesystem;
    fs::path cleanParent = fs::absolute(fs::path(effectivePath.c_str())).lexically_normal();
    fs::path cleanChild = fs::absolute(fs::path(fullPath.c_str())).lexically_normal();
    std::string parentStr = cleanParent.string();
    std::string childStr = cleanChild.string();
    // Remove trailing slashes for consistent comparison
    while (parentStr.size() > 1 && parentStr.back() == '/') parentStr.pop_back();
    while (childStr.size() > 1 && childStr.back() == '/') childStr.pop_back();
    if (childStr.compare(0, parentStr.size(), parentStr) != 0 ||
        (childStr.size() > parentStr.size() && parentStr != "/" && childStr[parentStr.size()] != '/')) {
        std::cout << "ERROR: Path traversal detected: '" << fullPath << "' escapes '" << effectivePath << "'"<< std::endl;
        std::cout << childStr << std::endl;
        std::cout << parentStr << std::endl;
        return false;
    }
    std::error_code ec;
    fs::create_directories(fs::path(fullPath.c_str()), ec);
    if (ec) {
        std::cout << "ERROR: Unable to create directory " << fullPath << std::endl;
        return false;
    }
    return true;
}

void writeErrorInformationAndMove(const OFString& path, const OFString& filename, const OFString& errorString) {
        if (!createSeriesFolder(path, "error")) {
            writeErrorInformation(path+filename, errorString);
            return;
        }
        if (rename((path+filename).c_str(), (path + "error/" + filename + ".dcm").c_str()) != 0) {
            writeErrorInformation(path+filename, errorString);
            return;
        }
        if (std::filesystem::exists(std::string((path+filename+".error").c_str()))) {
            rename((path+filename+".error").c_str(), (path+"error/"+filename+".dcm.error").c_str());
        }
        writeErrorInformation(path + "error/" + filename+".dcm", errorString);
}

DcmTagKey calculateUntilTag(const DicomResult& result) {
    const DcmTagKey* last_tag = std::max_element(main_tags_list.begin(), main_tags_list.end());
    if (result.additionalTags.size() > 0) {
        DcmTagKey last_tag_additional = std::max_element(result.additionalTags.begin(), result.additionalTags.end())->first;
        std::cout << "Last additional tag: " << last_tag_additional.toString() << std::endl;
        if (*last_tag < last_tag_additional) {
            last_tag = &last_tag_additional;
        }
    }
    std::cout << "Last tag: " << last_tag->toString() << std::endl;
    DcmTagKey next_tag = DCM_UndefinedTagKey;

    if (last_tag->getElement() == 0xFFFF) {
        next_tag = DcmTagKey(last_tag->getGroup()+1, 0x0000);
    } else {
        next_tag = DcmTagKey(last_tag->getGroup(), last_tag->getElement()+1);
    }
    return next_tag;
}

int main(int argc, char *argv[])
{
    if (!charsetConverter.isConversionAvailable())
    {
        std::cout << std::endl;
        std::cout << "ERROR: Characterset converter not available" << std::endl
                  << std::endl;
        std::cout << "ERROR: Check installed libraries" << std::endl
                  << std::endl;

        return 1;
    }

    if (argc < 5)
    {
        std::cout << std::endl;
        std::cout << VERSION << " (DCMTK " << OFFIS_DCMTK_VERSION_STRING << ")" << std::endl;
        std::cout << "------------------------" << std::endl
                  << std::endl;
        std::cout << "Usage: [dcm file to analyze] [sender address] [sender AET] [receiver AET] [ip:port of bookkeeper] [api key for bookkeeper]" << std::endl
                  << std::endl;
        return 0;
    }

    Config cfg;
    DicomResult result;

    cfg.senderAddress = OFString(argv[2]);
    cfg.senderAET = OFString(argv[3]);
    cfg.receiverAET = OFString(argv[4]);

    bool injectErrors = false;
    if (argc > 5)
    {
        cfg.bookkeeperAddress = std::string(argv[5]);
        if (cfg.bookkeeperAddress.find_first_of("\r\n") != std::string::npos)
        {
            std::cout << "ERROR: Bookkeeper address must not contain \\r or \\n" << std::endl;
            return 1;
        }
    }

    if (argc > 6)
    {
        cfg.bookkeeperToken = std::string(argv[6]);
        if (cfg.bookkeeperToken.find_first_of("\r\n") != std::string::npos)
        {
            std::cout << "ERROR: Bookkeeper token must not contain \\r or \\n" << std::endl;
            return 1;
        }
    }
    if (argc > 7)
    {
        // scan argv for additional arguments and store them in a vector of strings
        for (int i = 7; i < argc; ++i) {
            if (strcmp(argv[i],"--inject-errors") == 0 ) {
                injectErrors = true;
            } else if (strcmp(argv[i], "--tags-stop-early") == 0) {
                cfg.tagsStopEarly = true;
            } else if (strcmp(argv[i], "--set-tag") == 0 && i + 1 < argc) {
                std::string tag = std::string(argv[++i]);
                size_t pos = tag.find('=');
                if (pos != std::string::npos) {
                    auto name = tag.substr(0, pos);
                    if (name == "Filename") {
                        std::cout << "ERROR: --set-tag cannot override Filename" << std::endl;
                        return 1;
                    }
                    auto value = OFString(tag.substr(pos + 1).c_str());
                    cfg.forceTags.push_back(std::make_pair(OFString(name.c_str()), value));
                }
            }
        }
    }
    if (injectErrors) {
        std::ifstream file("./dcm_inject_error");
        if (file.is_open()) {
            std::string content;
            std::getline(file, content);
            // Trim whitespace
            size_t start = content.find_first_not_of(" \t\r\n");
            size_t end = content.find_last_not_of(" \t\r\n");
            if (start != std::string::npos) {
                try {
                    cfg.testInjectError = std::stoi(content.substr(start, end - start + 1));
                } catch (const std::exception &e) {
                    std::cout << "WARNING: Failed to parse dcm_inject_error: " << e.what() << std::endl;
                }
            }
            file.close();
        }
    }

    OFString origFilename = OFString(argv[1]);
    OFString path = "";

    size_t slashPos = origFilename.rfind("/");
    if (slashPos != OFString_npos)
    {
        path = origFilename.substr(0, slashPos + 1);
        origFilename.erase(0, slashPos + 1);
    }
    // Ensure origFilename is a plain filename with no path separators
    if (origFilename.find('/') != OFString_npos ||
        origFilename.find('\\') != OFString_npos ||
        origFilename.find('\0') != OFString_npos ||
        origFilename.empty())
    {
        std::cout << "ERROR: Invalid filename " << argv[1] << std::endl;
        return 1;
    }
    OFString full_path = path + origFilename;
    DcmFileFormat dcmFile;

    DcmTagKey untilTag;
    if (cfg.tagsStopEarly) {
        untilTag = calculateUntilTag(result);
    } else {
        untilTag = DCM_UndefinedTagKey;
    }
    OFCondition status = dcmFile.loadFileUntilTag(full_path, EXS_Unknown, EGL_noChange, 4096U, ERM_autoDetect, untilTag);

    if (DO_ERROR(cfg, 1) || !status.good())
    {
        OFString errorString = "Unable to read DICOM file ";
        errorString.append(origFilename);
        errorString.append("\nError: ");
        errorString.append(status.text());
        errorString.append("\n");
        writeErrorInformationAndMove(path, origFilename, errorString);
        return 1;
    }
    DcmDataset* dataset = dcmFile.getDataset();

    readTag(DCM_SpecificCharacterSet, dataset, result.specificCharacterSet, full_path);
    readTag(DCM_SOPInstanceUID, dataset, result.sopInstanceUID, full_path);
    readTag(DCM_SeriesInstanceUID, dataset, result.seriesInstanceUID, full_path);

    if (result.seriesInstanceUID.find('/') != OFString_npos ||
        result.seriesInstanceUID.find('\\') != OFString_npos ||
        result.seriesInstanceUID.find('\0') != OFString_npos)
    {
        writeErrorInformationAndMove(path, origFilename, "SeriesInstanceUID contains invalid path characters\n");
        return 1;
    }

    OFString tag_read_out = "";
    bool read_success = true;
    for (auto tag: main_tags_list ) {
        tag_read_out = "";
        if (!readTag(tag, dataset, tag_read_out, full_path)) {
            read_success = false;
            break;
        }
        result.mainTags.push_back(std::make_pair(tag, tag_read_out));
    }
    if (DO_ERROR(cfg, 2) || !read_success) {
        writeErrorInformationAndMove(path, origFilename, "Unable to read some DICOM tags\n");
        return 1;
    }
    tag_read_out = "";
    readTag(DCM_MediaStorageSOPClassUID, dcmFile.getMetaInfo(), tag_read_out, full_path);
    result.mainTags.push_back(std::make_pair(DCM_MediaStorageSOPClassUID, tag_read_out));

    if (DO_ERROR(cfg, 3) || !readExtraTags(dcmFile.getDataset(), full_path, result)) {
        OFString errorString = "Unable to read extra_tags file.\n";
        writeErrorInformationAndMove(path, origFilename, errorString);
        return 1;
    }

    result.conversionNeeded = true;
    if (result.specificCharacterSet.compare("ISO_IR 192") == 0)
    {
        // Incoming DICOM image already has UTF-8 format, conversion is not needed.
        result.conversionNeeded = false;
    }

    auto couldSelectCharacterSet = charsetConverter.selectCharacterSet(result.specificCharacterSet);
    if (DO_ERROR(cfg, 4) || !couldSelectCharacterSet.good()) {
        // There are two different sets of names of character sets in the DICOM standard.
        // If Code Extensions aren't used, it expects ISO 2375 names (e.g., "ISO_IR 192").
        // If Code Extensions are used, it expects names prefixed with ISO 2022, eg "ISO 2022 IR 100".
        // https://dicom.innolitics.com/ciods/vl-photographic-image/sop-common/00080005
        // Sometimes a dicom shows up that only has one character set- indicating it's not using Code Extensions-
        // but the character set is using the ISO 2022 name.

        // So, we are going to tell DCMTK to try to use Code Extensions by giving it a list, ie '\\ISO 2022 IR 100'.
        // If the file didn't really use Code Extensions, this will probably produce garbled tags, but it's probably
        //  better than refusing to process this file at all.

        std::cout << "WARNING: Possible invalid DICOM encoding. Unable to select character set '" << result.specificCharacterSet \
            << "'. Retrying as as if the file meant specify Code Extensions, ie '\\"<<result.specificCharacterSet<<"'"<<std::endl;
        couldSelectCharacterSet = charsetConverter.selectCharacterSet("\\"+result.specificCharacterSet);
        if (DO_ERROR(cfg, 4) || !couldSelectCharacterSet.good()) {
                OFString errorString = "ERROR: Unable to perform character set conversion!\n";
                errorString += couldSelectCharacterSet.text();
                writeErrorInformationAndMove(path, origFilename, errorString);
                return 1;
        }
    }
    OFString newFilename = result.seriesInstanceUID + "#" + origFilename;
    OFString seriesFolder = path + result.seriesInstanceUID + "/";

    if (DO_ERROR(cfg, 5) || !createSeriesFolder(path, result.seriesInstanceUID)) {
        OFString errorString = "Unable to create series folder for ";
        errorString.append(result.seriesInstanceUID);
        errorString.append("\n");
        writeErrorInformationAndMove(path, origFilename, errorString);
        return 1;
    }

    if (DO_ERROR(cfg, 6) || rename(full_path.c_str(), (seriesFolder + newFilename + ".dcm").c_str()) != 0)
    {
        OFString errorString = "Unable to move DICOM file to ";
        errorString.append(seriesFolder + newFilename);
        errorString.append("\n");
        writeErrorInformation(full_path, errorString);
        return 1;
    }

    if (DO_ERROR(cfg, 7) || !writeTagsFile(seriesFolder + newFilename, origFilename, cfg, result))
    {
        OFString errorString = "Unable to write tagsfile file for ";
        errorString.append(newFilename);
        errorString.append("\n");
        rename((seriesFolder + newFilename + ".dcm").c_str(), (path + origFilename).c_str());
        writeErrorInformationAndMove(path, origFilename, errorString);
        return 1;
    }

    if (!cfg.bookkeeperAddress.empty())
    {
        signal(SIGCHLD, SIG_IGN);
        pid_t pid = fork();
        if (pid == 0)
        {
            sendBookkeeperPost(cfg, newFilename, result.sopInstanceUID, result.seriesInstanceUID);
            _exit(0);
        }
        else if (pid < 0)
        {
            std::cout << "WARNING: fork() failed for bookkeeper notification" << std::endl;
        }
    }
}
