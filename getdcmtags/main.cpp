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

#define VERSION "0.5.3"

static OFString tagSpecificCharacterSet = "";
static OFString tagPatientName = "";
static OFString tagSOPInstanceUID = "";
static OFString tagSeriesInstanceUID = "";
static OFString tagStudyInstanceUID = "";
static OFString tagModality = "";
static OFString tagBodyPartExamined = "";
static OFString tagProtocolName = "";
static OFString tagRetrieveAETitle = "";
static OFString tagStationAETitle = "";
static OFString tagManufacturer = "";
static OFString tagManufacturerModelName = "";
static OFString tagStudyDescription = "";
static OFString tagCodeValue = "";
static OFString tagCodeMeaning = "";
static OFString tagSeriesDescription = "";
static OFString tagPatientID = "";
static OFString tagPatientBirthDate = "";
static OFString tagPatientSex = "";
static OFString tagAccessionNumber = "";
static OFString tagReferringPhysicianName = "";
static OFString tagStudyID = "";
static OFString tagSeriesNumber = "";
static OFString tagSeriesDate = "";
static OFString tagSeriesTime = "";
static OFString tagAcquisitionDate = "";
static OFString tagAcquisitionTime = "";
static OFString tagSequenceName = "";
static OFString tagScanningSequence = "";
static OFString tagSequenceVariant = "";
static OFString tagMagneticFieldStrength = "";
static OFString tagStationName = "";
static OFString tagDeviceSerialNumber = "";
static OFString tagDeviceUID = "";
static OFString tagSoftwareVersions = "";
static OFString tagContrastBolusAgent = "";
static OFString tagImageComments = "";
static OFString tagSliceThickness = "";
static OFString tagInstanceNumber = "";
static OFString tagAcquisitionNumber = "";
static OFString tagInstitutionName = "";
static OFString tagMediaStorageSOPClassUID = "";
static OFString tagAcquisitionType = "";
static OFString tagImageType = "";

static OFString helperSenderAET = "";
static OFString helperReceiverAET = "";

static std::string bookkeeperAddress = "";
static std::string bookkeeperToken = "";

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
    INSERTTAG("Modality", tagModality, "MR");
    INSERTTAG("BodyPartExamined", tagBodyPartExamined, "BRAIN");
    INSERTTAG("ProtocolName", tagProtocolName, "COR T1 PIT(POST)");
    INSERTTAG("RetrieveAETitle", tagRetrieveAETitle, "STORESCP");
    INSERTTAG("StationAETitle", tagStationAETitle, "ANY-SCP");
    INSERTTAG("Manufacturer", tagManufacturer, "mercure");
    INSERTTAG("ManufacturerModelName", tagManufacturerModelName, "Router");
    INSERTTAG("StudyDescription", tagStudyDescription, "NEURO^HEAD");
    INSERTTAG("CodeValue", tagCodeValue, "IMG11291");
    INSERTTAG("CodeMeaning", tagCodeMeaning, "MRI BRAIN PITUITARY WITH AND WITHOUT IV CONTRAST");
    INSERTTAG("SeriesDescription", tagSeriesDescription, "COR T1 POST");
    INSERTTAG("PatientName", tagPatientName, "Knight^Michael");
    INSERTTAG("PatientID", tagPatientID, "987654321");
    INSERTTAG("PatientBirthDate", tagPatientBirthDate, "20100101");
    INSERTTAG("PatientSex", tagPatientSex, "M");
    INSERTTAG("AccessionNumber", tagAccessionNumber, "1234567");
    INSERTTAG("ReferringPhysicianName", tagReferringPhysicianName, "Tanner^Willie");
    INSERTTAG("StudyID", tagStudyID, "243211348");
    INSERTTAG("SeriesNumber", tagSeriesNumber, "99");
    INSERTTAG("SOPInstanceUID", tagSOPInstanceUID, "1.2.256.0.7220020.3.1.3.541411159.31.1254476944.91518");
    INSERTTAG("SeriesInstanceUID", tagSeriesInstanceUID, "1.2.256.0.7230020.3.1.3.531431169.31.1254476944.91508");
    INSERTTAG("StudyInstanceUID", tagStudyInstanceUID, "1.2.226.0.7231010.3.1.2.531431169.31.1554576944.99502");
    INSERTTAG("SeriesDate", tagSeriesDate, "20190131");
    INSERTTAG("SeriesTime", tagSeriesTime, "134112.100000");
    INSERTTAG("AcquisitionDate", tagAcquisitionDate, "20190131");
    INSERTTAG("AcquisitionTime", tagAcquisitionTime, "134112.100000");
    INSERTTAG("SequenceName", tagSequenceName, "*se2d1");
    INSERTTAG("ScanningSequence", tagScanningSequence, "SE");
    INSERTTAG("SequenceVariant", tagSequenceVariant, "SP\OSP");
    INSERTTAG("MagneticFieldStrength", tagMagneticFieldStrength, "1.5");
    INSERTTAG("StationName", tagStationName, "MR20492");
    INSERTTAG("DeviceSerialNumber", tagDeviceSerialNumber, "12345");
    INSERTTAG("DeviceUID", tagDeviceUID, "1.2.276.0.7230010.3.1.4.8323329.22517.1564764826.40200");
    INSERTTAG("SoftwareVersions", tagSoftwareVersions, "mercure MR A10");
    INSERTTAG("ContrastBolusAgent", tagContrastBolusAgent, "8.0 ML JUICE");
    INSERTTAG("ImageComments", tagImageComments, "Comment on image");
    INSERTTAG("SliceThickness", tagSliceThickness, "3");
    INSERTTAG("InstanceNumber", tagInstanceNumber, "12");
    INSERTTAG("AcquisitionNumber", tagAcquisitionNumber, "15");
    INSERTTAG("InstitutionName", tagInstitutionName, "Some institution");
    INSERTTAG("MediaStorageSOPClassUID", tagMediaStorageSOPClassUID, "1.2.840.10008.5.1.4.1.1.4");
    INSERTTAG("AcquisitionType", tagAcquisitionType, "SPIRAL");
    INSERTTAG("ImageType", tagImageType, "ORIGINAL");

    INSERTTAG("SenderAET", helperSenderAET, "STORESCU");
    INSERTTAG("ReceiverAET", helperReceiverAET, "ANY-SCP");

    fprintf(fp, "\"Filename\": \"%s\"\n", originalFile.c_str());
    fprintf(fp, "}\n");

    fclose(fp);
    return true;
}

#define READTAG(TAG, SOURCE, VAR)                                                                                             \
    if ((dcmFile.SOURCE->tagExistsWithValue(TAG)) && (!dcmFile.SOURCE->findAndGetOFStringArray(TAG, VAR).good()))             \
    {                                                                                                                         \
        OFString errorStr = "Unable to read tag ";                                                                            \
        errorStr.append(TAG.toString());                                                                                      \
        errorStr.append("\nReason: ");                                                                                        \
        errorStr.append(dcmFile.SOURCE->findAndGetOFStringArray(TAG, VAR).text());                                            \
        writeErrorInformation(path + origFilename, errorStr);                                                                 \
        return 1;                                                                                                             \
    }                                                                                                                         \
    for (size_t i = 0; i < VAR.length(); i++)                                                                                 \
    {                                                                                                                         \
        switch (VAR[i])                                                                                                       \
        {                                                                                                                     \
        case 13:                                                                                                              \
            VAR[i] = ';';                                                                                                     \
            break;                                                                                                            \
        case 10:                                                                                                              \
            VAR[i] = ' ';                                                                                                     \
            break;                                                                                                            \
        case 34:                                                                                                              \
            VAR[i] = 39;                                                                                                      \
            break;                                                                                                            \
        default:                                                                                                              \
            break;                                                                                                            \
        }                                                                                                                     \
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

    if (argc < 4)
    {
        std::cout << std::endl;
        std::cout << "getdcmtags Version " << VERSION << std::endl;
        std::cout << "------------------------" << std::endl
                  << std::endl;
        std::cout << "Usage: [dcm file to analyze] [sending AET] [receiving AET] [ip:port of bookkeeper] [api key for bookkeeper]" << std::endl
                  << std::endl;
        return 0;
    }

    helperSenderAET = OFString(argv[2]);
    helperReceiverAET = OFString(argv[3]);

    if (argc > 4)
    {
        bookkeeperAddress = std::string(argv[4]);
    }

    if (argc > 5)
    {
        bookkeeperToken = std::string(argv[5]);
    }


    OFString origFilename = OFString(argv[1]);
    OFString path = "";

    size_t slashPos = origFilename.rfind("/");
    if (slashPos != OFString_npos)
    {
        path = origFilename.substr(0, slashPos + 1);
        origFilename.erase(0, slashPos + 1);
    }

    DcmFileFormat dcmFile;
    OFCondition status = dcmFile.loadFile(path + origFilename);

    if (!status.good())
    {
        OFString errorString = "Unable to read DICOM file ";
        errorString.append(origFilename);
        errorString.append("\n");
        writeErrorInformation(path + origFilename, errorString);
        return 1;
    }

    READTAG(DCM_SpecificCharacterSet, getDataset(), tagSpecificCharacterSet);
    READTAG(DCM_Modality, getDataset(), tagModality);
    READTAG(DCM_BodyPartExamined, getDataset(), tagBodyPartExamined);
    READTAG(DCM_ProtocolName, getDataset(), tagProtocolName);
    READTAG(DCM_RetrieveAETitle, getDataset(), tagRetrieveAETitle);
    READTAG(DCM_StationAETitle, getDataset(), tagStationAETitle);
    READTAG(DCM_Manufacturer, getDataset(), tagManufacturer);
    READTAG(DCM_ManufacturerModelName, getDataset(), tagManufacturerModelName);
    READTAG(DCM_StudyDescription, getDataset(), tagStudyDescription);
    READTAG(DCM_CodeValue, getDataset(), tagCodeValue);
    READTAG(DCM_CodeMeaning, getDataset(), tagCodeMeaning);
    READTAG(DCM_SeriesDescription, getDataset(), tagSeriesDescription);
    READTAG(DCM_PatientName, getDataset(), tagPatientName);
    READTAG(DCM_PatientID, getDataset(), tagPatientID);
    READTAG(DCM_PatientBirthDate, getDataset(), tagPatientBirthDate);
    READTAG(DCM_PatientSex, getDataset(), tagPatientSex);
    READTAG(DCM_AccessionNumber, getDataset(), tagAccessionNumber);
    READTAG(DCM_ReferringPhysicianName, getDataset(), tagReferringPhysicianName);
    READTAG(DCM_StudyID, getDataset(), tagStudyID);
    READTAG(DCM_SeriesNumber, getDataset(), tagSeriesNumber);
    READTAG(DCM_SOPInstanceUID, getDataset(), tagSOPInstanceUID);
    READTAG(DCM_SeriesInstanceUID, getDataset(), tagSeriesInstanceUID);
    READTAG(DCM_StudyInstanceUID, getDataset(), tagStudyInstanceUID);
    READTAG(DCM_SeriesDate, getDataset(), tagSeriesDate);
    READTAG(DCM_SeriesTime, getDataset(), tagSeriesTime);
    READTAG(DCM_AcquisitionDate, getDataset(), tagAcquisitionDate);
    READTAG(DCM_AcquisitionTime, getDataset(), tagAcquisitionTime);
    READTAG(DCM_SequenceName, getDataset(), tagSequenceName);
    READTAG(DCM_ScanningSequence, getDataset(), tagScanningSequence);
    READTAG(DCM_SequenceVariant, getDataset(), tagSequenceVariant);
    READTAG(DCM_MagneticFieldStrength, getDataset(), tagMagneticFieldStrength);
    READTAG(DCM_StationName, getDataset(), tagStationName);
    READTAG(DCM_DeviceSerialNumber, getDataset(), tagDeviceSerialNumber);
    READTAG(DCM_DeviceUID, getDataset(), tagDeviceUID);
    READTAG(DCM_SoftwareVersions, getDataset(), tagSoftwareVersions);
    READTAG(DCM_ContrastBolusAgent, getDataset(), tagContrastBolusAgent);
    READTAG(DCM_ImageComments, getDataset(), tagImageComments);
    READTAG(DCM_SliceThickness, getDataset(), tagSliceThickness);
    READTAG(DCM_InstanceNumber, getDataset(), tagInstanceNumber);
    READTAG(DCM_AcquisitionNumber, getDataset(), tagAcquisitionNumber);
    READTAG(DCM_InstitutionName, getDataset(), tagInstitutionName);
    READTAG(DCM_MediaStorageSOPClassUID, getMetaInfo(), tagMediaStorageSOPClassUID);
    READTAG(DCM_AcquisitionType, getDataset(), tagAcquisitionType);
    READTAG(DCM_ImageType, getDataset(), tagImageType);

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

    if (rename((path + origFilename).c_str(), (path + newFilename + ".dcm").c_str()) != 0)
    {
        OFString errorString = "Unable to rename DICOM file to ";
        errorString.append(newFilename);
        errorString.append("\n");
        writeErrorInformation(path + origFilename, errorString);
        return 1;
    }

    if (!writeTagsFile(path + newFilename, origFilename))
    {
        OFString errorString = "Unable to write tagsfile file for ";
        errorString.append(newFilename);
        errorString.append("\n");
        writeErrorInformation(path + origFilename, errorString);

        // Rename DICOM file back to original name, so that the name matches to
        // the .error file and can be moved to the error folder by the router
        rename((path + newFilename + ".dcm").c_str(), (path + origFilename).c_str());
        return 1;
    }

    sendBookkeeperPost(newFilename, tagSOPInstanceUID, tagSeriesInstanceUID);
}
