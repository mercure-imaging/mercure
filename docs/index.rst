mercure DICOM Orchestrator
==========================

.. image:: scheme.png
   :width: 550px
   :align: center

mercure is a flexible open-source DICOM orchestration solution with a simple-to-use web interface and extensive monitoring options. It provides functions for routing DICOM studies as well as for running DICOM processing steps, such as executing inference of AI models and dispatching the results to the desired destinations. Processing steps can either be executed directly on the mercure server (as Docker containers) or can be executed on connected cluster nodes, typically located on-premise but potentially also running in the cloud.

.. toctree::
   :hidden:
   :maxdepth: 2

   github.com/mercure-imaging/mercure <https://github.com/mercure-imaging/mercure>

.. toctree::
   :caption: User Guide
   :maxdepth: 2

   intro
   install
   usage
   monitoring
   dashboards
   advanced

.. toctree::
   :maxdepth: 1
   :titlesonly:

   faq

.. toctree::
   :caption: Support
   :maxdepth: 2

   support

.. toctree::
   :caption: Developer Information
   :maxdepth: 2

   modules.rst
   roadmap.rst
