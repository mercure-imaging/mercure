Existing Modules
================

The following list shows exemplary processing modules that have been developed for mercure. If you would like to see your module included in this list, please reach out to us via the :doc:`Discussion Board <../support>`.

Mercure-TestModule
------------------

+---------------+------------------------------------------------------------------------------------+
| Docker Tag    | mercureimaging/mercure-testmodule                                                  |
+===============+====================================================================================+
| Description   | Simple demo module that shows how processing modules can be developed for          | 
|               |                                                                                    | 
|               | mercure. This module applies a Gaussian filter to the incoming image series.       | 
+---------------+------------------------------------------------------------------------------------+
| Parameters    | sigma: Filter strength (default: 7)                                                |
|               |                                                                                    |
|               | series_offset: Offset added to series number (default: 1000)                       |
+---------------+------------------------------------------------------------------------------------+
| Code          | https://github.com/mercure-imaging/mercure-testmodule                              |
+---------------+------------------------------------------------------------------------------------+


Mercure-ExampleInference
------------------------

+---------------+------------------------------------------------------------------------------------+
| Docker Tag    | mercureimaging/mercure-exampleinference                                            |
+===============+====================================================================================+
| Description   | Simple demo module that shows how AI-based inference can be implemented, in this   | 
|               |                                                                                    | 
|               | example using ONNX Runtime as inference engine. The module performs a prostate     | 
|               |                                                                                    | 
|               | segmentation on a T1W prostate MRI scan and generates a segmentation overlay.      | 
+---------------+------------------------------------------------------------------------------------+
| Parameters    | color: Color of the segmentation overlay (name or #rrggbb code, default: yellow)   |
|               |                                                                                    |
|               | transparency: Transparency of the segmentation mask (default: 0.75)                |
|               |                                                                                    |
|               | series_offset: Offset added to series number (default: 1000)                       |
+---------------+------------------------------------------------------------------------------------+
| Code          | https://github.com/mercure-imaging/mercure-exampleinference                        |
+---------------+------------------------------------------------------------------------------------+


Mercure-Anonymizer
------------------

+---------------+------------------------------------------------------------------------------------+
| Docker Tag    | mercureimaging/mercure-anonymizer                                                  |
+===============+====================================================================================+
| Description   | Flexible DICOM anonymization module for mercure that supports project-specific     | 
|               |                                                                                    | 
|               | anonymization settings based on the AET under which the DICOM were received.       | 
+---------------+------------------------------------------------------------------------------------+
| Parameters    | See documentation for usage information                                            |
+---------------+------------------------------------------------------------------------------------+
| Code          | https://github.com/mercure-imaging/mercure-anonymizer                              |
+---------------+------------------------------------------------------------------------------------+


Mercure-TotalSegmentator
------------------------

+---------------+---------------------------------------------------------------------------------------------------------------+
| Docker Tag    | mercureimaging/mercure-totalsegmentator                                                                       |
+===============+===============================================================================================================+
| Description   | mercure integration of the TotalSegmentator model for segmentation of CT scans,                               | 
|               |                                                                                                               | 
|               | developed by the University Hospital Basel:                                                                   |
|               |                                                                                                               | 
|               | https://github.com/wasserth/TotalSegmentator                                                                  |  
+---------------+---------------------------------------------------------------------------------------------------------------+
| Tutorial      | https://github.com/mercure-imaging/mercure-totalsegmentator/blob/main/tutorial_mercure-totalsegmentator.ipynb |
+---------------+---------------------------------------------------------------------------------------------------------------+
| Code          | https://github.com/mercure-imaging/mercure-totalsegmentator                                                   |
+---------------+---------------------------------------------------------------------------------------------------------------+


Mercure-MonaiSegment
------------------------

+---------------+---------------------------------------------------------------------------------------------------------------+
| Docker Tag    | mercureimaging/mercure-monaisegment                                                                           |
+===============+===============================================================================================================+
| Description   | MONAI Segment is a mercure module for rapid deployment of segmentation models                                 |
|               |                                                                                                               | 
|               | hosted in the MONAI model zoo:                                                                                | 
|               |                                                                                                               | 
|               | https://monai.io/model-zoo.html                                                                               |
+---------------+---------------------------------------------------------------------------------------------------------------+
| Tutorial      | https://github.com/mercure-imaging/mercure-monaisegment/blob/main/tutorial_mercure-MonaiSegment.ipynb         |
+---------------+---------------------------------------------------------------------------------------------------------------+
| Code          | https://github.com/mercure-imaging/mercure-monaisegment                                                       |
+---------------+---------------------------------------------------------------------------------------------------------------+
