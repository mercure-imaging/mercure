Anonymizer
==========

.. note:: The anonymization module comes **without any warranties**. Operation of the software is **solely at the user’s own risk**. The authors take no responsibility for damages of any kind that may arise from usage of the software and distribution of data processed with the software.


Installation
------------

The anonymizer module can be installed on a mercure server using the Modules page of the mercure web interface. Enter the following line into the "Docker tag" field. mercure will automatically download and install the module, and it will automatically install updates when they get published on Docker Hub:

.. code-block::

   mercureimaging/mercure-anonymizer

Alternatively, clone the GitHub repository of the anonymizer and build the Docker container locally on your server. It is recommended to append a distinct version tag to the name of the container image (e.g., mercureimaging/mercure-anonymizer:dev) because otherwise the local version will get replaced if a newer module version gets published on Docker Hub.

If you need to modify the source code, compile the code with Qt Creator for Qt version 5.12 under Ubuntu Linux 20.04 and copy the compiled binary file into the folder /bin. Afterwards, build the Docker container using the make command.

Module Configuration
--------------------

Settings for the anonymizer module can be defined either on the Module page (global module settings) or on the Rule page (rule-dependent processing settings). Both settings are merged prior to the processing. Rule-dependent settings will overrule global module settings if identical settings are defined in both places.

Settings need to be entered in the JSON format.

General and Project-Specific Settings
-------------------------------------

General settings, which are applied to all anonymization steps, as well as project-specific settings can be defined. Project-specific settings are applied when a series (or study) has been sent to mercure with a certain Application Entity Title (AET). For example, if a series has been sent to mercure using the (receiver) AET "myproject", the "general" settings are applied and, in addition, the settings defined in the section "myproject" are applied (if settings are defined in both sections, project settings overrule the duplicate general settings).

The prefix "az\_" can be added to the AET and will be ignored for the project assignment (i.e., both AETs "myproject" and "az\_myproject" will be assigned to project "myproject"). This allows defining one global rule for all anonymization tasks by testing in the Selection Rule if "az\_" is contained in the ReceiverAET (i.e., 'az\_' in @ReceiverAET@).

.. code-block::

   {
       "general": {
           ... define general settings here ...
       },
       "myproject": {
           ... define project specific settings here ...
       }
   }

The following entries should be added to each project section for documentation purpose. The corresponding values can be accessed through macros (see section below) and can be referenced when modifying tags.

.. list-table::
   :header-rows: 1

   * - Entry
     - Description
   * - name
     - Name of the project
   * - owner
     - Owner of the project (e.g., Kerberos ID)
   * - prefix
     - Project prefix


Tag Assignment
--------------

You can specify how each DICOM tag should be processed during the anonymization by adding entries to the configuration sections (either "general" or the project-specific section) with the following form:

.. code-block::

   Format:  "([group],[element])": "[command]"
   Example: "(0010,1001)": "remove"
   Example: "(0010,0010)": "set(@fake_name@)"

The following commands are available:

.. list-table::
   :header-rows: 1

   * - Command
     - Description
   * - keep
     - Keep the tag value as is in the processed file
   * - safe
     - Mark the tag as known and safe, indicating that it does not contain PHI and is non-essential
   * - remove
     - Remove the tag completely from the file
   * - clear
     - Clear the tag value but keep the tag as empty value in the file
   * - set(value)
     - Set the tag to the value provided as parameter (often used with helper macros listed below)
   * - truncdate
     - Take the existing date value and change month and day to January 1st of the year


Additional options exist that affect the processing of the tags. These options can be selected in the general section or in project-specific sections (note that values need to be provided as string, i.e. "true").

.. list-table::
   :header-rows: 1

   * - Option
     - Values
     - Default
     - Description
   * - remove_unknown_tags
     - true / false
     - true
     - Remove all tags for which no assignment has been defined
   * - remove_safe_tags
     - true / false
     - false
     - Remove all tags that have been marked as "safe" (but not with "keep")
   * - remove_curves
     - true / false
     - true
     - Remove all tags associated with embedded curves (groups 5000-501E)
   * - remove_overlays
     - true / false
     - true
     - Remove all tags associated with embedded overlays (groups 6000-601E)
   * - print_assignment
     - true / false
     - false
     - Print the final tag assignment as log output ("general" section only)


Helper Macros
-------------

The following helper macros can be used in combination with the set() command. They need to be used inside the parameter of the set command (e.g., "set(@random_uid@)"):

.. list-table::
   :header-rows: 1

   * - Macro
     - Description
   * - @project_name@
     - Inserts the project name (as specified in the project section)
   * - @project_owner@
     - Inserts the project owner (as specified in the project section)
   * - @project_prefix@
     - Inserts the project prefix (as specified in the project section)
   * - @process_date@
     - Inserts the processing date in format MMddyyyy
   * - @process_time@
     - Inserts the processing time in format hhmmsszzz (i.e., start time of the module)
   * - @random_uid@
     - Inserts a randomly generated UID (without any meaning)
   * - @fake_name@
     - Inserts a fake name, randomly generated from names of greek letters
   * - @fake_mrn@
     - Inserts a fake MRN, generated from a time stamp (unique when using one server)
   * - @fake_acc@
     - Inserts a fake ACC number, generated from a time stamp (unique when using one server)
   * - @value@
     - Inserts the original value of the current tag
   * - @value(gggg,eeee)@
     - Inserts the original value of the tag (gggg,eeee)


Presets
-------

To avoid extensive lists of tag assignments in the configuration, the anonymizer provides presets that can be selected in the general or project-specific sections. The preset initializes the tag assignment prior to evaluating the configuration sections. Individual tags can still be added or modified by writing tag-assignment entries into the general or project sections. Use the "print_assignment" option to review the assignment created by the different presets (see above).

Currently, the following presets exist (please reach out to the authors if you think that the preset assignments are incomplete or if additional specific presets would be useful):

.. list-table::
   :header-rows: 1

   * - Preset
     - Description
   * - default
     - Complete removal of all tags known to contain PHI and removal of unknown (e.g., private) tags
   * - none
     - Empty assignment that keeps all tags as set


Presets can be selected globally or individually for each project by adding a "preset" entry to the general or project-specific section of the configuration (a project-specific setting overrules the general setting):

.. code-block::

   {
       "general": {
           "preset": "default"
       },
       "project1": {
           "preset": "none"
       }
   }
