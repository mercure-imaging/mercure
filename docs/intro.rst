What is Hermes?
===============

.. image:: scheme.png
   :width: 550px
   :align: center

Hermes is a solution for routing medical images (DICOM series) to different targets based on routing rules that can be defined using Hermes' web-based user interface. There are various situations when such a "DICOM proxy" or "DICOM router" is needed:

* It is often necessary to send certain studies to special image-analysis software (e.g., all cardiac MR studies to dedicated CMR software). Setting up the corresponding DICOM nodes on every scanner and keeping settings up-to-date is time-consuming and prone to errors
* Manual transfer of studies to application-specific processing tools requires instructing staff which series to send to which analysis software. This can be challenging in larger departments, especially when new software tools or prototypes are installed frequently
* Many scanners only allow configuring a limited number of destination nodes (sometimes only three), which can be insufficient for integrating all required analysis tools
* Sometimes the same series should be sent to multiple destinations (e.g., to compare tools), or the incoming series should be distributed to multiple server instances ("load balancing")

Hermes can automate all of these tasks. While other commercial DICOM routing solutions exist (often with a hefty price tag), Hermes provides a number of unique features that make it attractive especially in research-focused environments:

* Simple-to-use interface with personal accounts for managing routing rules and targets
* Powerful, yet intuitive language for defining routing rules
* Modularized design for high availability, reliability, and scalability
* Extensive monitoring capabilities
* Completely free

.. note:: Hermes has been released as open-source package under the `GPL-3.0 license <https://www.gnu.org/licenses/gpl-3.0.en.html>`_ This means that it can be installed and used without paying any charges. Moreover, the source code can be downloaded and modified if specific functionality is required. Hermes has been written in the Python language and is easily customizable.


Architecture
------------

The Hermes DICOM router consists of multiple service modules that interact with each other. The modularized architecture ensures high reliability of the routing system. For example, in the (unlikely) event that one of the modules crashes or needs to be restarted, the other modules continue to function (e.g., the router continues to receive images from the scanners). Moreover, all modules have been designed such that instances can be scaled-up if higher processing power is needed (e.g., the router can be configured to send out two or more series at the same time). Lastly, the modularized design makes it easy to extend the router's capabilities by replacing individual modules with customized versions.

.. topic:: Receiver

    The receiver service listens to incoming connections, receives DICOM images, and extracts relevant DICOM tags that can be used in the routing rules. It forks a separate process for every incoming connection, so that images from multiple senders can be received simultaneously. Internally, it uses the widely-established storescp tool from the Office DCMTK for image reception. 

.. topic:: Router

    The router service monitors incoming images. Once a series is complete, it checks if any of the configured routing rules applies for the series. If that is case, it will create a dispatch request for the corresponding DICOM target. If no routing rule applies, it will discard the images (the images are kept for a retention period before final deletion, so that accidentally discarded images can still be recovered).

.. topic:: Dispatcher

    The dispatcher service will send the prepared series to the desired target DICOM nodes. In case the DICOM target is temporarily unavailable or if the DICOM transfer fails, it will retry the transfer after a configurable waiting period. After a configurable number of unsuccessful retries, the DICOM images will be moved to an error folder and an alert will be triggered. The transfer can later be restarted again. 

.. topic:: Cleaner

    The cleaner service deletes processed images after the (configurable) retention period has passed. This applies to discarded images (for which no routing rule had triggered) as well as dispatched images (which have been successfully transferred to the desired targets). 

.. topic:: Bookkeeper

    The bookkeeper service acts as central monitoring instance for all router activity. It receives notifications from every router component and stores the data in a PostgreSQL database. This makes it possible to review the routing history of every image that passed through the router. The bookkeeper also stores extended information about the received series (e.g., the used contrast agent), so that it can be used as source for data mining. Moreover, it records all errors or processing abnormalities and can trigger automatic alerts.

.. topic:: Webgui

    The webgui module provides a convenient web-based user interface that allows configuring new targets and routing rules, as well as monitoring the router status. It uses an authorization system with personal accounts, which can either have full administrator rights or read-only rights. All relevant activities in the webgui are recorded by the bookkeeper, so that it is documented which user made which changes in the router configuration. It also provides a tool for testing routing rules prior to activation.
