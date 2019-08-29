FAQ
===

.. contents::
    :local:
    :depth: 1

--------

Does Hermes require specific hardware?
--------------------------------------

Hermes should run on a wide range of different hardware configurations. Since the routing process is largely I/O bound, it is recommended to use SSD drives and optical network cards when choosing server specifications. However, this is just a recommendation and not required. Hermes also runs on virtual servers with small foot print. However, it is required to provide sufficient disk space (ideally 500+ GB), so that Hermes can buffer incoming images and keep discarded images for the desired retention period.

--------

What is the purpose of the retention period?
--------------------------------------------

If Hermes receives images and no routing rule does apply, the images will not be deleted but instead kept in the "discard" folder for a retention period. This enables resending the images to the router again if a routing rule had not been properly configured (otherwise, the images would be lost). The retention period for which the files will be kept in the discard folder can be configured in the configuration files hermes.json.


--------

Can the series be dispatched in a certain order?
------------------------------------------------

Hermes dispatches series of a study in the order they were received. If multiple simultaneous connections are used to transmit a study (this depends on the sender), it could happen that the dispatching order is changed. At the moment, there is no mechanism for sorting the dispatching order again. However, if there is sufficient interest among Hermes users, we will implement a feature to enforce sequential dispatching of all series belonging to one study.

--------

What can I do to further improve the performance?
-------------------------------------------------

If you should run into a situation where the default Hermes setup is not able to handle the load of incoming DICOM series, then you can scale up the instances of the router and dispatcher module. By default, only one instance of each module is used (i.e., in the case of the dispatcher, only one series per time is sent outwards). 

All modules have been designed such that multiple module instance can be used in parallel. To enable this, you need to modify the file "services.json" in the "/configuration" folder and duplicate the entry of the module that you want to scale. You need to give the additional module instance a different name (e.g., "dispatcher2"). Moreover, you need to duplicate the corresponding .service file for systemd and rename it accordingly. Note that it is not necessary to scale the receiver module, as the receiver automatically launches a separate process for every DICOM connection.

--------

Why has the getdcmtags module been written in C++?
--------------------------------------------------

Hermes has been written in Python, except for the getdcmtags module that is used to extract the DICOM tags from the received DICOM files. The reason is that this module is launched by the storescp receiver in a forked process whenever a new DICOM image has been received. Because launching the Python runtime environment (i.e., the Python virtual machine) for every received image would take a lot of time, the module has been written in C++ instead.

--------

Is Hermes FDA-approved? Does it have a CE label?
------------------------------------------------

No, at this time, Hermes is neither FDA-approved nor does it have a CE label. However, it uses the Offis DICOM toolkit (DCMTK) for the underlying DICOM communication, which is well-established and used in numerous research and commercial products.

--------

Do you offer professional support for Hermes?
---------------------------------------------

Not currently. But please reach out to us through Github if you encounter any problems or bugs.

