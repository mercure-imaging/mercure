Code Documentation
==================

mercure has been developed using Python (and C++ for the getdcmtags module). It depends on a number of Python packages that are listed in the file requirements.txt. If you follow the installation instructions, you should already have a proper development environment. We recommend using Visual Studio Code for the development. 

For building the getdcmtags C++ module, we recommend using the Qt5 SDK with QtCreator. A project file for QtCreator is included in the repository (getdcmtags.pro). Make sure to copy the compiled binary into the /bin folder (preferably the Release build). getdcmtags depends on the development version of DCMTK, which can be installed with

::

    sudo apt install libdcmtk-dev

The Python part of the mercure code has been divided into separate service modules. These modules share the Python files contained in the common package and the packages with corresponding name (e.g., package routing is used by the router service).

.. toctree::
   :maxdepth: 1

   bookkeeper
   cleaner
   dispatcher
   router
   webgui

.. toctree::
   :maxdepth: 1
   
   common
   dispatch
   routing
   webinterface
