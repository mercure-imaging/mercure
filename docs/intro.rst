What is mercure?
================

.. image:: images/scheme.png
   :width: 550px
   :align: center

mercure is a flexible platform for orchestrating medical images in the standard DICOM format. Orchestration hereby refers to routing image series or complete patient studies to different destinations, or to process image series with different algorithms upon study reception. The action performed when a series or study is received (processing/routing/notification) is defined by rules that can be configured using mercure's web-based user interface.

There are numerous use-cases for such a "DICOM orchestrator" or "DICOM router":

* It is often necessary to send certain studies to special image-analysis software (e.g., all cardiac MR studies to dedicated CMR software). Setting up the corresponding DICOM nodes on every scanner and keeping settings up-to-date is time-consuming and prone to errors
* Manual transfer of studies to application-specific processing tools requires instructing staff which series to send to which analysis software. This can be challenging in larger departments, especially when new software tools or prototypes are installed frequently
* Some scanners only allow configuring a limited number of destination nodes (sometimes only three), which can be insufficient for integrating all required analysis tools
* Sometimes the same series should be sent to multiple destinations (e.g., to compare tools), or the incoming series should be distributed to multiple server instances ("load balancing")
* Images need to be anonymized before sending them to a destination (e.g., for collecting data for research studies that require de-identification)
* Processing algorithms, for example AI-based CAD algorithms, should be integrated into the routine clinical workflow
* Research studies should be tracked and notifications should be sent if specific exams have been performed

mercure can automate all these tasks. While other commercial DICOM routing solutions exist (often with a hefty price tag), mercure provides unique features that make it attractive especially in research-focused environments:

* Powerful, yet intuitive language for defining orchestration rules
* Easy-to-use interface with user accounts for managing rules, targets, and processing modules
* Simple interface for integrating (and sharing) custom processing algorithms
* Modularized architecture for high availability, reliability, and scalability
* Extensive monitoring capabilities
* Completely free and customizable

.. note:: mercure has been released as open-source package under the permissive `MIT license <https://choosealicense.com/licenses/mit>`_. This means that it can be installed and used without paying any charges to the authors. Moreover, the source code can be downloaded and modified if specific functionality is required. mercure has been written mostly in the Python language and is easily customizable.


Architecture
------------

mercure consists of multiple separated service modules that interact with each other. The modularized architecture ensures high reliability and customizability of the software. For example, in the (unlikely) event that one of the modules crashes or needs to be restarted, the other modules continue to function (e.g., the server continues to receive images from imaging devices). Moreover, all modules have been designed such that instances can be scaled-up if more processing power is needed (e.g., mercure can be configured to send out two or more series at the same time). Lastly, the modularized design makes it easy to extend mercure's capabilities by replacing individual modules with customized versions, e.g. if additional transfer protocols should be supported.

.. topic:: Receiver

    The receiver service listens to incoming DICOM connections, receives images, and extracts relevant DICOM tags that can be used in the routing rules. It forks a separate process for every incoming connection, so that images from multiple senders can be received simultaneously. Internally, it uses the widely-established storescp tool from the Office DCMTK package for image reception.

.. topic:: Router

    The router service monitors incoming images. Once a series is complete, it checks if any of the configured routing rules applies for the received series or study. If a rule has been triggered, it creates a corresponding processing, dispatching, or notification request. If no rule applies, it discards the images (the images are kept for a retention period, so that accidentally discarded images can still be recovered).

.. topic:: Processor

    The processor service executes processing modules on received series or studies. To this end, it will start a Docker container with the requested processing module and trigger the module's entry point. If the Docker image is not present on the server (or if a newer version is available), it pulls the image automatically from Docker Hub. Therefore, custom-developed processing algorithms can be easily shared through Docker Hub. After the processing, images will be either dispatched to the target destination or kept until the retention period has passed.

.. topic:: Dispatcher

    The dispatcher service sends the prepared series to the desired target nodes (via DICOM or SFTP transfer). If a target node is temporarily unavailable or if the transfer fails, it repeats the transfer after a configurable waiting period. After a configurable number of unsuccessful retries, the affected DICOM images are moved to an error folder and an alert will be triggered. The transfer can later be restarted.

.. topic:: Cleaner

    The cleaner service permanently deletes processed images after the (configurable) retention period has passed. This applies to discarded images (for which no rule had triggered) as well as to dispatched images (which have been successfully transferred to the desired targets). Because images are kept for a retention period and not deleted right away, it is possible to retrospectively process images for which no routing rule had been defined. The cleaner service is only active during off-peak hours (default: 10pm - 6am) to reduce I/O operations during regular work hours.

.. topic:: Bookkeeper

    The bookkeeper service acts as central monitoring instance for all system activity. It receives notifications from every mercure component and stores the data in a PostgreSQL database. This makes it possible to review the processing history of every image that passed through the router. The bookkeeper also stores extended information about received series (e.g., the used contrast agent), so that it can be used as source for data mining. Moreover, it records all errors or processing abnormalities. Automatic alerts can be triggered based on periodic database queries.

.. topic:: Webgui

    The webgui module provides a convenient web-based user interface that allows configuring new rules, targets, and processing modules, including a tool for testing rules prior to activation. It can be used to monitor the server status, check the processing queue, and review logs. It uses an authorization system with personal accounts, which can have full administrator rights or read-only rights. All relevant activities in the webgui are recorded by the bookkeeper, documenting which user made which configuration change. Moreover, all configuration items can be documented including assignment of an owner.

