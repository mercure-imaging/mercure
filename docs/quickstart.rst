Quick Start
===========

If you want to try out mercure or setup a development environment, you can easily install mercure on your computer via Vagrant, which is an open-source tool for automatically creating and provisioning virtual machines. First, install `VirtualBox <https://virtualbox.org/>`_ on your computer. Afterwards, download `Vagrant <https://vagrantup.org/>`_ and install it. This should work on Windows, Mac, and Linux systems.

.. important:: This way of installing mercure is only suited for testing or development purpose. If you want to install mercure for production use, follow the instructions in the Installation section.

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

Other installation modes
------------------------

In addition to a systemd-based installation, as described above, Vagrant can also be used for Docker-based or Nomad-based installations of mercure. To do this, navigate instead to the folder "/mercure/addons/vagrant/docker" or "/mercure/addons/vagrant/nomad" before calling the "vagrant up" command.

The Nomad UI for monitoring and controlling jobs can be reached at 127.0.0.1:4646.
