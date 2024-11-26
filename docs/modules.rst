Module Development
==================

Developing processing module for mercure is simple! Processing modules are Docker containers that are started by mercure when a DICOM series or study needs to be processed. After instantiating the container, a defined entry script is called to trigger the processing (docker-entrypoint.sh). The DICOM files that should be processed are found in the path specified by the environment variable **MERCURE_IN_DIR**. The processed DICOM files need to be written by the module into the folder specified by the environment variable **MERCURE_OUT_DIR**. Processing settings can be read from the file **task.json** ("process" > "settings"), which is contained in the folder with the incoming images.

Due to use of Docker, processing modules can be written using any programming language -- as long as the code runs under Linux. We prefer writing processing modules in Python because DICOM loaders (pydicom), image processing libraries (scipy, SimpleITK), and AI frameworks (PyTorch, TensorFlow) are widely available. However, other languages can be likewise used (e.g., Julia, Go, C++, Node.js). It is helpful to select an appropriate container image from `Docker Hub <https://hub.docker.com>`_ as basis for building the container (e.g., `continuumio/miniconda3 <https://hub.docker.com/r/continuumio/miniconda3>`_ for Python-based modules), which simplifies the packaging and build process.

A simple Python-based demo module can be found in the following Git repository. This repository can be used as template for own module developments:
https://github.com/mercure-imaging/mercure-testmodule     


DICOM Naming Convention
-----------------------

Depending on whether the rule that triggers the processing is a series-level or study-level rule, the folder with the incoming files (MERCURE_IN_DIR) contains the DICOM images from a single series or from all series that belong to the study. As usual for DICOM images, each image slice is stored in a separate file (multi-frame DICOM files aren't really used in practice). In order to make parsing the files easy, mercure prepends the series UID to the filename of all images belonging to the same series, followed by the separator character #:

.. highlight:: html

::

[series_UID]#[file_UID].dcm

Thus, by splitting the filename at #, images belonging to the same series can be identified. The ordering of the images within one series needs to be taken from the DICOM tags. These can be either read from the DICOM files (e.g., using a library such as pydicom) or they can be read from the corresponding .tags file, which is a JSON file containing the most relevant DICOM tags extracted from each file.


Creating Annotations
--------------------

When integrating AI-supported CAD algorithms, it is often necessary to mark findings in the DICOM series. mercure is providing a Python support library for this purpose, called :doc:`DCMAnnotate <../dcmannotate>`.

Additional mechanisms for reporting findings and analysis results will be added over time.


Distributing Modules
--------------------

There are two different ways of distributing mercure processing modules: a) sharing the module code, and b) uploading the container image to `Docker Hub <https://hub.docker.com>`_. 

When sharing the module code (e.g., by making the source code available via GitHub), users need to build the container locally first before the module can be used. Hence, users need to checkout the repository onto the mercure server and call the "make" command. Afterwards, the module can be configured via the mercure UI. 

When uploading the container image to Docker Hub, users don't have to build the container themselves. The module can be configured right away in the mercure UI, and mercure will automatically download the container image from Docker Hub when processing with the module is requested. mercure will also automatically update the container image if a newer version has been published on Docker Hub. This makes it very easy to distribute developed processing algorithms on a large scale.

Which distribution mechanism should you prefer? While still developing a processing algorithm, it might be better to share the module via a (private) repository (Docker Hub also offers private container images, but this option requires a paid Pro account). When the development/evaluation has finished, it is recommended to publish the module on Docker Hub, as it significantly lowers the burden for installing a module. It is good practice to still make the module code available in a public repository, so that users have the choice to manually build the module and review the processing operations.

