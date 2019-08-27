What is Hermes?
===============

Hermes is a solution for routing medical images (DICOM series) to different targets based on routing rules that can be defined using Hermes' web-based user interface. There are various situations when such a "DICOM proxy" or "DICOM router" is needed:

* It is often necessary to send certain clinical studies to special image-analysis software (e.g., all cardiac MR studies to dedicated CMR software). Setting up the corresponding DICOM nodes on every scanner and keeping settings up-to-date is time-consuming and prone to errors
* Manual transfer of studies to application-specific processing tools requires teaching staff which series to send to which analysis software. This can be challenging in larger departments, especially when new software tools or prototypes are installed frequently
* Many scanners only allow configuring a limited number of destination nodes (often only three), which can be insufficient for integrating all required analysis tools
* Sometimes the same series should be sent to multiple destinations (e.g., to compare tools), or the incoming series should be distributed to multiple server instances ("load balancing")

Hermes can automate all of these tasks. While other commercial DICOM routing solutions exist (often with a high price tag), Hermes provides a number of unique features that makes it attractive especially in research-focused environments:

* Simple-to-use interface with personalized accounts to manage routing rules and targets
* Very powerful, yet intuitive language for writing routing rules
* Modularized design for high availability, reliability, and scalability
* Extensive monitoring capabilities
* Completely free

Hermes has been released as open-source package under the GPL-3.0 license. This means that it can be installed and used without paying any charges. Moreover, the source code can be downloaded and modified if specific functionality is required. Hermes has been written in the Python language and is easily customizable.
