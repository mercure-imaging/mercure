Development Environment
=======================

mercure has been developed using Python (and C++ for the getdcmtags module). It depends on various Python packages that are listed in the file requirements.txt. 

A development environment can be easily created using Vagrant, as described in the 
:doc:`Quick Start <../quickstart>` section. When working under Windows, it is alternatively possible to use the Windows Subsystem for Linux (WSL2). It is recommended to use a systemd-type installation of mercure for development work because in this case the code is not distributed across multiple containers.

We highly recommend using Visual Studio Code as code editor. Depending on your individual setup, the code inside your mercure development environment can be edited from your host operating system using the Remote - SSH or Remote - WSL extensions for VS Code.

For building the getdcmtags C++ module, we recommend using the Qt5 SDK with QtCreator. A project file for QtCreator is included in the repository (getdcmtags.pro). Make sure to copy the compiled binary (i.e., the Release build) into the subfolder for the correct Ubuntu version inside the /bin folder. 

getdcmtags depends on the development version of DCMTK, which can be installed with

::

    sudo apt install libdcmtk-dev
