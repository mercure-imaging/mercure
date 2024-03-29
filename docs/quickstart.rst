Quick Start
===========

If you want to try out mercure or setup a development environment, you can easily install mercure on your computer via Vagrant, which is an open-source tool for automatically creating and provisioning virtual machines. First, install `VirtualBox <https://virtualbox.org/>`_ on your computer. Afterwards, download `Vagrant <https://vagrantup.com/>`_ and install it. This should work on Windows, Intel-based Mac, and Linux systems.

.. important:: This way of installing mercure is only suited for testing or development purpose. If you want to install mercure for production use, follow the instructions in the Installation section.

.. note:: These instructions work for Apple Mac computers with Intel CPUs, but not for the newer Macs with M1/M2/M3 (ARM) processors. The :doc:`Advanced Topics <../advanced>` section contains instructions for running mercure on ARM-based Macs.


Open a terminal shell and checkout the mercure repository by calling
::

    git clone https://github.com/mercure-imaging/mercure.git

and navigate to the subfolder "/mercure/addons/vagrant/systemd".

Install and start mercure by calling (will take some time and create lots of output!)
::

    vagrant up

.. tip:: If you encounter problems during the setup of the virtual machine (e.g., error messages related to the SSH keys), try opening the VirtualBox UI, select the newly created VM, and click on "Show". In our experience, this resolves occasional problems during the VM boot process.

mercure should now be running inside a virtual machine and be accessible from your host computer. Open a web browser (Chrome or Firefox) and open the address 127.0.0.1:8000. You should now see the mercure login screen.

.. note:: The login credentials for the first login are: Username = admin, Password = router

The DICOM receiver of mercure is listening at port 11112. If you want to send DICOM images to mercure from a folder on your host computer, you can do this with the "dcmsend" tool of the `Offis DCMTK tookit <https://dicom.offis.de/dcmtk.php.en>`_ by calling
::

    dcmsend 127.0.0.1 11112 *.dcm

If you want to shutdown or destroy this installation of mercure, call "vagrant halt" or "vagrant destroy".

.. tip:: If running the Vagrant installation without additional parameters ("vagrant up"), the latest stable version of mercure will be installed. To install the newest development version, add the argument |subst1| to the Vagrant command ("|subst2|"). This mercure version has the newest features but may be incomplete and still unstable. Use the dev version with caution. 

.. |subst1| raw:: html

   <strong>--dev</strong>

.. |subst2| raw:: html

   vagrant --dev up


Including Orthanc and OHIF
--------------------------

When testing mercure or developing modules, it is helpful to use a local PACS as dummy target. Therefore, we included an option to automatically install the open-source Orthanc PACS and OHIF DICOM viewer alongside mercure if you call the Vagrant installation command with the following argument
::

    vagrant --orthanc up

The Orthanc PACS is now listening to DICOM connections at port 4242. You can now add Orthanc as target in mercure via the Target page. Use the IP address 127.0.0.1 and Port 4242. You can use any value for the AET and AEC settings.

The user interface of Orthanc can be reached by opening 127.0.0.1:8042 in a web browser. Use the username "orthanc" and password "orthanc" if an authorization dialog appears.

While Orthanc already comes with a built-in DICOM viewer, we also included the open-source OHIF viewer because it supports displaying DICOM SR annotations. It can be reached at address 127.0.0.1:8008 (username "orthanc", password "orthanc"). The OHIF viewer connects to the Orthanc PACS and will show the same studies.

.. tip:: If the OHIF viewer only shows "Loading...", the authentication credentials might be missing. Try refreshing the page while precessing the SHIFT key. This will enforce that the authentication dialog gets displayed.

.. important:: The Orthanc and OHIF installation described here is only intended for local testing and development purpose. Do not expose these ports to the general network, as the installation might not be fully secured.


First steps
-----------

After installing mercure and Orthanc using Vagrant, you can go through the following exercise to familiarize yourself with mercure. These instructions assume a systemd-type installation. In this example, a prostate segmentation is performed as processing step. Afterwards, the input images and segmentation masks are sent to the Orthanc instance. This example is also demonstrated in the `mercure overview video <https://youtu.be/LyJ4iQE1yLk?t=567>`_.

.. note:: The prostate segmentation model used here has been developed for demonstration purpose only. It does not provide state-of-the-art segmentation performance.

* Log into the mercure web interface running at 127.0.0.1:8000 (username = admin, initial password = router).
* Go to the Targets page and click "Add New". Enter "Orthanc" as name for the target. Select DICOM as target type and enter the following connection parameters: Host/IP = 127.0.0.1, IP = 4242, AET Target = orthanc, AET Source = mercure. Click "Save".
* Test that mercure can talk to Orthanc by clicking on the entry "Orthanc" in the target list and clicking "Test". Both the Ping and C-Echo test should show a green check mark.
* Go to the Modules page and click "Install Module". Enter "ProstateSegmentation" as name. For the Docker tag, enter "mercureimaging/mercure-exampleinference", which is the name under which the demo prostate segmentation model has been published on  `Docker Hub <https://hub.docker.com/r/mercureimaging/mercure-exampleinference>`_. 
* Go to the Rules page and click "Add New". Enter "ProstateSegmentation" as name and click "Create" to get to the Edit Rule page. For the Selection Rule, enter "True" (thus, any received DICOM series will activate this rule). Under Action, select "Processing & Routing". Go to the Processing tab and select the Module "ProstateSegmentation". Check "Retain Input Images" under Data Flow. Go to the Routing page and select the Target "Orthanc". Then click "Save".
* You are now ready to test the configured processing rule by sending cases to the mercure server. The segmentation model expects T1-weighted post-contrast MRI images with square size. If you don't have such images, visit the `GitHub page of the mercure-exampleinference module <https://github.com/mercure-imaging/mercure-exampleinference>`_ and go through the steps under "Sample Data", which will download a few publicly available datasets.
* You can send cases to mercure using the "dcmsend" utility from the Offis DCMTK open-source package. If you don't have it installed, you can download it  `here <https://dicom.offis.de/download/dcmtk/dcmtk366/bin/>`_.
* On your host computer, open a command shell and go to a folder with a test case. Send the images to mercure with the command |subst3|.
* After receiving the images, mercure will start processing the case. Note that, by default, there is a 60 sec reception timeout before mercure considers the case as complete (this can be changed in the configuration).
* You can monitor the progress by going to the Queue page of the web interface. During the first run, mercure will download the module container from Docker Hub. Therefore, the processing time is longer for the first case. Note that the Queue page does not update automatically (unless you toggle the Auto Update switch on the top-right). Click the "Refresh Now" button to update the information. The processing is complete when the Processing and Routing services return to the "Idle" state.
* The segmentation results can now be reviewed in Orthanc. To this end, open the address 127.0.0.1:8042 (user = orthanc, password = orthanc). Click on "All Patients", which should show the case that has been processed. Click on the patient, then on the study, then click the yellow button "Stone Web Viewer" on the left side. You should now see two image series: one with the original input images, and one with the generated segmentation mask in yellow color blended with the images.

If you are interested how this segmentation module has been implemented, take a look at the source code `available in GitHub <https://github.com/mercure-imaging/mercure-exampleinference>`_ (the relevant file here is inference.py). This repository can be used as starting point for implementing own DL-based processing modules. More information on module development can be found :doc:`here <../modules>`.

.. |subst3| raw:: html

   "dcmsend 127.0.0.1 11112 *.dcm"


Other installation modes
------------------------

In addition to a systemd-based installation, as described above, Vagrant can also be used for Docker-based or Nomad-based installations of mercure. To do this, navigate instead to the folder "/mercure/addons/vagrant/docker" or "/mercure/addons/vagrant/nomad" before calling the "vagrant up" command.

The Nomad UI for monitoring and controlling jobs can be reached at 127.0.0.1:4646.
