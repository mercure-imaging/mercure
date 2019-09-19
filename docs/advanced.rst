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

Advanced settings can be reviewed and adjusted on the Configuration page of the webgui. To change the settings, click the "Edit Settings" button at the bottom of the page. Once saved, the different service modules will automatically load the updated configuration. 

.. important:: Make sure to preserve correct JSON formatting of the settings. The webgui will automatically check the syntax before saving the file.

Alternatively to using the webgui, the changes can also be made by directly editing the file hermes.json with a Linux text editor, e.g. nano.

.. important:: When editing the configuration file directly, it is required to shutdown all Hermes services prior to making any changes (via the webgui or systemctl command).

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
offpeak_start            Start of the off-peak work hours (in 24h format)
offpeak_end              End of the off-peak work hours (in 24h format)  
targets                  Configured targets - should be edited via webgui
rules                    Configured rules - should be edited via webgui 
======================== ===========================================================================


Scaling services
----------------

.. note:: This section is coming soon.
