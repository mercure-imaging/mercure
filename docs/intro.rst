What is Hermes?
===============

Hermes is a solution for routing medical images (DICOM series) to different targets based on routing rules
that can be defined using Hermes' web-based user interface. There are various applications for such a "DICOM proxy" or "DICOM router":

* It is often necessary to send certain studies to special image-analysis software (e.g., all cardiac MR studies to a dedicated cardiac MR software). However, setting up the DICOM nodes on every scanner and keeping settings up-to-date is time-consuming and prone to errors. 

* Manual transfer of studies to application-specific processing tools requires training staff which series to send to which analysis software. This can be challenging in larger departments, especially when new software tools or prototypes are installed frequently. 

* Many scanners only allow configuring few destination nodes (often only three).

* Sometimes the same series should be sent to multiple destinations (e.g., to compare tools), or the incoming series should be distributed to multiple server instances (load balancing).



.. note:: This section is coming soon.
