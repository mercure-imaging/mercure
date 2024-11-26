Advanced Topics
===============

Configuration Files
-------------------

mercure stores the configuration in multiple files in the subfolder **/opt/mercure/config**. If you want to backup the configuration or install mercure on another machine, you need to copy all files inside this folder. During installation of mercure, these files are generated from template files contained in the folder **/opt/mercure/app/configuration**.

============== ================
File           Meaning
============== ================
bookkeeper.env Contains IP, port, and DB password for the bookkeeper service
mercure.json   Configured rules, targets, modules, and other mercure settings
services.json  List of configured mercure services (must be modified for scaling services)
users.json     User account information for the web interface
webgui.env     Contains IP, port, and secret key for the web interface
============== ================


Additional Settings
-------------------

Advanced settings can be reviewed and adjusted on the Configuration page of the web interface. To change the settings, click the "Edit Settings" button at the bottom of the page. Once saved, the different service modules will automatically load the updated configuration. 

.. note:: Make sure to preserve correct JSON formatting of the settings. The web interface will automatically check the syntax before saving the file.

Alternatively to using the web interface, the changes can also be made by directly editing the file **mercure.json** with a Linux text editor, e.g. nano.

.. important:: When editing the configuration file directly, it is required to shutdown all mercure services prior to making any changes (via the web interface or systemctl command).

The following settings can be customized (default values can be found in default_mercure.json):

=========================== ===========================================================================
Key                         Meaning
=========================== ===========================================================================
appliance_name              Optional name of the mercure server (useful for multiple servers)
port                        Port for receiving DICOMs (default: 11112). Must be >1024 for non-root service user.
accept_compressed_images    Enable reception of compressed DICOMs. Use with care (see below). Requires that all processing modules can handle compressed images.
incoming_folder             Buffer location for received DICOM files
studies_folder              Buffer location for collecting series belonging to one study
outgoing_folder             Buffer location for series to be dispatched
success_folder              Storage location for completed series until retention period has passed
error_folder                Storage location for files that could not be parsed or dispatched
discard_folder              Storage location for discarded series until retention period has passed
processing_folder           Buffer location for series to be processed
bookkeeper                  IP and port of the bookkeeper instance
graphite_ip                 IP address of the graphite server. Leave empty if none
graphite_port               Port of the graphite server
router_scan_interval        Interval how often the router checks for arrived images (sec)
series_complete_trigger     Time after arrival of last slice when series is considered complete (sec)
study_complete_trigger      Time after arrival of last series when study is considered complete (sec)
study_forcecomplete_trigger Time after which studies are considered complete even if series are missing (sec)
dispatcher_scan_interval    Interval how often the dispatcher checks for series to be sent (sec)
retry_delay                 Delay before retrying to dispatch series after failure (sec)
retry_max                   Maximum number of retries when dispatching
cleaner_scan_interval       Interval how often the cleaner checks for files to be deleted (sec)
retention                   Duration how long files will be kept before deletion (sec)
emergency_clean_percentage  Percentage of disk usage that triggers emergency cleaning  
offpeak_start               Start of the off-peak work hours (24h format)
offpeak_end                 End of the off-peak work hours (24h format)  
targets                     Configured targets - should be edited via web interface
rules                       Configured rules - should be edited via web interface 
modules                     Configured modules - should be edited via web interface 
=========================== ===========================================================================

.. tip:: By default, the mercure DICOM receiver requests incoming DICOM images in uncompressed format. Thus, compressed images need to be decompressed by the sender prior to the transfer (e.g., if sending cases from a PACS that stores images in compressed form). This avoids potential incompatibilities between different implementations of the compression algorithms and ensures best compatibility. If using mercure solely for routing purpose, it can be more efficient to accept images also in compressed form. This can be enabled by setting accept_compressed_images to "True". However, this setting requires that all processing modules that are installed on the mercure server need to be able to handle compressed images (this might not be the case for many modules, including the demo modules). Also, if accepting compressed images, it can happen that the images will still be decompressed during dispatching if the target DICOM node indicates preference for uncompressed images.


Scaling Services
----------------

By default, mercure uses only a single instance of each service module (i.e., in the case of the dispatcher, only one series per time is sent outwards). This provides sufficient performance for most applications. However, for demanding applications with very high volume of incoming DICOM series, it can be necessary run multiple instances of the modules (router, processor, dispatcher). All mercure modules have been written to allow for parallel execution, so that additional instances can be started. 

The exact procedure for scaling up services depends on the type of mercure installation (systemd / Docker / Nomad). The instructions below describe how services can be duplicated when using systemd (which is preferred for high-performance installations).
    
For systemd installations, the file **services.json** in the folder **/opt/mercure/config** needs to be modified. Here, the section of each module that should be scaled needs to be duplicated. For example, for scaling the dispatcher, the "dispatcher" section needs to be duplicated and a unique name needs to be selected for the copy (for the section name and inner keys "name" and "systemd_service", as shown below):
::

    {
        ...
        "dispatcher": {
            "name": "Dispatcher",
            "systemd_service": "mercure_dispatcher.service",
            "docker_service": "mercure_dispatcher_1"
        },
        "dispatcher2": {
            "name": "Dispatcher2",
            "systemd_service": "mercure_dispatcher2.service",
            "docker_service": "mercure_dispatcher_2"
        },
        ...
    }

.. note:: It is not necessary to scale the receiver module, as the receiver automatically launches a separate process for every DICOM connection.

Afterwards, the .service files of the scaled service modules need to be duplicated in the folder **/etc/systemd/system**. For example, if duplicating the dispatcher module as shown above, copy the existing file mercure_dispatcher.service and name it mercure_dispatcher2.service (or whatever has been listed in the file services.json). Enable and start the duplicated service by calling (from an account with sudo rights):
::

  sudo systemctl enable mercure_dispatcher2.service
  sudo systemctl start mercure_dispatcher2.service

As last step, it is necessary to authorize the mercure system user to control the duplicated services. This is done by editing the file **/etc/sudoers.d/mercure** (using a user account with sudo permission) and adding a line for each duplicated service (according to the name specified above). When copying an existing line from the file, make sure to change every occurrence of the service name in the line.


Installation on Apple Macs with ARM Processors
----------------------------------------------

Because the modern Apple Mac computers with M1/M2/M3 processors use a different architecture (ARM) than the older Intel-based Macs, it is not possible to directly run virtual machines with x86 architecture. Therefore, the installation instructions described in the Quickstart section do not work. It is still possible to run mercure on these Macs by using a software-based virtualization software called QEMU. However, this is VERY slow and may only be useful for initial testing purposes. 

The following steps describe how to install and run mercure on a Mac with an Mx processor:

* Download and install  `VirtualBox <https://virtualbox.org/>`_. **Note:** The latest version currently does not support ARM Macs. Go to download page, go to older builds, Version 7.0.8 supports ARM Mac (Developer Preview)

* Make sure that Homebrew is installed

* Run the following commands to install Qemu and Vagrant

::

    brew install qemu
    brew install --cask vagrant
    vagrant plugin install vagrant-qemu

* Make sure that rosetta is installed:

::

    sudo softwareupdate --install-rosetta

* Clone the mercure repository and navigate to the vagrant folder for Macs:

::

    /addons/vagrant/systemd_m1

* Start the mercure VM as usual with:    

::
    
    vagrant --orthanc up

* To increase speed, try the following provider setup in the Vagrantfile:

::
    
    config.vm.provider "qemu" do |qe|
        qe.arch = "x86_64"
        qe.machine = "q35"
        qe.cpu = "max"
        qe.smp = "cpus=2,sockets=1,cores=2,threads=1"
        qe.net_device = "virtio-net-pci"
        qe.extra_qemu_args = %w(-accel tcg,thread=multi,tb-size=512)
        qe.qemu_dir = "/usr/local/share/qemu"
    end    
