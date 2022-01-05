DCMAnnotate
===========

DCMAnnotate is a Python support library developed by the mercure team that simplifies creating annotations on DICOM image series. Because currently no well-supported uniform standard for DICOM annotations exists, DCMAnnotate can save the annotations either as DICOM SR files in the TID-1500 format (as, e.g., supported by the OHIF viewer), as "burned in pixels" / "secondary capture" DICOMs (supported by most PACS products), or in the proprietary annotation format of the Visage PACS (for users of the PACS software by Visage Imaging). 

Purpose of DCMAnnotate is to make it easy for AI researchers to implement AI-based image analysis algorithms as mercure processing modules and to integrate the algorithms clinically with standard software infrastructure for reporting findings and results. DCMAnnotate can be included in processing modules written in Python. The output format for the annotations should be taken from the module settings, so that end users can configure the annotation format according to the display capabilities of their local PACS solution.

The documentation and source code can be found on the `DCMAnnotate Github page <https://github.com/mercure-imaging/dcmannotate>`_
