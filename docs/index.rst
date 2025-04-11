.. image:: /images/header.jpg
   :align: center
   :class: headerimage

mercure DICOM Orchestrator
==========================

mercure is a flexible open-source DICOM orchestration platform. It offers an intuitive web-based user interface as well as extensive monitoring options, making it suitable for routine applications that require high availability. It can be used for dispatching DICOM studies to different targets based on easily definable routing rules and for processing DICOM series with custom-developed algorithms, such as inference of AI models for medical imaging. Processing algorithms can either be executed directly on a mercure server (as Docker containers) or can be executed on connected cluster nodes, typically located on premise but possibly also running as cloud instances. Implemented processing modules can be shared via Docker Hub.

.. image:: /images/scheme.png
   :width: 550px
   :align: center
   :class: spacerbottom20

.. container:: bullet
   
   mercure now supports `MONAI Application Packages (MAP) <https://github.com/Project-MONAI/monai-deploy/blob/main/guidelines/monai-application-package.md/>`_ as processing modules. Therefore, it can be used as lightweight solution for the clinical integration of AI models developed using the `MONAI Open-Source Framework <https://monai.io/>`_.

.. raw:: html

   <div class="videocontainer_desktop">
   <iframe width="560" height="315" src="https://www.youtube.com/embed/LyJ4iQE1yLk?start=0&amp;rel=0&amp;showinfo=0" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen class="align-center videobox"></iframe>
   </div>
   <div class="videocontainer_mobile">
   <iframe width="100%" height="100%" src="https://www.youtube.com/embed/LyJ4iQE1yLk?start=0&amp;rel=0&amp;showinfo=0" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen class="align-center videobox" style="position: absolute; top: 0; left: 0;"></iframe>
   </div>

.. note:: mercure is still under active development. Please report bugs and feature requests via our `GitHub Issue Tracker <https://github.com/mercure-imaging/mercure/issues>`_
   :class: spacerbottom30

.. toctree::
   :hidden:
   :maxdepth: 2

   github.com/mercure-imaging/mercure <https://github.com/mercure-imaging/mercure>

.. toctree::
   :caption: User Guide
   :glob:

   intro
   quickstart
   install
   usage/index
   advanced
   monitoring
   dashboards
   
.. toctree::
   :maxdepth: 1
   :titlesonly:

   faq

.. toctree::
   :caption: Modules
   :maxdepth: 1
   :titlesonly:

   modules
   module_list
   anonymizer
   dcmannotate

.. toctree::
   :caption: Support
   :maxdepth: 1
   :titlesonly:

   support
   releases

.. toctree::
   :caption: Developer Information
   :titlesonly:
   :maxdepth: 2

   environment
   source/index
   