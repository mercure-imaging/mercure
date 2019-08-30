Monitoring
==========

Hermes provides three different mechanisms for monitoring the router activity and health.

Log files
---------

All Hermes services write detailed logging information with timestamps into system log files. The most convenient way to review these logs is to use the "Logs" page of the Hermes web interface. Here you can see a separate tab for every service. The logs are updated whenever you switch between tabs and when you click the refresh button on the top-right.

Using the From/To controls, you can limit the time span that is shown in the log viewer.

.. note:: Only the last 1000 lines of each log are displayed to keep the user interface responsive. If you are looking for an older event, use the From/To fields to narrow down the time span.

.. tip:: The log files can also be viewed in the terminal using the journalctl command by providing the service name as argument. For example, "journalctl -u hermes_ui.service" shows the log of the webgui. You can see the names of the different services as tooltip when hovering over the tabs on the "Logs" page.

Graphite
--------

.. note:: This section is coming soon.


Bookkeeer with Redash
---------------------

.. note:: This section is coming soon.


Setting alerts
--------------

.. note:: This section is coming soon.
