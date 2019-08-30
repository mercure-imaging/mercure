Advanced Topics
===============

Configuration files
-------------------

Hermes stores the configuration in multiple files in the subfolder /configuration. If you want to backup the configuration or install Hermes on another machine, you need to copy all files inside this folder.

============== ================
File           Meaning
============== ================
bookkeeper.env Contains the IP, port, and DB password for the bookkeeper
hermes.json    Configured targets, rules, storage location, and other Hermes settings
services.json  Customizable list of used Hermes services
users.json     User information for the webgui
webgui.env     Contains the IP, port, and secret key for the webgui
============== ================


Additional settings
-------------------

Advanced settings can be adjusted in the file hermes.json. These changes need to be done using a Linux text editor, e.g. nano.

.. important:: It is required to shutdown all Hermes services (via the webgui or systemctl command) before this file should be edited. Make sure to preserve correct formatting of the .json file.

The following settings can be customized (default values can be found in default_hermes.json):

======================== ===========================================================================
Key                      Meaning
======================== ===========================================================================
incoming_folder          Buffer location for received DICOM files
outgoing_folder          Buffer location for series to be dispatched
success_folder           Storage location for sent series until retention period has passed
error_folder             Storage location for files that could not be parsed or dispatched
discard_folder           Storage location for discarded series until retention period has passed
bookkeeper               IP and port of the bookkeeper instance
graphite_ip              IP address of the graphite server. Leave empty if none
graphite_port            Port of the graphite server
router_scan_interval     Interval how often the router checks for arrived images (in sec)
series_complete_trigger  Time after arrival of last slice when series is considered complete (in sec)
dispatcher_scan_interval Interval how often the dispatcher checks for series to be sent (in sec)
retry_delay              Delay before retrying to dispatch series after failure (in sec)
retry_max                Maximum number of retries when dispatching
cleaner_scan_interval    Interval how often the cleaner checks for files to be deleted (in sec)
retention                Duration how long files will be kept before deletion (in sec)
targets                  Configured targets - should be edited via webgui
rules                    Configured rules - should be edited via webgui 
======================== ===========================================================================


Scaling services
----------------

.. note:: This section is coming soon.
