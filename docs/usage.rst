Usage
=====

.. important:: The information on this page is still being updated for mercure version 0.2.


Web interface 
-------------

.. image:: ui_login.png
   :width: 550px
   :align: center
   :class: border

mercure can be conveniently configured and controlled using the web-based user interface. To access it, use a modern web browser (e.g., Chrome or Firefox) and enter the IP of your mercure server as URL. Depending on the port that you have selected during the installation (by default 8000), you need to add ":8000" to the URL.

During the installation, mercure creates a "seed account" that you need to use for the first login. You will be asked to change the password after the first login.

.. note:: The login credentials for the first login are: Username = admin, Password = router

To end your session, use the menu on the top-right and select "Logout".

User management
---------------

.. image:: ui_users.png
   :width: 550px
   :align: center
   :class: border

Users can be created, modified, and deleted on the "Users" page. There are two types of users: Normal users, who can view the router configuration and status but not change anything, and administrators, who have full access. Users with administration rights are indicated by an icon with a shield in the user list.

.. tip:: You should create separate accounts for every person using the router. This will allow you to review which user made changes to the router configuration, as mercure is keeping track of all configuration changes.


System status and control
-------------------------

.. image:: ui_status.png
   :width: 550px
   :align: center
   :class: border

You can see the status of the different mercure service components on the "Overview" page. If a service is running, it will be shown in green, otherwise in red. In normal operation, everything should be green. 

.. image:: ui_status_control.png
   :width: 550px
   :align: center
   :class: border

You can start, stop, and restart services by clicking the "Service Control" button. This will show a dialog where you can select which service(s) to control and which operation to execute (e.g., start or stop). If a service does not react at all anymore, it is also possible to kill a service. 

.. note:: If you stop a service, it might take a short moment until the service goes down. This is because the services have been designed to finish the active series before terminating. 

If you followed the mercure installation instructions, then only the bookkeeper service has been started so far. All other services should be red when you login for the first time. Therefore, you should now go ahead and start all services.

.. tip:: If you don't want to use the web interface, you can also manually control the mercure services from the command line. This can be done with the command "systemctl start -u mercure_router.service" (in this example for the routing service). You can find the names of the individual services in the files "/configuration/services.json".

The Overview page also shows you the disk space available in the folder for buffering the incoming DICOM files. If this bar turns yellow or red, make sure to free up disk space as the router will not be able to receiver images if the disk is completely full.


Defining targets
----------------

.. image:: ui_targets.png
   :width: 550px
   :align: center
   :class: border

DICOM nodes that should receive the routed series can be defined and modified on the "Targets" page. Here, you will see a list of the currently configured targets. By clicking on one item, you can see the target details (e.g., the IP address). You can also test if the target can be reached by clicking the "Test" button, which will first try to ping the server and afterwards open a C-Echo association. The target can only receive images if both tests are successful.

Click the "Add New" button to create a new target. This can be done during normal operation of the router, i.e. it is not necessary to stop any of the router service.

.. image:: ui_target_edit.png
   :width: 550px
   :align: center
   :class: border

After choosing a name for the target, you can enter the settings of the DICOM connection settings. Here, you need to enter the IP address, port, the target AET (application entity title) that should be called on the receiver side, and the source AET with which mercure identifies itself to the target.

.. tip:: Some DICOM nodes require that you set a specific target AET, while other systems ignore this setting. Likewise, some DICOM nodes only accept images from a sender who's source AET is known, while others ignore the value. Please check with the vendor/operator of your DICOM node which values are required.

Finally, you can also enter a contact e-mail address. This should be done for reference purpose, so that it can be looked up at a later time who should be contacted if problems with the target exist.


Defining routing rules
----------------------

.. highlight:: none

.. image:: ui_rules.png
   :width: 550px
   :align: center
   :class: border

When you have configured a target, you can add routing rules that define which DICOM series should be forwarded to that target. This can be done on the "Rules" page. Again, it is not necessary to stop mercure while defining new rules. The different mercure services will automatically load the new configuration once the rule has been saved. Click the "Add New" button to create a new rule, or click on any of the existing rules and select "Edit" to modify it.

.. image:: ui_rules_edit.png
   :width: 550px
   :align: center
   :class: border

The routing rule is evaluated for every incoming DICOM series using a set of DICOM sets that have been extracted from the DICOM files. To see the full list of DICOM tags available for writing rules, click the "Show Tags" button.

.. tip:: If you need additional tags that are currently not in the list, please contact us (or modify the getdcmtags module yourself).

Tags have to be used in routing rules in the format @TagName@, for example @PatientName@. When evaluating a routing rule, the contained tags will be replaced with the values read from the received DICOM series.

A series will be dispatched to a target if the routing rule evaluates to True and it will be ignored if it will be ignored if the rule evaluates to False. If none of the routing rules evaluate to True, the series will be discarded.

The routing rules can be written in a Python-like syntax. For example, the rule

:: 

  'CINE' in @SeriesDescription@

will activate for all series that have the word "CINE" in the series description (e.g., "CINE 2ch"). If you only want to send series that are exactly called "CINE", use the following rule instead
:: 

  @SeriesDescription@ = 'CINE'

This rule would not trigger if the series is called "CINE 2ch". Multiple conditions can be combined using the "or" and "and" operators. Here, it is recommended to enclose every sub-condition with "( )". By default, DICOM tags are treated as strings and are case-sensitive. If you want to make your condition case-insensitive, then append ".lower()" to the tag. For example, the rule 
:: 

  @SeriesDescription@.lower() = 'cine'

would trigger for series called "CINE" or "cine". If you want to test for numerical value thresholds (e.g., if the slice thickness is lower than 2mm), you first need to convert the tag into a float by writing the tag inside "float( )". This then allows you to write a rule like
:: 

  float(@SliceThickness@) < 2.0

.. image:: ui_rules_test.png
   :width: 550px
   :align: center
   :class: border

To test a routing rule before activating it, click the icon with the cog wheels on the left side of input box. If you see a red icon in the dialog, the rule is invalid (the dialog will also tell you why). If the rule is valid, the dialog will test if the rule would trigger if a DICOM series with the values shown in the lower part of the dialog would arrive. You can modify these values and test if the rule acts as expected.

.. hint:: If you make a mistake while changing the test values (e.g., missing a quotation mark), you will see a yellow icon. 

If you have validated that your rule triggers as expected, select the desired target from the drop-down list. Also enter an email address into the Contact field and a description into the Comment field, so that it can be looked up at a later time why the rule was defined and who requested it.

Routing rules can be temporarily disabled by setting the "Disabled" field to True. In this case, the rule appears in grayed-out color in the rule list and it will be ignored during processing.







