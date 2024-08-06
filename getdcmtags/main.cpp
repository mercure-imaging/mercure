#include <stdio.h>
#include <stdlib.h>
#include <sstream>
#include <iomanip>

#include "dcmtk/dcmdata/dcpath.h"
#include "dcmtk/dcmdata/dcerror.h"
#include "dcmtk/dcmdata/dctk.h"
#include "dcmtk/ofstd/ofstd.h"
#include "dcmtk/dcmdata/dcspchrs.h"
#include "dcmtk/dcmdata/dctypes.h"
#include <QPair> 
#include <QString> 
#include <QFile>
#include <QVariant>
#include <QDir>

#include <QFileInfo>
#include <QTextStream>
#include <QVector> 
#include <QVectorIterator>
#include <QCoreApplication>

#include "tags_list.h"

#define VERSION "0.71"


static OFString tagSpecificCharacterSet = "";
static OFString tagSeriesInstanceUID = "";
static OFString tagSOPInstanceUID = "";

static OFString helperSenderAddress = "";
static OFString helperSenderAET = "";
static OFString helperReceiverAET = "";

static std::string bookkeeperAddress = "";
static std::string bookkeeperToken = "";

static QVector<QPair<DcmTagKey, OFString>> additional_tags;
static QVector<QPair<DcmTagKey, OFString>> main_tags;


// Escape the JSON values properly to avoid problems if DICOM tags contains invalid characters
// (see https://stackoverflow.com/questions/7724448/simple-json-string-escape-for-c)
std::string escapeJSONValue(const OFString &s)
{
    std::ostringstream o;
    for (auto c = s.begin(); c != s.end(); c++)
    {
        // Convert control characters into UTF8 coded version
        if (*c == '"' || *c == '\\' || ('\x00' <= *c && *c <= '\x1f'))
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


void sendBookkeeperPost(OFString filename, OFString fileUID, OFString seriesUID)
{
    if (bookkeeperAddress.empty())
    {
        return;
    }

    // Send REST call to bookkeeper instance as forked process, so that the
    // current process can proceed and terminate
    std::string cmd = "wget -q -T 1 -t 3 --post-data=\"filename=";
    cmd.append(filename.c_str());
    cmd.append("&file_uid=");
    cmd.append(fileUID.c_str());
    cmd.append("&series_uid=");
    cmd.append(seriesUID.c_str());
    cmd.append("\"");
    cmd.append(" --header=\"Authorization: Token ");
    cmd.append(bookkeeperToken);
    cmd.append("\" http://");
    cmd.append(bookkeeperAddress);
    cmd.append("/register-dicom -O /dev/null");

    system(cmd.data());
}


void writeErrorInformation(OFString dcmFile, OFString errorString)
{
    OFString filename = dcmFile + ".error";
    OFString lock_filename = dcmFile + ".error.lock";

    // Create lock file to ensure that no other process moves the file
    // while the error information is written
    FILE *lfp = fopen(lock_filename.c_str(), "w+");
    if (lfp == nullptr)
    {
        std::cout << "ERROR: Unable to create lock file " << lock_filename << std::endl;
        // If the lock file cannot be created, something is seriously wrong. In this case,
        // it is better to let the received file remain in the incoming folder.
        return;
    }
    fclose(lfp);

    errorString = "ERROR: " + errorString;
    FILE *fp = fopen(filename.c_str(), "w+");

    if (fp == nullptr)
    {
        std::cout << "ERROR: Unable to write error file " << filename << std::endl;
    }

    fprintf(fp, "%s\n", errorString.c_str());
    fclose(fp);

    // Remove lock file
    remove(lock_filename.c_str());

    std::cout << errorString << std::endl;
}


static DcmSpecificCharacterSet charsetConverter;
static bool isConversionNeeded = false;

#define INSERTTAG(A, B, C)                                                              \
    conversionBuffer = "";                                                              \
    if (isConversionNeeded)                                                             \
    {                                                                                   \
        if (!charsetConverter.convertString(B, conversionBuffer).good())                \
        {                                                                               \
            std::cout << "ERROR: Unable to convert charset for tag " << A << std::endl; \
            std::cout << "ERROR: Unable to process file " << dcmFile << std::endl;      \
        }                                                                               \
    }                                                                                   \
    else                                                                                \
    {                                                                                   \
        conversionBuffer = B;                                                           \
    }                                                                                   \
    fprintf(fp, "\"%s\": \"%s\",\n", A, escapeJSONValue(conversionBuffer).c_str())


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
        return DcmTagKey(OFstatic_cast(Uint16, group),OFstatic_cast(Uint16, elem));
    }
}


bool readTag(DcmTagKey tag, DcmItem* dataset, OFString& out, OFString path_info) {
    if (!dataset->tagExistsWithValue(tag)) {
        return true;
    }
    if (!dataset->findAndGetOFStringArray(tag, out).good())
    {
        OFString errorStr = "Unable to read tag "; 
        errorStr.append(tag.toString());
        errorStr.append("\nReason: ");                                                                                        
        errorStr.append(dataset->findAndGetOFStringArray(tag, out).text());                                            
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


bool readExtraTags(DcmDataset* dataset, OFString path_info) {
    QString filePath = "./dcm_extra_tags";
    if (!QFileInfo::exists(filePath)) {
        filePath = QCoreApplication::applicationDirPath() + "/dcm_extra_tags";
    }
    if (QFileInfo::exists(filePath)) {
        QFile inputFile(filePath);
        inputFile.open(QIODevice::ReadOnly);
        if (!inputFile.isOpen()) {
            std::cout << "Unable to read extra_tags file." << std::endl;
            return false;
        }

        QTextStream stream(&inputFile);
        for (QString line = stream.readLine();
            !line.isNull();
            line = stream.readLine()) {

            OFString out;
            DcmTagKey the_tag = parseTagKey(qPrintable(line));
            if (the_tag == DCM_UndefinedTagKey) {
                std::cout << "Unknown tag " << qPrintable(line) << std::endl;
                return false;
            }
            if (!readTag(the_tag, dataset, out, path_info))
                return false;
            additional_tags.append(QPair<DcmTagKey, OFString>(the_tag, out));
        };
    }
    return true;
}


void writeTagsList(QVector<QPair<DcmTagKey, OFString>>& tags, FILE* fp, OFString& dcmFile, OFString& conversionBuffer) {
    
    QVectorIterator<QPair<DcmTagKey, OFString>> iter(tags);

    const DcmDataDictionary &globalDataDict = dcmDataDict.rdlock();
    while(iter.hasNext())
    {
        auto pair = iter.next();
        const DcmDictEntry *dicent = globalDataDict.findEntry(pair.first, NULL);
        if (dicent == NULL) { // If it's not in the dictionary
            INSERTTAG(pair.first.toString().c_str(), pair.second,"");
        } else {
            INSERTTAG(dicent->getTagName(), pair.second,"");
        }
    }
    dcmDataDict.rdunlock();
}


bool writeTagsFile(OFString dcmFile, OFString originalFile)
{
    OFString filename = dcmFile + ".tags";
    FILE *fp = fopen(filename.c_str(), "w+");

    if (fp == nullptr)
    {
        std::cout << "ERROR: Unable to write tag file " << filename << std::endl;
        return false;
    }

    fprintf(fp, "{\n");
    OFString conversionBuffer = "";

    INSERTTAG("SpecificCharacterSet", tagSpecificCharacterSet, "ISO_IR 100");
    INSERTTAG("SeriesInstanceUID", tagSeriesInstanceUID, "1.2.256.0.7230020.3.1.3.531431169.31.1254476944.91508");
    INSERTTAG("SOPInstanceUID", tagSOPInstanceUID, "1.2.256.0.7220020.3.1.3.541411159.31.1254476944.91518");
    
    INSERTTAG("SenderAddress", helperSenderAddress, "");
    INSERTTAG("SenderAET", helperSenderAET, "STORESCU");
    INSERTTAG("ReceiverAET", helperReceiverAET, "ANY-SCP");

    writeTagsList(main_tags, fp, dcmFile, conversionBuffer);
    writeTagsList(additional_tags, fp, dcmFile, conversionBuffer);

    fprintf(fp, "\"Filename\": \"%s\"\n", originalFile.c_str());
    fprintf(fp, "}\n");

    fclose(fp);
    return true;
}

bool createSeriesFolder(const OFString& path, const OFString& seriesUID) {
    OFString fullPath = path + seriesUID;
    QDir dir(QString::fromStdString(fullPath.c_str()));
    if (!dir.exists()) {
        if (!dir.mkpath(".")) {
            std::cout << "ERROR: Unable to create directory " << fullPath << std::endl;
            return false;
        }
    }
    return true;
}
int main(int argc, char *argv[])
{
    QCoreApplication app( argc, argv );
    
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
        std::cout << "getdcmtags Version " << VERSION << std::endl;
        std::cout << "------------------------" << std::endl
                  << std::endl;
        std::cout << "Usage: [dcm file to analyze] [sender address] [sender AET] [receiver AET] [ip:port of bookkeeper] [api key for bookkeeper]" << std::endl
                  << std::endl;
        return 0;
    }

    helperSenderAddress = OFString(argv[2]);
    helperSenderAET = OFString(argv[3]);
    helperReceiverAET = OFString(argv[4]);

    if (argc > 5)
    {
        bookkeeperAddress = std::string(argv[5]);
    }

    if (argc > 6)
    {
        bookkeeperToken = std::string(argv[6]);
    }

    OFString origFilename = OFString(argv[1]);
    OFString path = "";

    size_t slashPos = origFilename.rfind("/");
    if (slashPos != OFString_npos)
    {
        path = origFilename.substr(0, slashPos + 1);
        origFilename.erase(0, slashPos + 1);
    }
    OFString full_path = path + origFilename;
    DcmFileFormat dcmFile;
    OFCondition status = dcmFile.loadFile(full_path);

    if (!status.good())
    {
        OFString errorString = "Unable to read DICOM file ";
        errorString.append(origFilename);
        errorString.append("\n");
        writeErrorInformation(full_path, errorString);
        return 1;
    }
    DcmDataset* dataset = dcmFile.getDataset();

    readTag(DCM_SpecificCharacterSet, dataset, tagSpecificCharacterSet, full_path);
    readTag(DCM_SOPInstanceUID, dataset, tagSOPInstanceUID, full_path);
    readTag(DCM_SeriesInstanceUID, dataset, tagSeriesInstanceUID, full_path);

    OFString tag_read_out = "";
    for (auto tag: main_tags_list ) {
        tag_read_out = "";
        if (!readTag(tag, dataset, tag_read_out, full_path))
            return 1;
        main_tags.append(QPair<DcmTagKey, OFString>(tag, tag_read_out));
    }
    tag_read_out = "";
    readTag(DCM_MediaStorageSOPClassUID, dcmFile.getMetaInfo(), tag_read_out, full_path);
    main_tags.append(QPair<DcmTagKey, OFString>(DCM_MediaStorageSOPClassUID, tag_read_out));

    if (!readExtraTags(dcmFile.getDataset(), full_path)) {
        return 1;
    }

    isConversionNeeded = true;
    if (tagSpecificCharacterSet.compare("ISO_IR 192") == 0)
    {
        // Incoming DICOM image already has UTF-8 format, conversion is not needed.
        isConversionNeeded = false;
    }

    if (!charsetConverter.selectCharacterSet(tagSpecificCharacterSet).good())
    {
        std::cout << "ERROR: Unable to perform character set conversion! " << std::endl;
        std::cout << "ERROR: Incoming charset is " << tagSpecificCharacterSet << std::endl;
        return 1;
    }

    OFString newFilename = tagSeriesInstanceUID + "#" + origFilename;
    OFString seriesFolder = path + tagSeriesInstanceUID + "/";

    if (!createSeriesFolder(path, tagSeriesInstanceUID)) {
        OFString errorString = "Unable to create series folder for ";
        errorString.append(tagSeriesInstanceUID);
        errorString.append("\n");
        writeErrorInformation(path + origFilename, errorString);
        return 1;
    }

    if (rename((path + origFilename).c_str(), (seriesFolder + newFilename + ".dcm").c_str()) != 0)
    {
        OFString errorString = "Unable to move DICOM file to ";
        errorString.append(seriesFolder + newFilename);
        errorString.append("\n");
        writeErrorInformation(path + origFilename, errorString);
        return 1;
    }

    if (!writeTagsFile(seriesFolder + newFilename, origFilename))
    {
        OFString errorString = "Unable to write tagsfile file for ";
        errorString.append(newFilename);
        errorString.append("\n");
        writeErrorInformation(seriesFolder + newFilename, errorString);

        // Rename DICOM file back to original name and location
        rename((seriesFolder + newFilename + ".dcm").c_str(), (path + origFilename).c_str());
        return 1;
    }

    sendBookkeeperPost(newFilename, tagSOPInstanceUID, tagSeriesInstanceUID);
}
