Release History
===============

Version 0.4.0-alpha.1
---------------------
*Release date: TBA*

* Multiple targets for dispatch
* Redesign of the web UI
* New DICOM Query tool
* Modules can create result files
* Failed dispatch jobs can be restarted
* Timestamps in log files now in local time
* New target types
* New rule syntax (optional)
* Notifications based on module results
* Visual system tag can be shown in navbar
* Getdcmtags: Additional DICOM tags can be extracted
* Support for monitoring with InfluxDB
* Faster DICOM receive mechanism
* Added command-line tool manage.py for creating users
* Rule now honor the urgent/off-peak priority setting
* Notifications now support templating
* Added email notifications
* "Return to sender" option for DICOM targets
* TLS support for secured DICOM transfer
* Processing log and results can be viewed in queue page
* Update option in install.sh to update dependencies, services
* System status flag for missing services


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
