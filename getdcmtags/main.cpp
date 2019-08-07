#include <stdio.h>

#include "dcmtk/dcmdata/dcpath.h"
#include "dcmtk/dcmdata/dcerror.h"
#include "dcmtk/dcmdata/dctk.h"
#include "dcmtk/ofstd/ofstd.h"

#define VERSION "0.1b"

static OFString tagPatientName="";
static OFString tagSeriesInstanceUID="";
static OFString tagStudyInstanceUID="";
static OFString tagModality="";
static OFString tagBodyPartExamined="";
static OFString tagProtocolName="";
static OFString tagRetrieveAETitle="";
static OFString tagStationAETitle="";
static OFString tagManufacturer="";
static OFString tagManufacturerModelName="";
static OFString tagStudyDescription="";
static OFString tagProcedureCodeSequence="";
static OFString tagSeriesDescription="";
static OFString tagSeriesDescriptionCodeSequence="";
static OFString tagPatientID="";
static OFString tagPatientBirthDate="";
static OFString tagPatientSex="";
static OFString tagAccessionNumber="";
static OFString tagReferringPhysicianName="";
static OFString tagStudyID="";
static OFString tagSeriesNumber="";
static OFString tagSeriesDate="";
static OFString tagSeriesTime="";
static OFString tagAcquisitionDate="";
static OFString tagAcquisitionTime="";
static OFString tagSequenceName="";
static OFString tagScanningSequence="";
static OFString tagSequenceVariant="";
static OFString tagMagneticFieldStrength="";
static OFString tagStationName="";
static OFString tagDeviceSerialNumber="";
static OFString tagDeviceUID="";
static OFString tagSoftwareVersions="";
static OFString tagContrastBolusAgent="";
static OFString tagImageComments="";


void writeErrorInformation(OFString dcmFile, OFString errorString)
{
    OFString filename=dcmFile+".error";
    errorString="ERROR: "+errorString;
    FILE* fp = fopen(filename.c_str(), "w+");

    if (fp==nullptr)
    {
        std::cout << "ERROR: Unable to write error file " << filename;
    }

    fprintf(fp, "%s\n", errorString.c_str());
    fclose(fp);
    std::cout << errorString << std::endl;
}


#define INSERTTAG(A,B,C) fprintf(fp, "\"%s\": \"%s\",\n",A,B.c_str())

bool writeTagsFile(OFString dcmFile, OFString originalFile)
{
    OFString filename=dcmFile+".tags";
    FILE* fp = fopen(filename.c_str(), "w+");

    if (fp==nullptr)
    {
        std::cout << "ERROR: Unable to write tag file " << filename;
        return false;
    }

    fprintf(fp, "{\n");

    INSERTTAG("Modality",                      tagModality,                      "MR");
    INSERTTAG("BodyPartExamined",              tagBodyPartExamined,              "Example");
    INSERTTAG("ProtocolName",                  tagProtocolName,                  "Example");
    INSERTTAG("RetrieveAETitle",               tagRetrieveAETitle,               "Example");
    INSERTTAG("StationAETitle",                tagStationAETitle,                "Example");
    INSERTTAG("Manufacturer",                  tagManufacturer,                  "Example");
    INSERTTAG("ManufacturerModelName",         tagManufacturerModelName,         "Example");
    INSERTTAG("StudyDescription",              tagStudyDescription,              "Example");
    INSERTTAG("ProcedureCodeSequence",         tagProcedureCodeSequence,         "Example");
    INSERTTAG("SeriesDescription",             tagSeriesDescription,             "Example");
    INSERTTAG("SeriesDescriptionCodeSequence", tagSeriesDescriptionCodeSequence, "Example");
    INSERTTAG("PatientName",                   tagPatientName,                   "Example");
    INSERTTAG("PatientID",                     tagPatientID,                     "Example");
    INSERTTAG("PatientBirthDate",              tagPatientBirthDate,              "Example");
    INSERTTAG("PatientSex",                    tagPatientSex,                    "M");
    INSERTTAG("AccessionNumber",               tagAccessionNumber,               "1234567");
    INSERTTAG("ReferringPhysicianName",        tagReferringPhysicianName,        "Example");
    INSERTTAG("StudyID",                       tagStudyID,                       "Example");
    INSERTTAG("SeriesNumber",                  tagSeriesNumber,                  "99");
    INSERTTAG("SeriesInstanceUID",             tagSeriesInstanceUID,             "Example");
    INSERTTAG("StudyInstanceUID",              tagStudyInstanceUID,              "Example");
    INSERTTAG("SeriesDate",                    tagSeriesDate,                    "Example");
    INSERTTAG("SeriesTime",                    tagSeriesTime,                    "Example");
    INSERTTAG("AcquisitionDate",               tagAcquisitionDate,               "Example");
    INSERTTAG("AcquisitionTime",               tagAcquisitionTime,               "Example");
    INSERTTAG("SequenceName",                  tagSequenceName,                  "Example");
    INSERTTAG("ScanningSequence",              tagScanningSequence,              "Example");
    INSERTTAG("SequenceVariant",               tagSequenceVariant,               "Example");
    INSERTTAG("MagneticFieldStrength",         tagMagneticFieldStrength,         "1.5");
    INSERTTAG("StationName",                   tagStationName,                   "Example");
    INSERTTAG("DeviceSerialNumber",            tagDeviceSerialNumber,            "12345");
    INSERTTAG("DeviceUID",                     tagDeviceUID,                     "Example");
    INSERTTAG("SoftwareVersions",              tagSoftwareVersions,              "Example");
    INSERTTAG("ContrastBolusAgent",            tagContrastBolusAgent,            "");
    INSERTTAG("ImageComments",                 tagImageComments,                 "Comment on Image");

    fprintf(fp, "\"Filename\": \"%s\"\n",originalFile.c_str());
    fprintf(fp, "}\n");

    fclose(fp);
    return true;
}


#define READTAG(TAG,VAR) if ((dcmFile.getDataset()->tagExistsWithValue(TAG)) && (!dcmFile.getDataset()->findAndGetOFString(TAG, VAR).good())) \
                         {  \
                             OFString errorStr="Unable to read tag ";\
                             errorStr.append(TAG.toString()); \
                             errorStr.append("\nReason: "); \
                             errorStr.append(dcmFile.getDataset()->findAndGetOFString(TAG, VAR).text()); \
                             writeErrorInformation(path+origFilename, errorStr); \
                             return 1; \
                         }

int main(int argc, char *argv[])
{           
    if (argc < 2)
    {
        std::cout << std::endl;
        std::cout << "getdcmtags ver " << VERSION << std::endl;
        std::cout << "-------------------" << std::endl << std::endl;
        std::cout << "Usage: [dcm file to analyze]" << std::endl << std::endl;

        return 0;
    }

    OFString origFilename=OFString(argv[1]);
    OFString path="";

    size_t slashPos=origFilename.rfind("/");
    if (slashPos!=OFString_npos)
    {
        path=origFilename.substr(0,slashPos+1);
        origFilename.erase(0,slashPos+1);
    }

    DcmFileFormat dcmFile;
    OFCondition   status=dcmFile.loadFile(path+origFilename);

    if (!status.good())
    {
        OFString errorString="Unable to read DICOM file ";
        errorString.append(origFilename);
        errorString.append("\n");
        writeErrorInformation(path+origFilename, errorString);
        return 1;
    }

    READTAG(DCM_Modality,                      tagModality);
    READTAG(DCM_BodyPartExamined,              tagBodyPartExamined);
    READTAG(DCM_ProtocolName,                  tagProtocolName);
    READTAG(DCM_RetrieveAETitle,               tagRetrieveAETitle);
    READTAG(DCM_StationAETitle,                tagStationAETitle);
    READTAG(DCM_Manufacturer,                  tagManufacturer);
    READTAG(DCM_ManufacturerModelName,         tagManufacturerModelName);
    READTAG(DCM_StudyDescription,              tagStudyDescription);
    READTAG(DCM_ProcedureCodeSequence,         tagProcedureCodeSequence);
    READTAG(DCM_SeriesDescription,             tagSeriesDescription);
    READTAG(DCM_SeriesDescriptionCodeSequence, tagSeriesDescriptionCodeSequence);
    READTAG(DCM_PatientName,                   tagPatientName);
    READTAG(DCM_PatientID,                     tagPatientID);
    READTAG(DCM_PatientBirthDate,              tagPatientBirthDate);
    READTAG(DCM_PatientSex,                    tagPatientSex);
    READTAG(DCM_AccessionNumber,               tagAccessionNumber);
    READTAG(DCM_ReferringPhysicianName,        tagReferringPhysicianName);
    READTAG(DCM_StudyID,                       tagStudyID);
    READTAG(DCM_SeriesNumber,                  tagSeriesNumber);
    READTAG(DCM_SeriesInstanceUID,             tagSeriesInstanceUID);
    READTAG(DCM_StudyInstanceUID,              tagStudyInstanceUID);
    READTAG(DCM_SeriesDate,                    tagSeriesDate);
    READTAG(DCM_SeriesTime,                    tagSeriesTime);
    READTAG(DCM_AcquisitionDate,               tagAcquisitionDate);
    READTAG(DCM_AcquisitionTime,               tagAcquisitionTime);
    READTAG(DCM_SequenceName,                  tagSequenceName);
    READTAG(DCM_ScanningSequence,              tagScanningSequence);
    READTAG(DCM_SequenceVariant,               tagSequenceVariant);
    READTAG(DCM_MagneticFieldStrength,         tagMagneticFieldStrength);
    READTAG(DCM_StationName,                   tagStationName);
    READTAG(DCM_DeviceSerialNumber,            tagDeviceSerialNumber);
    READTAG(DCM_DeviceUID,                     tagDeviceUID);
    READTAG(DCM_SoftwareVersions,              tagSoftwareVersions);
    READTAG(DCM_ContrastBolusAgent,            tagContrastBolusAgent);
    READTAG(DCM_ImageComments,                 tagImageComments);

    OFString newFilename=tagSeriesInstanceUID+"#"+origFilename;

    if (rename((path+origFilename).c_str(), (path+newFilename+".dcm").c_str())!=0)
    {
        OFString errorString="Unable to rename DICOM file to ";
        errorString.append(newFilename);
        errorString.append("\n");
        writeErrorInformation(path+origFilename, errorString);
        return 1;
    }

    if (!writeTagsFile(path+newFilename,origFilename))
    {
        OFString errorString="Unable to write tagsfile file for ";
        errorString.append(newFilename);
        errorString.append("\n");
        writeErrorInformation(path+origFilename, errorString);
        return 1;
    }
}

