Modules
------------------

An overview of the installed processing modules can be seen on the "Modules" page. Details are shown by clicking on an item, which also allows editing the module settings.

.. image:: /images/ui/modules.png
   :width: 550px
   :align: center
   :class: border

To setup a new processing module, click the "Install Module" button. Select a unique name for the module. It is possible to install the same processing module multiple times under different names with different settings. Specify the processing module by entering the Docker Tag.

.. note:: The Docker Tag corresponds to the name of the processing module as stored on Docker Hub (example: mercureimaging/mercure-testmodule). For modules that are not distributed via Docker Hub, the Docker container needs to be built locally on the server before it can be used by mercure. 

Afterwards, you can edit additional Docker-specific settings on the "Docker" tab (additional volumes, environment variables, etc.). In most cases, these settings are not needed. 

.. image:: /images/ui/modules_edit.png
   :width: 550px
   :align: center
   :class: border

Settings for the processing module can be defined on the "Settings" tab. These settings must be entered in **JSON format**. The settings entered on the module page are global modules settings, i.e. they are applied whenever the module is used. The global module settings can be overwritten (or extended) by defining settings for the individual rule (thus, the settings passed to the module are the global module settings merged with the rule-specific processing settings).

The "Orchestration" tab allows configuring Nomad-specific settings. If you have a systemd- or Docker-type installation, these settings are irrelevant and can be ignored. It is possible to specify "Execution constraints" if the module should be executed on a certain node of your processing cluster (e.g., if a specific GPU or operating system is needed). The field "Resource requirements" can be used to request resources needed for execution of the module (e.g., the amount of memory or CPU cores).

The "Information" tab can be used to document the current module setup, including a free-text description as well as contact e-mail address.


