FAQ
===

.. contents::
    :local:
    :depth: 1

--------

Does mercure require specific hardware?
---------------------------------------

mercure runs on a wide range of different hardware configurations. Since the routing process is largely I/O bound, it is recommended to use SSD drives for the storage folders and optical network cards when choosing server specifications. However, this is just a recommendation and not required. mercure also runs on virtual servers with small foot print. However, it is required to provide sufficient disk space (ideally 500+ GB), so that mercure can buffer incoming images and keep discarded images for the desired retention period.

--------

What is the purpose of the retention period?
--------------------------------------------

If mercure receives images and no routing rule does apply, the images will not be deleted but instead kept in the "discard" folder for a retention period. This enables resending the images to the router again if a routing rule had not been properly configured (otherwise, the images would be lost). The retention period for which the files will be kept in the discard folder can be configured in the configuration files mercure.json.


--------

Can the series be dispatched in a certain order?
------------------------------------------------

mercure dispatches series of a study in the order they were received. If multiple simultaneous connections are used to transmit a study (this depends on the sender), it could happen that the dispatching order is changed. At the moment, there is no mechanism for sorting the dispatching order again. However, if there is sufficient need among mercure users, we will implement a feature to enforce sequential dispatching of all series belonging to one study.

--------

What can I do to further improve the performance?
-------------------------------------------------

If you should run into a situation where a default mercure setup is not able to handle the load of incoming DICOM series, then you can scale up the instances of the router, processing, and dispatcher modules. By default, only one instance of each module is used (i.e., in the case of the dispatcher, only one series per time is sent outwards). 

All service modules have been designed such that multiple module instances can be used in parallel. The exact way of scaling up the services depends on the type of mercure installation (systemd/Docker/Nomad). More information on scaling services can be found in the :doc:`Advanced <../advanced>` section.

--------

Why has the getdcmtags module been written in C++?
--------------------------------------------------

mercure has been written in Python, except for the getdcmtags module that is used to extract the DICOM tags from the received DICOM files. The reason is that this module is launched by the storescp receiver in a forked process whenever a new DICOM image has been received. Because launching the Python runtime environment (i.e., the Python virtual machine) for every received image would take a lot of time, the module has been written in C++ instead.

--------

Does mercure use Log4j?
-----------------------

No, mercure has not been written in Java, and it does not use the Log4j logging software.

--------

Is mercure FDA-approved? Does it have a CE label?
-------------------------------------------------

No, at this time, mercure is neither FDA-approved nor does it have a CE label. However, it uses the Offis DICOM toolkit (DCMTK) for the underlying DICOM communication, which is well-established and used in numerous research and commercial products.

--------

Do you offer professional support for mercure?
----------------------------------------------

Not currently. Please post your questions and support requests to the :doc:`Discussion Board <../support>`, and please `submit an issue on Github <https://github.com/mercure-imaging/mercure/issues>`_ if you encounter any bugs or if you would like to propose an enhancement.

--------

Can mercure be used for commercial purpose?
-------------------------------------------

Yes, commercial use of mercure is generally possible, but it must adhere to the policies defined by the GNU GPLv3 open-source license. `Click here <https://choosealicense.com/licenses/gpl-3.0/>`_ to learn more about the permissions, conditions, and limitations of the license. 


--------

Who is behind the project?
--------------------------

mercure has been developed by `Kai Tobias Block <http://tobias-block.net/>`_, `Roy Wiggins <http://roy.red/>`_, and `Joshy Cyriac <https://twitter.com/_joshycyriac_>`_. The development has been supported by the `Center for Advanced Imaging Innovation and Research (CAI2R) <https://cai2r.net>`_ at `NYU Langone Health <https://nyulangone.org>`_.

The name stems from the French translation of Mercury or Mercurius, the god of messages and communication in ancient Roman mythology. The project was initially called Hermes, Mercury's counterpart in Greek mythology, but the name was changed to avoid confusion with another existing software in the medical-imaging field.
