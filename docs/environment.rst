Development Environment
=======================

mercure has been developed using Python (and C++ for the getdcmtags module). It depends on various Python packages that are listed in the file requirements.txt. 

A development environment can be easily created using Vagrant, as described in the 
:doc:`Quick Start <../quickstart>` section. When working under Windows, it is alternatively possible to use the Windows Subsystem for Linux (WSL2). It is recommended to use a systemd-type installation of mercure for development work because in this case the code is not distributed across multiple containers.

.. note:: If running the Vagrant installation without additional parameters ("vagrant up"), the latest stable version of mercure will be installed, corresponding to the repository commit currently tagged with `latest-stable <https://github.com/mercure-imaging/mercure/releases/tag/latest-stable>`_. To install the newest  development version, add the argument |subst1| to the Vagrant command ("|subst2|"). This mercure version has the newest features but may be incomplete and still unstable. Use this version with caution. 

.. |subst1| raw:: html

   <strong>--dev</strong>

.. |subst2| raw:: html

   vagrant --dev up


Setting up VS Code
------------------

We highly recommend using Visual Studio Code (VS Code) as code editor. Depending on your individual setup, the code inside your mercure development environment can be edited from your host operating system using the Remote - SSH or Remote - WSL extensions for VS Code. In order to allow VS Code to connect to the VM, you need to add the public SSH key of the Vagrant account to the VM Linux user "mercure" (since mercure is running under the service account "mercure"). This can be done by going through the following steps (this description assumes that you are running the development environment on an Intel-based Windows host computer):

* Install Visual Studio Code on your host computer ([https://code.visualstudio.com](https://code.visualstudio.com/))
  
* Open Visual Studio Code and install the following VS Code extensions (via the tool bar on the left): “Remote - SSH”, “Remote - SSH: Editing Configuration Files”, “Remote Explorer”
  
* Other (optional) recommended extensions: “Python”, “Pylance”, “Git Graph”, “Code Spell Checker”, "Pretty_imports", "GitHub copilot" or "Intellicode"
  
* When the VM is running, click on the bottom left icon in VS Code (“Open a Remote Window”) and select “Connect to Host”. Then click “Configure SSH Hosts…”. Add the following section to the configuration file (assuming the VM has been created in C:\mercure) and save the configuration:

::

   Host mercure
      HostName 127.0.0.1
      User mercure
      Port 2222
      UserKnownHostsFile /dev/null
      StrictHostKeyChecking no
      PasswordAuthentication no
      IdentityFile C:/mercure/.vagrant/machines/default/virtualbox/private_key
      IdentitiesOnly yes
      LogLevel FATAL  


* Open an SSH shell from the (Windows) command shell using the command "vagrant ssh". Copy the content of the following file to the clipboard or Notepad editor: /home/vagrant/.ssh/authorized_keys  

* Make yourself the user "mercure" by typing "sudo su mercure". Create the file /home/mercure/.ssh/authorized_keys and insert the previously copied content (i.e., the public key copied from user vagrant). Change the username at the end of the line from vagrant to mercure. Close the terminal shell by typing exit twice.

* Now, restart VS Code, click on “Connect to Host”, and select mercure from the list. During the first run, select “Linux” as Operating system. VS Code will now install the server application inside the VM. Afterwards, click on "Open Folder". The mercure installation folder is at “/opt/mercure/app”.

* Open a Terminal within VS Code and verify that the Unix user of the terminal is "mercure".

* The development environment is now ready.


Building getdcmtags
-------------------

For building the getdcmtags C++ module, we recommend using the qmake tool from the Qt SDK. A project file for qmake is included in the repository (getdcmtags.pro). Make sure to copy the compiled binary (i.e., the Release build) into the subfolder for the correct Ubuntu version inside the /bin folder. 

getdcmtags depends on the development version of DCMTK, which can be installed with

::

    sudo apt install libdcmtk-dev
