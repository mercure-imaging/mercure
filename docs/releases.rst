Release History
===============

Version 0.4.0-beta.7
---------------------
*Release date: 4/30/2025*

* Bugfixes for UI

Version 0.4.0-beta.6
---------------------
*Release date: 4/24/2025*

* Fix for configuration editor
* Update of dependencies

Version 0.4.0-beta.4
---------------------
*Release date: 4/21/2025*

* Hardening of the web interface against XSS attacks

Version 0.4.0-beta.2
---------------------
*Release date: 4/15/2025*

* Support of multiple targets for dispatching
* Redesign of the web UI
* New DICOM Query tool
* New DICOM Upload tool
* Modules can create result files
* Failed jobs can be restarted
* Timestamps in log files now shown in local time
* New target types
* New rule syntax (optional)
* Added email notifications
* Notifications based on module results
* Notifications now support templating
* Visual system tag can be shown in navbar
* Getdcmtags: Additional DICOM tags can be extracted
* Faster DICOM receive mechanism
* Added command-line tool manage.py for creating users
* Rules now honor the urgent/off-peak priority setting
* "Return to sender" option for DICOM targets
* DICOM targets can pass the incoming AET/AEC
* TLS support for secured DICOM transfer
* Processing log and results can be viewed in queue page
* System status flag for missing services
* Display of additional job information on Queue page
* Improved job search on the Archive Queue page with pagination
* Added button for duplicating rules
* Metabase installation option for results analyses and custom dashboards
* Update option in install.sh to update dependencies, services
* Support for Ubuntu 24.04 LTS

Version 0.3.1-beta.13
---------------------
*Release date: 8/23/2024*

* New JSON editor for configuration and module settings
* Support for rsync and DICOM-TLS transfers
* Improved error messages 
* Integrated Zulip chat for support forum
* Added option to dispatch DICOMs back to sender
* Added support for InfluxDB monitoring
* Changed Vagrant files to use Ubuntu 22.04
* Various bugfixes

Version 0.3.0-beta.1
--------------------
*Release date: 9/18/2023*

* Support for MONAI MAP processing modules
* Support for chaining multiple processing steps
* E-Mail notifications
* Templating of notifications via Jinja2
* Processing modules can return results and trigger notifications
* Option to allow running Docker containers as root users
* Option to extract additional tags from DICOMs, configurable via Configuration page
* Various UI improvements
* Reorganization of Configuration page
* Support of XNAT as dispatching target
* Switch of Docker containers to Ubuntu 22.04

Version 0.2.2-beta.1
--------------------
*Release date: 1/17/2023*

* Support for Ubuntu 22.04
* Added emergency cleaning mechanism if disk space is running low

Version 0.2.1-beta.1
--------------------
*Release date: 6/21/2022*

* Improved Queue page with Archive
* Added support for S3 as Target
* Added support for DICOMweb as Target

Version 0.2.0-beta.7
--------------------
*Release date: 3/7/2022*

* Improved locking mechanism

Version 0.2.0-beta.6
--------------------
*Release date: 3/7/2022*

Version 0.2.0-beta.5
--------------------
*Release date: 3/3/2022*

Version 0.2.0-beta.4
--------------------
*Release date: 2/19/2022*

Version 0.2.0-beta.3
--------------------
*Release date: 2/16/2022*

Version 0.2.0-beta.2
--------------------
*Release date: 2/9/2022*
